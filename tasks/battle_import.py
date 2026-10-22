"""Native battle model bridge using the shared readers and GLB encoder."""
import copy
import hashlib
import math
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

import bpy

from ..m2formats import animpack, casanim, engines, mesh, modeldb, modelexport
from .strat_reader import resolveStratPath
from .unit_exporter import selectedModFolder

_databases = {}


def enabled(context=None):
    return (context or bpy.context).scene.med2_toolkit_reader.backend_battle_import == 'BUILTIN'


def sources(context, model_id, faction=''):
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
    # A mod may repeat an entry per faction group (HoE's elephant_crew3: one for
    # england/hre, one for slave/merc). Same mesh and skeleton, so take the one
    # listing this faction.
    if len(entries) > 1 and len({(tuple(e.lods[:1]), tuple((a.primary_skeleton, a.secondary_skeleton) for a in e.animations)) for e in entries}) == 1:
        owned = [e for e in entries if any(t.faction.casefold() == faction.casefold() for t in e.main_textures)]
        entries = owned[:1] or entries[:1]
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
    candidates = candidates or list(entry.animations)
    if len(candidates) != 1:
        raise ValueError('Built-in import needs one unambiguous animation set; use IWTE for this model')
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
    # Unit mesh influences address skeleton slots, not the advisory mesh bone
    # labels. Humanoid skeletons reserve four weapon slots after 20 body bones.
    humanoid = len(tracks) == 20 and 'bone_rhand' in by_name and 'bone_lhand' in by_name
    if humanoid:
        tracks.extend([
            casanim.Track('bone_weapon_group01', by_name['bone_rhand'], (0, 0, 0)),
            casanim.Track('bone_weapon_group02', 20, (0, 0, 0)),
            casanim.Track('bone_weapon_group03', by_name['bone_lhand'], (0, 0, 0)),
            casanim.Track('bone_weapon_group04', 20, (0, 0, 0)),
        ])
    if len(weapons) > 2:
        raise ValueError('More than two weapon skeletons; use IWTE')
    for weapon_index, weapon in enumerate(weapons):
        remap = {}
        slot = 20 + weapon_index * 2
        for index, (bone, parent, pivot) in enumerate(table(weapon)):
            key = bone.casefold()
            if key in by_name:
                remap[index] = by_name[key]
                continue
            if parent not in remap:
                raise ValueError('Weapon skeleton %s has no matching body anchor: %s' % (weapon, bone))
            if humanoid:
                if slot >= 22 + weapon_index * 2:
                    raise ValueError('Weapon skeleton exceeds its two slots; use IWTE: %s' % weapon)
                remap[index] = slot
                tracks[slot] = casanim.Track(bone, remap[parent], tuple(pivot))
                slot += 1
            else:
                remap[index] = len(tracks)
                tracks.append(casanim.Track(bone, remap[parent], tuple(pivot)))
            by_name[key] = remap[index]
    return casanim.Animation(source=name, tracks=tracks), name


def nativeGLB(model, skeleton, single_sheet=False, indexed_bones=False):
    """Keep the shared encoder, adapting its viewer axes and merged parts to IWTE.

    Shared export mirrors X; Blender maps glTF (x,y,z) to (x,-z,y).
    A 180-degree Y rotation before export therefore gives game (x,z,y).
    """
    model = copy.deepcopy(model)
    skeleton = copy.deepcopy(skeleton)
    for track in skeleton.tracks:
        track.name = track.name.replace(' ', '__')
    if indexed_bones:
        model.bones = [track.name for track in skeleton.tracks]
    # Bone 255 marks "no bone"; some shipped meshes weight parts to it fully
    # (HoE family_member_lod0's helmet backface). IWTE binds those to bone 0.
    ids = bytearray(model.bone_ids)
    for slot in range(1, len(ids), 4):
        for offset in (0, 1):
            if ids[slot + offset] == 255 and model.weights[(slot // 4) * 2 + (1 - offset)] > 0:
                ids[slot + offset] = 0
    model.bone_ids = bytes(ids)
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
    document, binary = modelexport.read_glb(modelexport.export_glb(model, skeleton=skeleton, uscale=0.5 if single_sheet else 1.0))
    merged = document['meshes'][0]
    mesh_node = document['nodes'].pop()
    document['scenes'][0]['nodes'].remove(len(document['nodes']))
    document['meshes'] = []
    document['materials'] = [{'name': 'characterlod0__' + role,
                              'pbrMetallicRoughness': {'metallicFactor': 0, 'roughnessFactor': .5}}
                             for role in ('main', 'attach')]
    used_names = set()
    for group, primitive in zip((g for g in model.groups if g.indices), merged['primitives']):
        base = '%s__%s' % (group.name, group.texture_group.replace(' ', '__'))
        suffix = '__opt' if group.optional else ''
        name = base + suffix
        duplicate = 0
        while name in used_names:
            name = base + str(duplicate) + suffix
            duplicate += 1
        used_names.add(name)
        # IWTE assigns one sheet per part: any referenced U beyond the first
        # tile selects attach, including parts crossing a tile edge. Keep the
        # original UVs and object boundaries for the existing export workflow.
        attach = not single_sheet and any(model.uvs[v * 2] > 1.0 for v in group.indices)
        primitive['material'] = 1 if attach else 0
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
    started = time.perf_counter()
    root, vanilla, entry, path = sources(context, model_id, faction)
    skeleton, skeleton_name = restSkeleton(root, entry, context.scene.med2_toolkit_units.primary_secondary == 'secondary')
    model = mesh.read_mesh(path)
    if not model.weights or not model.bones:
        raise ValueError('Built-in infantry import needs a skinned mesh; use IWTE for this model')
    blob = nativeGLB(model, skeleton, single_sheet=not entry.attach_textures, indexed_bones=True)
    # Content-addressed texture files keep old imported materials stable and
    # avoid basename collisions across mods. Mesh GLBs are always rebuilt.
    folder = Path(bpy.path.abspath(output_folder)) / '.med2-native' / 'textures'
    folder.mkdir(parents=True, exist_ok=True)
    textures = textureFiles(root, vanilla, entry, faction, folder)
    return importPrepared(context, unit_name, path, skeleton_name, blob, textures, folder, started)


def importPrepared(context, unit_name, path, skeleton_name, blob, textures, folder, started):
    from .importer import materialWorkflow, selectionBoundingBox, hideVariations
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
        print('Built-in battle import %s: %.3fs' % (unit_name, time.perf_counter()-started))
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


def importEngine(context, engine_id, unit_name, output_folder):
    started = time.perf_counter()
    value = selectedModFolder(context).strip().strip('"')
    if not value:
        raise ValueError('Select a mod data folder in Paths first')
    root = Path(bpy.path.abspath(value)).resolve()
    vanilla = Path(bpy.path.abspath(context.scene.med2_toolkit_reader.directory_med2)) / 'data'
    descriptor = resolveStratPath(root, 'descr_engines.txt', vanilla)
    if descriptor is None:
        raise ValueError('No unpacked descr_engines.txt')
    entries = engines.parse_file(descriptor).get_all(engine_id)
    if len(entries) != 1:
        raise ValueError('Engine is missing or has culture/variant alternatives; use IWTE: %s' % engine_id)
    groups = [g for g in entries[0].groups if g.name.casefold() == 'normal']
    if len(groups) != 1 or not groups[0].meshes:
        raise ValueError('Engine has no unambiguous normal model: %s' % engine_id)
    group = groups[0]
    path = resolveStratPath(root, group.meshes[0], vanilla)
    descriptor = resolveStratPath(root, 'descr_engine_skeleton.txt', vanilla)
    if path is None or descriptor is None:
        raise ValueError('Engine mesh or skeleton descriptor is not unpacked: %s' % engine_id)
    skeleton_entry = engines.parse_skeleton_file(descriptor).get(group.skeleton)
    defaults = [p for key, p in skeleton_entry.anims if key == 'default'] if skeleton_entry else []
    animation = resolveStratPath(root, defaults[0], vanilla) if len(defaults) == 1 else None
    if animation is None:
        raise ValueError('Engine default skeleton CAS is missing or ambiguous: %s' % group.skeleton)
    skeleton = casanim.read_anim(animation)
    # IWTE excludes the CAS container root from its exported armature.
    if skeleton.tracks and skeleton.tracks[0].name.casefold() in ('scene root', 'sceneroot'):
        container = skeleton.tracks[0]
        if any(abs(v) > 1e-6 for v in container.pivot):
            raise ValueError('Engine scene root has a nonzero pivot; use IWTE')
        skeleton.tracks = skeleton.tracks[1:]
        for track in skeleton.tracks:
            track.parent -= 1
    model = mesh.read_mesh(path)
    if not model.weights or not model.bones:
        raise ValueError('Engine mesh has no skin; use IWTE')
    paths = engines.mesh_textures(path)
    if len(paths) not in (2, 3) or (len(paths) == 3 and 'overlay' not in paths[2].casefold()):
        raise ValueError('Engine texture layout is unsupported; use IWTE: %s' % engine_id)
    entry = SimpleNamespace(main_textures=[SimpleNamespace(faction='all', texture=paths[0], normal=paths[1])], attach_textures=[])
    folder = Path(bpy.path.abspath(output_folder)) / '.med2-native' / 'textures'
    folder.mkdir(parents=True, exist_ok=True)
    textures = textureFiles(root, vanilla, entry, 'all', folder)
    blob = nativeGLB(model, skeleton, single_sheet=True)
    return importPrepared(context, unit_name, path, group.skeleton, blob, textures, folder, started)
