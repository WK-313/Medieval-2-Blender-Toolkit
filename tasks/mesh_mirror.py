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
    rig = obj.find_armature()
    bones = set(rig.data.bones.keys()) if rig else None
    pairs = {}
    for group in obj.vertex_groups if remap else ():
        other = oppositeName(group.name)
        if other != group.name:
            if bones is not None and group.name in bones and other not in bones:
                raise ValueError(f'Missing counterpart bone: {group.name} -> {other}')
            # Ignore non-bone utility groups on a rigged mesh.
            if bones is None or group.name in bones:
                pairs[group.name] = other
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    with context.temp_override(object=obj, active_object=obj):
        result = bpy.ops.object.modifier_apply(modifier=mod.name)
    if result != {'FINISHED'}:
        raise ValueError('Blender could not apply the Mirror modifier')
    # Applying an already evaluated modifier can restore its old group list.
    # Create missing counterparts and resolve indices only on the applied mesh.
    for name in pairs.values():
        if name not in obj.vertex_groups:
            obj.vertex_groups.new(name=name)
    mapping = {obj.vertex_groups[a].index: obj.vertex_groups[b].index for a, b in pairs.items()}
    # Native group mirroring is disabled; handle reflected copies below.
    # Snapshot each vertex before writes so blended L/R weights cannot overwrite.
    for vertex in obj.data.vertices:
        # Each reflection swaps sides once; two reflections cancel the swap.
        reflections = sum(-signs[axis] * vertex.co[axis] > EPSILON for axis in active)
        if not reflections % 2:
            continue
        weights = [(entry.group, entry.weight) for entry in vertex.groups if entry.group in mapping]
        for source, weight in weights:
            obj.vertex_groups[source].remove([vertex.index])
        for source, weight in weights:
            obj.vertex_groups[mapping[source]].add([vertex.index], weight, 'REPLACE')
    return [f'{obj.name}: {label} Mirror -> applied mesh; center seam retained'] + ([
        f'{obj.name}: weight mirroring -> skipped (primary/secondary item)' if skip_item else
        f'{obj.name}: weight mirroring -> disabled; copied source weights retained'] if not remap else []) + [
        f'{obj.name}: mirrored {a} -> {b}' for a, b in sorted(pairs.items())]
