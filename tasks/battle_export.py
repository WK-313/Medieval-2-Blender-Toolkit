"""Convert an exported GLB to the shared battle mesh representation.

The caller supplies the game's bone-slot order; glTF joint order is not a game
slot order. This bridge is independent of UI/backend selection.
"""
from array import array
import math
import os
import tempfile
from pathlib import Path
import re
import struct

from mathutils import Matrix, Vector
from ..m2formats import mesh, modelexport


def meshFromGLB(path, bone_order):
    """Read static bind geometry, splitting seams and keeping two influences."""
    raw = Path(path).read_bytes()
    if len(raw) < 28 or raw[:4] != b'glTF':
        raise ValueError('Expected an exported GLB')
    version, length = struct.unpack_from('<II', raw, 4)
    if version != 2 or length != len(raw):
        raise ValueError('Unsupported or truncated GLB')
    json_length, json_type = struct.unpack_from('<II', raw, 12)
    binary_header = 20 + json_length
    if json_type != 0x4E4F534A or json_length % 4 or binary_header + 8 > len(raw):
        raise ValueError('Invalid GLB JSON chunk')
    binary_length, binary_type = struct.unpack_from('<II', raw, binary_header)
    if binary_type != 0x004E4942 or binary_length % 4 or binary_header + 8 + binary_length != len(raw):
        raise ValueError('Invalid GLB binary chunk')
    doc, binary = modelexport.read_glb(raw)
    if len(doc.get('buffers', [])) != 1 or doc['buffers'][0].get('uri'):
        raise ValueError('Only a single embedded GLB buffer is supported')
    if doc['buffers'][0]['byteLength'] > len(binary):
        raise ValueError('Truncated GLB buffer')
    if not bone_order or len(bone_order) > 256:
        raise ValueError('Supply between 1 and 256 game bone slots')
    names = [name.replace(' ', '__') for name in bone_order]
    if len(set(names)) != len(names):
        raise ValueError('Game bone-slot names must be unique')
    slots = {name: index for index, name in enumerate(names)}
    out = mesh.MeshFile(source=str(path), format='mesh', bones=list(bone_order),
                        bone_links=list(range(len(bone_order))))
    ids = bytearray()
    formats = {5120: 'b', 5121: 'B', 5122: 'h', 5123: 'H', 5125: 'I', 5126: 'f'}
    widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
    cache = {}

    def item(items, index, label):
        if type(index) is not int or not 0 <= index < len(items):
            raise ValueError('Invalid GLB ' + label + ' index')
        return items[index]

    def accessor(index):
        if index in cache:
            return cache[index]
        a = item(doc['accessors'], index, 'accessor')
        if 'sparse' in a or 'bufferView' not in a:
            raise ValueError('Sparse or implicit GLB accessors are unsupported')
        view = item(doc['bufferViews'], a['bufferView'], 'buffer view')
        if view.get('buffer', 0) != 0:
            raise ValueError('External GLB buffers are unsupported')
        if a.get('componentType') not in formats or a.get('type') not in widths:
            raise ValueError('Unsupported GLB accessor type')
        fmt, width = formats[a['componentType']], widths[a['type']]
        size = struct.calcsize(fmt)
        stride = view.get('byteStride', size * width)
        offset = a.get('byteOffset', 0)
        start = view.get('byteOffset', 0)
        count = a['count']
        end = offset + (count - 1) * stride + size * width if count else offset
        if count < 0 or offset < 0 or start < 0 or stride < size * width or end > view['byteLength'] or start + view['byteLength'] > len(binary):
            raise ValueError('GLB accessor exceeds its buffer view')
        values = []
        for i in range(count):
            row = struct.unpack_from('<' + str(width) + fmt, binary, start + offset + i * stride)
            if a.get('normalized') and fmt != 'f':
                top = (2 ** (size * 8) - 1) if fmt.isupper() else (2 ** (size * 8 - 1) - 1)
                row = tuple(max(-1.0, value / top) for value in row)
            if not all(math.isfinite(value) for value in row):
                raise ValueError('GLB contains non-finite attributes')
            values.append(row)
        cache[index] = values
        return values

    nodes = doc.get('nodes', [])
    # Exported glTF is right-handed Y-up; game mesh Z is reflected.
    reflect = Matrix.Diagonal((1, 1, -1, 1))
    vertices = {}
    reduced = 0
    for node_index, node in enumerate(nodes):
        if 'mesh' not in node:
            continue
        if 'skin' not in node:
            raise ValueError('Every battle part must be skinned')
        skin = item(doc['skins'], node['skin'], 'skin')
        joint_names = [item(nodes, index, 'joint').get('name', '') for index in skin['joints']]
        # glTF skinning ignores the mesh node transform. Positions are in
        # bind space; applying that node transform double-translates IWTE GLBs.
        transform = reflect
        if abs(transform.to_3x3().determinant()) < 1e-12:
            raise ValueError('A battle part has a singular transform')
        normal_transform = transform.to_3x3().inverted().transposed()
        reverse = transform.to_3x3().determinant() < 0
        name = re.sub(r'\.\d+$', '', node.get('name', ''))
        optional = name.endswith('__opt')
        if optional:
            name = name[:-5]
        if '__' not in name:
            raise ValueError('Battle part needs type__name: ' + name)
        group_type, part_name = name.split('__', 1)
        if not group_type or not part_name:
            raise ValueError('Battle part has an empty type or name')
        group = mesh.MeshGroup(group_type, part_name, array('H'), int(optional))
        for primitive in item(doc['meshes'], node['mesh'], 'mesh')['primitives']:
            if primitive.get('mode', 4) != 4 or primitive.get('targets') or primitive.get('extensions'):
                raise ValueError('Only uncompressed triangle primitives without morphs are supported')
            attrs = primitive['attributes']
            required = ('POSITION', 'NORMAL', 'TEXCOORD_0', 'JOINTS_0', 'WEIGHTS_0')
            if any(key not in attrs for key in required):
                raise ValueError('Battle parts need positions, normals, UVs, joints and weights')
            pos, normals, uvs, joints, weights = [accessor(attrs[key]) for key in required]
            if any(len(values) != len(pos) for values in (normals, uvs, joints, weights)):
                raise ValueError('Battle attribute counts differ')
            if any(len(row) != width for values, width in zip((pos,normals,uvs,joints,weights),(3,3,2,4,4)) for row in values):
                raise ValueError('Battle attribute widths differ')
            if 'WEIGHTS_1' in attrs and any(any(row) for row in accessor(attrs['WEIGHTS_1'])):
                raise ValueError('Additional weight sets are unsupported')
            if 'indices' in primitive:
                spec = item(doc['accessors'], primitive['indices'], 'accessor')
                if spec['type'] != 'SCALAR' or spec['componentType'] not in (5121, 5123, 5125) or spec.get('normalized'):
                    raise ValueError('Triangle indices must be unsigned scalar integers')
            flat = [row[0] for row in accessor(primitive['indices'])] if 'indices' in primitive else list(range(len(pos)))
            if len(flat) % 3 or any(not isinstance(index, int) or not 0 <= index < len(pos) for index in flat):
                raise ValueError('Invalid triangle indices')
            local_ids = {}
            for index in dict.fromkeys(flat):
                influence = {}
                for joint, weight in zip(joints[index], weights[index]):
                    if weight < 0:
                        raise ValueError('Negative skin weight')
                    if weight == 0:
                        continue
                    if not isinstance(joint, int) or not 0 <= joint < len(joint_names) or joint_names[joint] not in slots:
                        raise ValueError('Weighted joint is absent from the game bone slots')
                    slot = slots[joint_names[joint]]
                    influence[slot] = influence.get(slot, 0) + weight
                strongest = sorted(influence.items(), key=lambda pair: (-pair[1], pair[0]))
                if not strongest:
                    raise ValueError('A battle vertex has no positive skin weight')
                reduced += len(strongest) > 2
                strongest = strongest[:2]
                total = sum(weight for _, weight in strongest)
                j0, w0 = strongest[0][0], strongest[0][1] / total
                j1, w1 = (strongest[1][0], strongest[1][1] / total) if len(strongest) > 1 else (j0, 0.0)
                point = transform @ Vector(pos[index])
                normal = normal_transform @ Vector(normals[index])
                if normal.length < 1e-12:
                    raise ValueError('A battle vertex has a zero normal')
                normal.normalize()
                key = (*point, *normal, *uvs[index], j0, j1, w0, w1)
                if key not in vertices:
                    vertex = len(vertices)
                    if vertex >= 65536:
                        raise ValueError('Battle mesh exceeds 65,536 vertices after seam splitting')
                    vertices[key] = vertex
                    out.positions.extend(point);out.normals.extend(normal);out.uvs.extend(uvs[index])
                    out.weights.extend((w0, w1));ids.extend((0, j1, j0, 0))
                local_ids[index] = vertices[key]
            for offset in range(0, len(flat), 3):
                triangle = [local_ids[index] for index in flat[offset:offset+3]]
                if reverse:
                    triangle[1], triangle[2] = triangle[2], triangle[1]
                group.indices.extend(triangle)
        if group.indices:
            out.groups.append(group)
    if not out.groups:
        raise ValueError('GLB has no battle triangles')
    out.bone_ids = bytes(ids)
    if reduced:
        out.notes.append(f'Reduced {reduced} source vertices to two normalized influences')
    return out


def taskBoneOrder(path):
    """Read unit skeleton ordering from the same template used by IWTE."""
    sections = {}
    current = None
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.match(r'^<([^>]+)>\s*(.*)$', line)
        if match:
            current, value = match.groups()
            if current in sections:
                raise ValueError('Duplicate task directive: ' + current)
            sections[current] = [value] if value else []
        elif current:
            sections[current].append(line)
    scalar = lambda name: ' '.join(sections.get(name, [])).strip().strip('"')
    if scalar('task_id') != 'extract_to_mesh' or scalar('mesh_type') != 'unit':
        raise ValueError('Built-in battle export needs an extract_to_mesh unit template; use IWTE for other mesh types')
    if scalar('mesh_double_texture') != 'yes':
        raise ValueError('Built-in battle export currently requires a double-texture unit template')
    if scalar('skeleton_scale') not in ('', '1', '1.0', '1.0000'):
        raise ValueError('Built-in battle export requires skeleton scale 1')
    names = sections.get('cas_skeleton_name_list', [])
    if not names or any(len(name.split()) != 1 for name in names):
        raise ValueError('Task template needs one bone name per skeleton-list line')
    if len(set(names)) != len(names):
        raise ValueError('Task template contains duplicate bone names')
    # The QOL weapon groups follow the body's explicitly ordered slots.
    groups = ['bone_weapon_group%02d' % index for index in range(1, 5)]
    if not any(name in names for name in groups):
        names = names + groups
    elif not all(name in names for name in groups):
        raise ValueError('Task template has an incomplete weapon-group slot list')
    return names


def exportGLBToMesh(glb_path, task_path):
    """Validate and serialize fully before replacing an existing output file."""
    model = meshFromGLB(glb_path, taskBoneOrder(task_path))
    encoded = mesh.write_mesh(model)
    checked = mesh.read_mesh_bytes(encoded, str(glb_path), layout=True)
    if checked.vertices != model.vertices or checked.triangles != model.triangles:
        raise ValueError('Written battle mesh failed its geometry check')
    target = Path(glb_path).with_suffix('.mesh')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target, model
