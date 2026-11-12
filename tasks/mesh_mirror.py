"""Reflect meshes in local space and remap M2 skeleton weights."""
import re

import bmesh
import bpy
from mathutils import Matrix

MODIFIER = 'M2 Cut Mirror'
EPSILON = 1e-6
# Imported M2 centre columns sit ~0.0005 off X=0 (position quantisation); snap
# them to the seam rather than cutting a hair-thin strip beside them.
SEAM = 1e-3
M2_SIDE_NAME = re.compile(
    r'^(bone_)([LRlr])(clavical|upperarm|elbow|hand|thigh|lowerleg|foot)$', re.IGNORECASE)


def oppositeName(name):
    # M2 side markers precede the limb, rather than ending the bone name.
    match = M2_SIDE_NAME.fullmatch(name)
    if match:
        side = {'L': 'R', 'R': 'L', 'l': 'r', 'r': 'l'}[match[2]]
        return match[1] + side + match[3]
    return bpy.utils.flip_name(name)


def validateMesh(obj, allow_shape_keys=False):
    if obj.library or obj.data.library or obj.override_library:
        raise ValueError('Make the mesh local before mirroring')
    if obj.data.shape_keys and not allow_shape_keys:
        raise ValueError('Shape keys are present; remove them on a working copy first')
    if not obj.data.vertices:
        raise ValueError('Mesh is empty')


def weightPairs(obj):
    rig = obj.find_armature()
    bones = rig.data.bones if rig else None
    pairs = {}
    for group in obj.vertex_groups:
        if bones is not None and group.name not in bones:
            continue  # Utility groups on rigged meshes are not bone weights.
        other = oppositeName(group.name)
        if other == group.name:
            continue
        if bones is not None and other not in bones:
            raise ValueError(f'Missing counterpart bone: {group.name} -> {other}')
        pairs[group.name] = other
    return pairs


def weightGroupMapping(obj, pairs):
    for name in pairs.values():
        if name not in obj.vertex_groups:
            obj.vertex_groups.new(name=name)
    return {obj.vertex_groups[a].index: obj.vertex_groups[b].index for a, b in pairs.items()}


def remapVertexWeights(groups, vertex, mapping):
    # Snapshot before writing so blended L/R weights cannot overwrite each other.
    weights = [(entry.group, entry.weight) for entry in vertex.groups if entry.group in mapping]
    for source, _ in weights:
        groups[source].remove([vertex.index])
    for source, weight in weights:
        groups[mapping[source]].add([vertex.index], weight, 'REPLACE')


def flipMirror(obj):
    validateMesh(obj, allow_shape_keys=True)
    pairs = weightPairs(obj)
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    mesh = obj.data
    custom_normals = {}
    if mesh.has_custom_normals:
        # flip_normals() reverses corner order without transforming custom normals.
        normals = mesh.corner_normals
        custom_normals = {(face.index, mesh.loops[i].vertex_index): normals[i].vector.copy()
                          for face in mesh.polygons for i in face.loop_indices}
    reflection = Matrix.Diagonal((-1.0, 1.0, 1.0, 1.0))
    mesh.transform(reflection, shape_keys=True)
    mesh.flip_normals()
    if custom_normals:
        normal_transform = reflection.to_3x3()
        mesh.normals_split_custom_set([
            normal_transform @ custom_normals[face.index, mesh.loops[i].vertex_index]
            for face in mesh.polygons for i in face.loop_indices
        ])
    mesh.update()
    mapping = weightGroupMapping(obj, pairs)
    if mapping:
        for vertex in mesh.vertices:
            remapVertexWeights(obj.vertex_groups, vertex, mapping)
    return [f'{obj.name}: local X -> -X on {len(mesh.vertices)} vertices'] + [
        f'{obj.name}: flipped weights {a} -> {b}' for a, b in sorted(pairs.items())]


def sourceSide(obj, axis=0):
    # The kept half is whichever side of the mirror plane still has geometry.
    positive = any(v.co[axis] > EPSILON for v in obj.data.vertices)
    negative = any(v.co[axis] < -EPSILON for v in obj.data.vertices)
    if positive and negative:
        raise ValueError(f'Source vertices cross local {"XYZ"[axis]}=0; move them back before applying')
    if not (positive or negative):
        raise ValueError(f'No source geometry off local {"XYZ"[axis]}=0')
    return 1 if positive else -1


def cutMirror(obj, keep_positive=False, axes=(True, False, False), keep_sides=None):
    validateMesh(obj)
    if any(mod.type == 'MIRROR' for mod in obj.modifiers):
        raise ValueError('A Mirror modifier already exists; apply or remove it first')
    axes = tuple(axes)
    if len(axes) != 3 or not any(axes):
        raise ValueError('Select at least one mirror axis')
    keep_sides = tuple(keep_sides) if keep_sides is not None else (keep_positive,) * 3
    active = [axis for axis in range(3) if axes[axis]]
    label = '/'.join('XYZ'[axis] for axis in active)
    sides = '/'.join(('+' if keep_sides[axis] else '-') + 'XYZ'[axis] for axis in active)
    for axis in active:
        sign = 1 if keep_sides[axis] else -1
        if not any(sign * v.co[axis] > SEAM for v in obj.data.vertices):
            raise ValueError(f'No geometry on the {sides} side of local {"XYZ"[axis]}=0')
    before = len(obj.data.vertices)
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        for axis in active:
            sign = 1 if keep_sides[axis] else -1
            normal = tuple(1 if i == axis else 0 for i in range(3))
            bmesh.ops.bisect_plane(
                bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
                dist=SEAM, plane_co=(0, 0, 0), plane_no=normal,
                clear_outer=not keep_sides[axis], clear_inner=keep_sides[axis])
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if -sign * v.co[axis] > SEAM], context='VERTS')
            for vertex in bm.verts:
                if abs(vertex.co[axis]) <= SEAM:
                    vertex.co[axis] = 0
        # All cuts happen in memory first; an empty octant leaves the mesh alone.
        if not bm.verts or any(not any(abs(v.co[axis]) > EPSILON for v in bm.verts)
                               for axis in active):
            raise ValueError(f'No source geometry remains off the mirror planes on kept {sides} sides')
        # A linked duplicate must not lose its other half as a side effect.
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    mod = obj.modifiers.new(MODIFIER, 'MIRROR')
    mod.use_axis = axes
    mod.use_clip = True
    mod.use_mirror_merge = True
    mod.merge_threshold = EPSILON
    mod.use_mirror_vertex_groups = False
    # Mirror the rest mesh before an Armature or other deformation.
    obj.modifiers.move(len(obj.modifiers) - 1, 0)
    return [f'{obj.name}: {before} -> {len(obj.data.vertices)} source vertices; bisected on local {label}',
            f'{obj.name}: no mirror -> {label} Mirror with clipping (keep {sides})']


def applyMirror(context, obj, mirror_weights=True, ignore_primary_secondary=False):
    validateMesh(obj)
    mod = obj.modifiers.get(MODIFIER)
    if not mod or mod.type != 'MIRROR':
        raise ValueError('Use Cut + Mirror first')
    if (obj.modifiers[0] != mod or not any(mod.use_axis)
            or mod.mirror_object or any(mod.use_bisect_axis)
            or mod.use_mirror_vertex_groups):
        raise ValueError('Mirror settings/order changed; restore the original Cut + Mirror settings')
    active = [axis for axis in range(3) if mod.use_axis[axis]]
    signs = {axis: sourceSide(obj, axis) for axis in active}
    label = '/'.join('XYZ'[axis] for axis in active)
    skip_item = ignore_primary_secondary and obj.name.lower().startswith(('primary', 'secondary'))
    remap = mirror_weights and not skip_item
    pairs = weightPairs(obj) if remap else {}
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    with context.temp_override(object=obj, active_object=obj):
        result = bpy.ops.object.modifier_apply(modifier=mod.name)
    if result != {'FINISHED'}:
        raise ValueError('Blender could not apply the Mirror modifier')
    # Applying an already evaluated modifier can restore its old group list.
    # Create missing counterparts and resolve indices only on the applied mesh.
    mapping = weightGroupMapping(obj, pairs)
    # Native group mirroring is disabled; handle reflected copies below.
    for vertex in obj.data.vertices if mapping else ():
        # Each reflection swaps sides once; two reflections cancel the swap.
        reflections = sum(-signs[axis] * vertex.co[axis] > EPSILON for axis in active)
        if reflections % 2:
            remapVertexWeights(obj.vertex_groups, vertex, mapping)
    return [f'{obj.name}: {label} Mirror -> applied mesh; center seam retained'] + ([
        f'{obj.name}: weight mirroring -> skipped (primary/secondary item)' if skip_item else
        f'{obj.name}: weight mirroring -> disabled; copied source weights retained'] if not remap else []) + [
        f'{obj.name}: mirrored {a} -> {b}' for a, b in sorted(pairs.items())]
