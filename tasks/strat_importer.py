"""Import a campaign CAS at its native bind scale, with reversible provenance."""
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

from ..m2formats import cas
from .strat_data import STRAT_BONES


def casToBlender(value):
    """Match IWTE's CAS-to-Blender axis reflection (Y up to Z up)."""
    x, y, z = value
    return (x, z, y)


def _textureName(path):
    name = Path(path).name
    if name.lower().endswith('.dds'):
        name = name[:-4]
    if name.lower().endswith('.tga'):
        name = name[:-4]
    return name


def _nodeKey(name):
    """IWTE uses underscores where CAS node labels can contain spaces."""
    return ''.join(name.casefold().replace('_', ' ').split())


def _assignTexture(armature, texture_path):
    """Apply a faction texture using independent materials on imported meshes."""
    if texture_path is None:
        return []
    path = Path(texture_path) if texture_path else None
    if path is not None and (not path.is_file() or not path.stat().st_size):
        return [('WARNING', 'Texture not found: %s' % path)]
    image = bpy.data.images.load(str(path), check_existing=True) if path else None
    materials = {}
    for obj in armature.children_recursive:
        if obj.type != 'MESH':
            continue
        # Imported GLBs can reuse an existing mesh/material datablock.
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        if not obj.data.materials:
            obj.data.materials.append(None)
        for slot in obj.material_slots:
            original = slot.material
            if original not in materials:
                material = original.copy() if original else bpy.data.materials.new(_textureName(path) if path else 'Missing faction texture')
                material.use_nodes = True
                shader = next((node for node in material.node_tree.nodes
                               if node.type == 'BSDF_PRINCIPLED'), None)
                if shader is None:
                    shader = material.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
                    output = next((node for node in material.node_tree.nodes
                                   if node.type == 'OUTPUT_MATERIAL'), None)
                    if output is None:
                        output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
                    material.node_tree.links.new(shader.outputs['BSDF'], output.inputs['Surface'])
                if image is None:
                    # An explicitly unavailable faction must not inherit the
                    # embedded GLB texture. Copies leave shared originals intact.
                    for input_name in ('Base Color', 'Alpha'):
                        for link in list(shader.inputs[input_name].links):
                            material.node_tree.links.remove(link)
                    shader.inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1.0)
                    shader.inputs['Alpha'].default_value = 1.0
                else:
                    node = material.node_tree.nodes.new('ShaderNodeTexImage')
                    node.image = image
                    material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
                    material.node_tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
                materials[original] = material
            slot.material = materials[original]
    return []


def finalizeStratImport(context, armature, metadata=None, cas_path='',
                        texture_path=None, backend='builtin'):
    """Shared post-import state for native and IWTE imports; never writes files.

    Campaign descriptor scale is deliberately metadata, not an object transform.
    Exporting the model must not bake the campaign display multiplier into CAS.
    """
    from .strat_model import STRAT_TAG, stratOutputFolder
    metadata = dict(metadata or {})
    report = _assignTexture(armature, texture_path) if backend != 'builtin' else []
    name = Path(cas_path).stem or armature.name
    armature[STRAT_TAG] = name
    armature['med2_strat_import_metadata'] = json.dumps(metadata, ensure_ascii=False)
    armature['med2_strat_source_cas'] = str(cas_path)
    armature['med2_strat_source_texture'] = str(texture_path or '')
    armature['med2_strat_import_backend'] = backend
    armature['med2_strat_bone_order'] = json.dumps([b.name for b in armature.data.bones])
    settings = getattr(context.scene, 'med2_toolkit_strat', None)
    if settings is not None:
        settings.model_name = name
        settings.texture_name = _textureName(texture_path) if texture_path else name
        settings.skeleton_scale = 1.0
        settings.last_build_dir = stratOutputFolder(context, name)
        settings.last_texture = ''
        settings.last_exported_glb = ''
        settings.last_cas = ''
    for obj in context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    return report


def _validate(scene):
    if not scene.objects or not scene.vertices:
        raise cas.CasError('The CAS contains no readable mesh geometry')
    if scene.notes:
        # Partial mesh chunks are not a successful editable model. IWTE can
        # handle unsupported variants without silently losing geometry.
        raise cas.CasError('; '.join(scene.notes))
    count = len(scene.nodes)
    if len(scene.parents) != count or len(scene.pivots) != 3 * count:
        raise cas.CasError('Incomplete CAS skeleton hierarchy')
    if any(parent < -1 or parent >= count for parent in scene.parents):
        raise cas.CasError('Invalid CAS skeleton parent index')
    for i, parent in enumerate(scene.parents):
        if parent < -1 or parent >= count or parent == i:
            raise cas.CasError('Invalid CAS skeleton parent index')
        chain = set()
        while parent >= 0:
            if parent in chain:
                raise cas.CasError('Cyclic CAS skeleton hierarchy')
            chain.add(parent)
            parent = scene.parents[parent]
    for obj in scene.objects:
        if any(i >= obj.vertices for i in obj.indices):
            raise cas.CasError('CAS mesh contains an invalid triangle index')
        if obj.skinned and (len(obj.bones) != obj.vertices or any(b >= count for b in obj.bones)):
            raise cas.CasError('CAS mesh contains invalid bone weights')
        if not all(math.isfinite(v) for v in (*obj.positions, *obj.normals, *obj.uvs)):
            raise cas.CasError('CAS mesh contains non-finite coordinates')
    if not all(math.isfinite(v) for v in scene.pivots):
        raise cas.CasError('CAS skeleton contains non-finite pivots')
    if cas.is_skinned(scene) and not cas.has_pivots(scene):
        raise cas.CasError('Skinned CAS has no bind pivots; a separate skeleton is required')


def importStratCAS(context, cas_path, *, metadata=None, texture_path=None):
    """Return (report, rig); CAS decoding errors propagate before any mutation.

    Blender construction failures roll back all new datablocks and selection.
    Canonical names are matched case-insensitively; pivots and hierarchy always
    come from the selected CAS, including custom/static models.
    """
    scene = cas.read_cas(cas_path)
    _validate(scene)
    if context.mode != 'OBJECT':
        return [('ERROR', 'Switch to Object Mode before importing a strat model')], None
    metadata = dict(metadata or {})
    json.dumps(metadata)  # Reject invalid metadata before scene mutation.
    world = cas.bind_world(scene)
    blocks = ('objects', 'meshes', 'armatures', 'materials', 'images', 'collections')
    before = {name: set(getattr(bpy.data, name)) for name in blocks}
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    settings = getattr(context.scene, 'med2_toolkit_strat', None)
    previous_settings = {name: getattr(settings, name) for name in
                         ('model_name', 'texture_name', 'skeleton_scale', 'last_build_dir',
                          'last_texture', 'last_exported_glb', 'last_cas')} if settings else {}
    report = []
    try:
        collection = bpy.data.collections.new(Path(cas_path).stem)
        context.scene.collection.children.link(collection)
        data = bpy.data.armatures.new(Path(cas_path).stem)
        rig = bpy.data.objects.new(Path(cas_path).stem, data)
        collection.objects.link(rig)
        for obj in selected:
            obj.select_set(False)
        rig.select_set(True)
        context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        canonical = {_nodeKey(name): name for name, _, _, _ in STRAT_BONES}
        # Scene Root is a container, except when vertices explicitly use it.
        used = {int(b) for obj in scene.objects for b in obj.bones}
        keep = [i for i, name in enumerate(scene.nodes)
                if _nodeKey(name) != 'sceneroot' or i in used]
        bones = {}
        for i in keep:
            name = canonical.get(_nodeKey(scene.nodes[i]), scene.nodes[i])
            bone = data.edit_bones.new(name)
            bone.head = casToBlender(world[i])
            bone.tail = bone.head + Vector((0, 0, 0.09524196))
            bone.align_roll(Vector((0, -1, 0)))
            bone['med2_cas_node_index'] = i
            bone['med2_cas_node_name'] = scene.nodes[i]
            bones[i] = bone
        for i, bone in bones.items():
            if scene.parents[i] in bones:
                bone.parent = bones[scene.parents[i]]
        bone_names = {i: bone.name for i, bone in bones.items()}
        bpy.ops.object.mode_set(mode='OBJECT')
        loaded_materials = {}
        resolved_texture = str(texture_path or '')
        for source in scene.objects:
            positions = cas.posed_positions(source, world)
            vertices = [casToBlender(positions[i:i + 3]) for i in range(0, len(positions), 3)]
            # Swapping Y/Z reflects handedness, so reverse triangle winding.
            faces = [tuple(reversed(source.indices[i:i + 3])) for i in range(0, len(source.indices), 3)]
            mesh = bpy.data.meshes.new(source.name)
            mesh.from_pydata(vertices, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(source.name, mesh)
            collection.objects.link(obj)
            obj.parent = rig
            if source.uvs:
                uv = mesh.uv_layers.new(name='UVMap')
                for loop in mesh.loops:
                    i = 2 * loop.vertex_index
                    uv.data[loop.index].uv = (source.uvs[i], 1.0 - source.uvs[i + 1])
            if source.normals:
                normals = [casToBlender(source.normals[i:i + 3]) for i in range(0, len(source.normals), 3)]
                mesh.normals_split_custom_set_from_vertices(normals)
                for polygon in mesh.polygons:
                    polygon.use_smooth = True
            if source.skinned:
                modifier = obj.modifiers.new('Armature', 'ARMATURE')
                modifier.object = rig
                groups = {}
                for index, bone in enumerate(source.bones):
                    groups.setdefault(int(bone), []).append(index)
                for bone, indices in groups.items():
                    obj.vertex_groups.new(name=bone_names[bone]).add(indices, 1.0, 'REPLACE')
            if source.material is not None or texture_path:
                if source.material not in loaded_materials:
                    original = scene.materials[source.material] if source.material is not None else cas.CasMaterial()
                    path = (Path(texture_path) if texture_path else None) if texture_path is not None else cas.texture_path(Path(cas_path), original.texture)
                    name = _textureName(str(path)) if path else original.name or source.name
                    material = bpy.data.materials.new(name)
                    material.use_nodes = True
                    shader = material.node_tree.nodes.get('Principled BSDF')
                    shader.inputs['Base Color'].default_value = original.diffuse
                    shader.inputs['Roughness'].default_value = 1.0
                    if path and path.is_file() and path.stat().st_size:
                        image = bpy.data.images.load(str(path), check_existing=True)
                        node = material.node_tree.nodes.new('ShaderNodeTexImage')
                        node.image = image
                        material.node_tree.links.new(node.outputs['Color'], shader.inputs['Base Color'])
                        material.node_tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
                        resolved_texture = resolved_texture or str(path)
                    elif texture_path != '':
                        report.append(('WARNING', 'Texture not found: %s' % (path or original.texture)))
                    loaded_materials[source.material] = material
                mesh.materials.append(loaded_materials[source.material])
        metadata['cas_version'] = scene.version
        metadata['cas_nodes'] = list(scene.nodes)
        metadata['cas_parents'] = list(scene.parents)
        metadata['cas_pivots'] = list(scene.pivots)
        report.extend(finalizeStratImport(context, rig, metadata, str(cas_path), resolved_texture))
        report.append(('INFO', 'Imported %s: %d meshes, %d triangles, %d bones' %
                       (Path(cas_path).name, len(scene.objects), scene.triangles, len(data.bones))))
        if metadata.get('scale'):
            report.append(('INFO', 'Campaign scale %s saved as metadata; editable model remains at native scale' % metadata['scale']))
        return report, rig
    except Exception as error:
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for name in blocks:
            collection = getattr(bpy.data, name)
            for block in set(collection) - before[name]:
                collection.remove(block, do_unlink=True)
        for obj in selected:
            obj.select_set(True)
        context.view_layer.objects.active = active
        for name, value in previous_settings.items():
            setattr(settings, name, value)
        return [('ERROR', 'Strat import failed: %s' % error)], None
