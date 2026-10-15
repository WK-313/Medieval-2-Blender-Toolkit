"""Adapt a Blender rest mesh to the shared campaign CAS writer."""
from array import array
import json

import bpy
from mathutils import Vector

from ..m2formats import cas


def _axis(value):
    return (value[0], value[2], value[1])


def stratCasScene(context, rig, texture):
    """Snapshot without changing selection, pose, mesh datablocks or weights.

    CAS stores translation-only bind pivots and one bone per vertex. Refuse
    ambiguous skinning rather than silently changing the user's weights.
    """
    bones = list(rig.data.bones)
    stored = rig.get('med2_strat_bone_order')
    if stored:
        order = json.loads(stored)
        if not isinstance(order, list) or set(order) != {b.name for b in bones} or len(order) != len(bones):
            raise ValueError('Stored strat bone order does not match the rig')
        bones = [rig.data.bones[name] for name in order]
    if not bones:
        raise ValueError('The strat rig has no bones')
    # Scene Root is a file container; native imports normally omit it.
    root_bones = [b for b in bones if b.name.replace('_', '').replace(' ', '').lower() == 'sceneroot']
    if root_bones and (bones[0] != root_bones[0] or root_bones[0].parent):
        raise ValueError('Scene Root must be the first root bone')
    offset = 0 if root_bones else 1
    indices = {b.name: i + offset for i, b in enumerate(bones)}
    scene = cas.CasScene(source='', version=3.2, key_times=array('f', [0]))
    world = [Vector((0, 0, 0))] if offset else []
    scene.nodes = ['Scene Root'] if offset else []
    scene.parents = [-1] if offset else []
    for bone in bones:
        scene.nodes.append(bone.get('med2_cas_node_name', bone.name))
        scene.parents.append(indices[bone.parent.name] if bone.parent else (0 if offset else -1))
        world.append(Vector(_axis(rig.matrix_world @ bone.head_local)))
    for i, parent in enumerate(scene.parents):
        if i and parent < 0:
            raise ValueError('CAS requires one Scene Root; other bones must descend from it')
        scene.pivots.extend(world[i] - world[parent] if parent >= 0 else world[i])
    scene.materials = [cas.CasMaterial(texture=texture)]
    shapes = {b.custom_shape for b in rig.pose.bones if b.custom_shape}
    meshes = [o for o in rig.children_recursive if o.type == 'MESH' and o not in shapes]
    if not meshes:
        raise ValueError('The strat armature has no mesh under it')
    previous = rig.data.pose_position
    try:
        rig.data.pose_position = 'REST'
        context.view_layer.update()
        depsgraph = context.evaluated_depsgraph_get()
        for obj in meshes:
            if any(m.type == 'ARMATURE' and m.object != rig for m in obj.modifiers):
                raise ValueError('%s uses another armature' % obj.name)
            evaluated = obj.evaluated_get(depsgraph)
            mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
            try:
                mesh.calc_loop_triangles()
                if not mesh.uv_layers.active:
                    raise ValueError('%s has no UV map' % obj.name)
                transform = evaluated.matrix_world
                if abs(transform.to_3x3().determinant()) < 1e-10:
                    raise ValueError('%s has a singular object transform' % obj.name)
                normal_matrix = transform.to_3x3().inverted().transposed()
                group_bones = {g.index: indices[g.name] for g in obj.vertex_groups if g.name in indices}
                armature_mods = [m for m in obj.modifiers if m.type == 'ARMATURE' and m.show_viewport]
                skinned = bool(armature_mods)
                if skinned and (len(armature_mods) != 1 or armature_mods[0].use_bone_envelopes or
                                not armature_mods[0].use_vertex_groups or armature_mods[0].vertex_group):
                    raise ValueError('%s needs one armature modifier using vertex groups only' % obj.name)
                output = cas.CasObject(name=obj.name, skinned=True, material=0)
                mapping = {}
                uv = mesh.uv_layers.active.data
                reverse = transform.to_3x3().determinant() > 0
                for triangle in mesh.loop_triangles:
                    corners = []
                    for loop_index in triangle.loops:
                        vertex = mesh.vertices[mesh.loops[loop_index].vertex_index]
                        if skinned:
                            weights = [g for g in vertex.groups if g.weight > 1e-6 and g.group in group_bones]
                            if len(weights) != 1:
                                raise ValueError('%s vertex %d needs exactly one bone weight (found %d)' % (obj.name, vertex.index, len(weights)))
                            bone_index = group_bones[weights[0].group]
                            if not bones[bone_index - offset].use_deform:
                                raise ValueError('%s is weighted to a non-deforming bone' % obj.name)
                        else:
                            # Encode static geometry on the container, avoiding
                            # the exporter-specific static attachment convention.
                            bone_index = indices[obj.parent_bone] if obj.parent == rig and obj.parent_type == 'BONE' else 0
                        point = Vector(_axis(transform @ vertex.co)) - world[bone_index]
                        normal = _axis((normal_matrix @ mesh.corner_normals[loop_index].vector).normalized())
                        texcoord = (uv[loop_index].uv.x, 1.0 - uv[loop_index].uv.y)
                        key = (tuple(point), normal, texcoord, bone_index)
                        if key not in mapping:
                            mapping[key] = len(mapping)
                            output.positions.extend(point)
                            output.normals.extend(normal)
                            output.uvs.extend(texcoord)
                            output.bones.append(bone_index)
                        corners.append(mapping[key])
                    output.indices.extend(reversed(corners) if reverse else corners)
                if output.triangles:
                    scene.objects.append(output)
            finally:
                evaluated.to_mesh_clear()
    finally:
        rig.data.pose_position = previous
        context.view_layer.update()
    if not scene.objects:
        raise ValueError('The strat model has no triangles')
    # Validate binary limits and finite values before the caller stages files.
    cas.write_cas(scene)
    return scene
