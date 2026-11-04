"""Bisect in mesh-local space and bake M2 skeleton-aware mirrored weights."""
import re

import bmesh
import bpy

MODIFIER = 'M2 Cut Mirror'
EPSILON = 1e-6
# Imported M2 centre columns sit ~0.0005 off X=0 (position quantisation); snap
# them to the seam rather than cutting a hair-thin strip beside them.
SEAM = 1e-3


def oppositeName(name):
    # M2 side markers precede the limb, rather than ending the bone name.
    match = re.match(r'^(bone_)([LRlr])(clavical|upperarm|elbow|hand|thigh|lowerleg|foot)$',
                     name, re.IGNORECASE)
    if match:
        side = {'L': 'R', 'R': 'L', 'l': 'r', 'r': 'l'}[match[2]]
        return match[1] + side + match[3]
    return bpy.utils.flip_name(name)


def validateMesh(obj):
    if obj.library or obj.data.library or obj.override_library:
        raise ValueError('Make the mesh local before mirroring')
    if obj.data.shape_keys:
        raise ValueError('Shape keys are present; remove them on a working copy first')
    if not obj.data.vertices:
        raise ValueError('Mesh is empty')


def sourceSide(obj):
    # The kept half is whichever side of X=0 still has geometry.
    positive = any(v.co.x > EPSILON for v in obj.data.vertices)
    negative = any(v.co.x < -EPSILON for v in obj.data.vertices)
    if positive and negative:
        raise ValueError('Source vertices cross local X=0; move them back before applying')
    if not (positive or negative):
        raise ValueError('No source geometry off local X=0')
    return 1 if positive else -1


def cutMirror(obj, keep_positive=False):
    validateMesh(obj)
    if any(mod.type == 'MIRROR' for mod in obj.modifiers):
        raise ValueError('A Mirror modifier already exists; apply or remove it first')
    sign = 1 if keep_positive else -1
    side = '+X' if keep_positive else '-X'
    if not any(sign * v.co.x > SEAM for v in obj.data.vertices):
        raise ValueError(f'No geometry on the {side} side of local X=0')
    before = len(obj.data.vertices)
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.bisect_plane(
            bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
            dist=SEAM, plane_co=(0, 0, 0), plane_no=(1, 0, 0),
            clear_outer=not keep_positive, clear_inner=keep_positive)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if -sign * v.co.x > SEAM], context='VERTS')
        for vertex in bm.verts:
            if abs(vertex.co.x) <= SEAM:
                vertex.co.x = 0
        # A linked duplicate must not lose its other half as a side effect.
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    mod = obj.modifiers.new(MODIFIER, 'MIRROR')
    mod.use_axis = (True, False, False)
    mod.use_clip = True
    mod.use_mirror_merge = True
    mod.merge_threshold = EPSILON
    mod.use_mirror_vertex_groups = False
    # Mirror the rest mesh before an Armature or other deformation.
    obj.modifiers.move(len(obj.modifiers) - 1, 0)
    return [f'{obj.name}: {before} -> {len(obj.data.vertices)} source vertices; bisected at local X=0',
            f'{obj.name}: no mirror -> X Mirror with clipping (keep {side})']


def applyMirror(context, obj):
    validateMesh(obj)
    mod = obj.modifiers.get(MODIFIER)
    if not mod or mod.type != 'MIRROR':
        raise ValueError('Use Cut + Mirror first')
    if (obj.modifiers[0] != mod or tuple(mod.use_axis) != (True, False, False)
            or mod.mirror_object or any(mod.use_bisect_axis)
            or mod.use_mirror_vertex_groups):
        raise ValueError('Mirror settings/order changed; restore the original Cut + Mirror settings')
    sign = sourceSide(obj)
    rig = obj.find_armature()
    bones = set(rig.data.bones.keys()) if rig else None
    pairs = {}
    for group in obj.vertex_groups:
        other = oppositeName(group.name)
        if other != group.name:
            if bones is not None and group.name in bones and other not in bones:
                raise ValueError(f'Missing counterpart bone: {group.name} -> {other}')
            # Ignore non-bone utility groups on a rigged mesh.
            if bones is None or group.name in bones:
                pairs[group.name] = other
    for name in pairs.values():
        if name not in obj.vertex_groups:
            obj.vertex_groups.new(name=name)
    mapping = {obj.vertex_groups[a].index: obj.vertex_groups[b].index for a, b in pairs.items()}
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    with context.temp_override(object=obj, active_object=obj):
        result = bpy.ops.object.modifier_apply(modifier=mod.name)
    if result != {'FINISHED'}:
        raise ValueError('Blender could not apply the Mirror modifier')
    # Native group mirroring is disabled: swap exactly once on the new half.
    # Snapshot each vertex before writes so blended L/R weights cannot overwrite.
    for vertex in obj.data.vertices:
        if -sign * vertex.co.x <= EPSILON:
            continue
        weights = [(entry.group, entry.weight) for entry in vertex.groups if entry.group in mapping]
        for source, weight in weights:
            obj.vertex_groups[source].remove([vertex.index])
        for source, weight in weights:
            obj.vertex_groups[mapping[source]].add([vertex.index], weight, 'REPLACE')
    return [f'{obj.name}: X Mirror -> applied mesh; center seam retained'] + [
        f'{obj.name}: mirrored {a} -> {b}' for a, b in sorted(pairs.items())]
