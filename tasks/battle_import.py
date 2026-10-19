"""Native battle model bridge using the shared readers and GLB encoder."""
import copy
import hashlib
import math
from pathlib import Path
import tempfile
import time

import bpy

from ..m2formats import animpack, casanim, mesh, modeldb, modelexport
from .strat_reader import resolveStratPath
from .unit_exporter import selectedModFolder

_databases = {}


def enabled(context=None):
    return (context or bpy.context).scene.med2_toolkit_reader.backend_battle_import == 'BUILTIN'


def sources(context, model_id):
    value = selectedModFolder(context).strip().strip('"')
    if not value:
        raise ValueError('Select a mod data folder in Paths first')
    root = Path(bpy.path.abspath(value)).resolve()
    vanilla = Path(bpy.path.abspath(context.scene.med2_toolkit_reader.directory_med2)) / 'data'
    path = resolveStratPath(root, 'unit_models/battle_models.modeldb')
    if path is None:
        raise ValueError('No battle_models.modeldb in the selected mod')
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    cached = _databases.get(str(path))
    if cached is None or cached[0] != stamp:
        cached = (stamp, modeldb.parse_file(path))
        _databases[str(path)] = cached
    entries = [e for e in cached[1].entries if e.name.casefold() == model_id.casefold()]
    if len(entries) != 1:
        raise ValueError('Model entry is missing or ambiguous: %s' % model_id)
    entry = entries[0]
    if not entry.lods:
        raise ValueError('No mesh LOD for %s' % model_id)
    mesh_path = resolveStratPath(root, entry.lods[0][0], vanilla)
    if mesh_path is None:
        raise ValueError('Unpacked mesh not found: %s' % entry.lods[0][0])
    return root, vanilla, entry, mesh_path


def restSkeleton(root, entry, secondary=False):
    candidates = [a for a in entry.animations if a.mount_type.casefold() == 'none']
    if len(candidates) != 1:
        raise ValueError('Built-in import currently needs one infantry animation set; use IWTE for mounted models')
    animation = candidates[0]
    name = animation.secondary_skeleton if secondary else animation.primary_skeleton
    weapons = animation.sec_weapons if secondary else animation.pri_weapons
    if not name:
        raise ValueError('This entry has no selected primary/secondary skeleton')
    packs, _ = animpack.packs_for(root)
    def table(skeleton):
        packed = packs.skeleton(skeleton) if packs else None
        bones = packed.bone_table() if packed else casanim.skeleton_bones(root, skeleton)
        if not bones:
            raise ValueError('Skeleton not found: %s' % skeleton)
        return bones
    tracks = []
    for index, (bone, parent, pivot) in enumerate(table(name)):
        if not (-1 <= parent < index):
            raise ValueError('Invalid skeleton hierarchy: %s' % name)
        tracks.append(casanim.Track(bone, parent, tuple(pivot)))
    by_name = {t.name.casefold(): i for i, t in enumerate(tracks)}
    if len(by_name) != len(tracks):
        raise ValueError('Duplicate skeleton bone names')
    for weapon in weapons:
        remap = {}
        for index, (bone, parent, pivot) in enumerate(table(weapon)):
            key = bone.casefold()
            if key in by_name:
                remap[index] = by_name[key]
                continue
            if parent not in remap:
                raise ValueError('Weapon skeleton %s has no matching body anchor: %s' % (weapon, bone))
            remap[index] = len(tracks)
            by_name[key] = len(tracks)
            tracks.append(casanim.Track(bone, remap[parent], tuple(pivot)))
    return casanim.Animation(source=name, tracks=tracks), name


def nativeGLB(model, skeleton):
    """Keep the shared encoder, adapting its viewer axes and merged parts to IWTE.

    Shared export mirrors X; Blender maps glTF (x,y,z) to (x,-z,y).
    A 180-degree Y rotation before export therefore gives game (x,z,y).
    """
    model = copy.deepcopy(model)
    skeleton = copy.deepcopy(skeleton)
    weighted = set()
    for vertex in range(model.vertices):
        for weight, bone in ((model.weights[vertex*2], model.bone_ids[vertex*4+2]),
                             (model.weights[vertex*2+1], model.bone_ids[vertex*4+1])):
            if weight > 0:
                if bone >= len(model.bones):
                    raise ValueError('Mesh weight references an invalid bone')
                weighted.add(model.bones[bone].casefold())
    missing = weighted - {track.name.casefold() for track in skeleton.tracks}
    if missing:
        raise ValueError('Weighted bones absent from the selected skeleton: %s' % ', '.join(sorted(missing)))
    for values in (model.positions, model.normals):
        for i in range(0, len(values), 3):
            values[i], values[i+2] = -values[i], -values[i+2]
    # Preserve quantized near-zero normals instead of the viewer encoder's
    # fallback-up heuristic; IWTE normalizes these decoded vectors too.
    for i in range(0, len(model.normals), 3):
        length = math.sqrt(sum(v*v for v in model.normals[i:i+3]))
        if length:
            for axis in range(3):
                model.normals[i+axis] /= length
    for track in skeleton.tracks:
        x, y, z = track.pivot
        track.pivot = (-x, y, -z)
    document, binary = modelexport.read_glb(modelexport.export_glb(model, skeleton=skeleton, uscale=1.0))
    merged = document['meshes'][0]
    mesh_node = document['nodes'].pop()
    document['scenes'][0]['nodes'].remove(len(document['nodes']))
    document['meshes'] = []
    document['materials'] = [{'name': 'characterlod0__' + role,
                              'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': .5}}
                             for role in ('main', 'attach')]
    for group, primitive in zip((g for g in model.groups if g.indices), merged['primitives']):
        if group.sheets == 'both':
            raise ValueError('A mesh part crosses main and attachment sheets: %s; use IWTE' % group.name)
        name = '%s__%s%s' % (group.name, group.texture_group, '__opt' if group.optional else '')
        primitive['material'] = 1 if group.sheets == 'attach' else 0
        document['meshes'].append({'name': name, 'primitives': [primitive]})
        node = dict(mesh_node, name=name, mesh=len(document['meshes'])-1)
        document['nodes'].append(node)
        document['scenes'][0]['nodes'].append(len(document['nodes'])-1)
    return modelexport._glb(document, binary)


def textureFiles(root, vanilla, entry, faction, folder):
    result = {}
    for role, textures in (('main', entry.main_textures), ('attach', entry.attach_textures)):
        if not textures:
            continue
        selected = next((t for t in textures if t.faction.casefold() == faction.casefold()), None)
        selected = selected or next((t for t in textures if t.faction.casefold() == 'all'), textures[0])
        files = []
        for relative in (selected.texture, selected.normal):
            path = resolveStratPath(root, relative, vanilla)
            if path is None:
                raise ValueError('Unpacked texture not found: %s' % relative)
            content = path.read_bytes()
            # Game .texture wraps the DDS in 48 bytes; some mods store bare DDS.
            if not content.startswith(b'DDS '):
                content = content[48:]
            if len(content) < 128 or not content.startswith(b'DDS '):
                raise ValueError('Texture contains no DDS image: %s' % path)
            digest = hashlib.sha256(content).hexdigest()
            target = folder / digest / (path.stem + '.dds')
            target.parent.mkdir(exist_ok=True)
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)
            files.append((str(path), target.relative_to(folder).as_posix()))
        result[role] = files
    return result


def importModel(context, model_id, unit_name, faction, output_folder):
    from .importer import materialWorkflow, selectionBoundingBox, hideVariations
    started = time.perf_counter()
    root, vanilla, entry, path = sources(context, model_id)
    skeleton, skeleton_name = restSkeleton(root, entry, context.scene.med2_toolkit_units.primary_secondary == 'secondary')
    model = mesh.read_mesh(path)
    if not model.weights or not model.bones:
        raise ValueError('Built-in infantry import needs a skinned mesh; use IWTE for this model')
    blob = nativeGLB(model, skeleton)
    # Content-addressed texture files keep old imported materials stable and
    # avoid basename collisions across mods. Mesh GLBs are always rebuilt.
    folder = Path(bpy.path.abspath(output_folder)) / '.med2-native' / 'textures'
    folder.mkdir(parents=True, exist_ok=True)
    textures = textureFiles(root, vanilla, entry, faction, folder)
    existing = {kind: set(getattr(bpy.data, kind)) for kind in ('objects', 'meshes', 'armatures', 'materials', 'images')}
    selected, active = list(context.selected_objects), context.view_layer.objects.active
    try:
        with tempfile.TemporaryDirectory(prefix='med2_battle_') as temporary:
            glb = Path(temporary) / 'model.glb'
            glb.write_bytes(blob)
            bpy.ops.import_scene.gltf(filepath=str(glb), disable_bone_shape=True)
        rigs = [o for o in bpy.data.objects if o not in existing['objects'] and o.type == 'ARMATURE']
        if len(rigs) != 1:
            raise ValueError('Native conversion did not produce one armature')
        rig = rigs[0]
        rig.name = unit_name
        rig.data.name = unit_name
        rig.data.display_type = 'STICK'
        rig['med2_battle_skeleton'] = skeleton_name
        rig['med2_battle_source'] = str(path)
        rig['med2_battle_import_backend'] = 'BUILTIN'
        for material in set(bpy.data.materials) - existing['materials']:
            role = 'attach' if '__attach' in material.name else 'main'
            if role not in textures:
                raise ValueError('Mesh uses %s material but the entry has no textures for it' % role)
            diffuse, normal = textures[role]
            material.name = Path(diffuse[0]).stem
            materialWorkflow(str(folder) + '/', diffuse[1], normal[1], material)
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        context.view_layer.objects.active = rig
        width, z_offset = selectionBoundingBox()
        if context.scene.med2_toolkit_units.hide_toggle:
            hideVariations()
        print('Built-in battle import %s: %.3fs' % (model_id, time.perf_counter()-started))
        return 2, width, z_offset
    except Exception:
        for kind in existing:
            collection = getattr(bpy.data, kind)
            for item in set(collection) - existing[kind]:
                collection.remove(item, do_unlink=True)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        raise
