"""Let Blender's native weight paint mirror recognize M2 bone pairs."""
import bpy

from .mesh_mirror import M2_SIDE_NAME, oppositeName

PAINT_NAMES = 'med2_weight_paint_names'
PAINT_SETTINGS = 'med2_weight_paint_settings'


def paintRig(obj):
    if obj and obj.type == 'ARMATURE':
        return obj
    if obj and obj.type == 'MESH':
        return next((mod.object for mod in obj.modifiers
                     if mod.type == 'ARMATURE' and mod.object and mod.use_vertex_groups), None)
    return None


def togglePaintSymmetry(rig, active):
    armature = rig.data
    if rig.library or rig.override_library or armature.library or armature.users > 1:
        raise ValueError('Weight Paint symmetry needs a local armature with its own data')
    if armature.is_editmode:
        raise ValueError('Leave armature Edit Mode first')

    saved_names = armature.get(PAINT_NAMES)
    if saved_names is not None:
        names = dict(saved_names)
    else:
        names = {}
        for bone in armature.bones:
            match = M2_SIDE_NAME.fullmatch(bone.name)
            if match:
                other = oppositeName(bone.name)
                if other not in armature.bones:
                    raise ValueError(f'Missing counterpart bone: {bone.name} -> {other}')
                prefix, side, limb = match.groups()
                names[bone.name] = f'{prefix}{limb}.{side}'
        if not names:
            raise ValueError('No Medieval II left/right bone pairs found')
        if active.type != 'MESH':
            raise ValueError('Select the mesh you want to paint')

    bound = []
    for obj in bpy.data.objects:
        rigs = {mod.object for mod in obj.modifiers if mod.type == 'ARMATURE' and mod.object}
        if rig not in rigs:
            continue
        if (len(rigs) > 1 or obj.library or obj.override_library
                or obj.data.library or obj.data.users > 1
                or (obj.type == 'MESH' and obj.data.is_editmode)):
            raise ValueError(f'{obj.name}: Weight Paint symmetry needs local data bound to one rig')
        bound.append(obj)

    # Blender propagates bone renames to the rig's bound vertex groups. Check
    # both namespaces first so Blender cannot suffix or skip a name on collision.
    for old, new in names.items():
        if old not in armature.bones:
            raise ValueError(f'Cannot restore a renamed or deleted paint bone: {old}')
        if new in armature.bones:
            raise ValueError(f'Bone name already exists: {old} -> {new}')
        for obj in bound:
            if new in obj.vertex_groups:
                raise ValueError(f'{obj.name}: vertex group already exists: {new}')

    for old, new in names.items():
        armature.bones[old].name = new
    if saved_names is not None:
        del armature[PAINT_NAMES]
        for obj in bound:
            if obj.type == 'MESH' and PAINT_SETTINGS in obj.data:
                mirror_x, mirror_groups = obj.data[PAINT_SETTINGS]
                obj.data.use_mirror_x = bool(mirror_x)
                obj.data.use_mirror_vertex_groups = bool(mirror_groups)
                del obj.data[PAINT_SETTINGS]
    else:
        armature[PAINT_NAMES] = {new: old for old, new in names.items()}
        mesh = active.data
        mesh[PAINT_SETTINGS] = [int(mesh.use_mirror_x), int(mesh.use_mirror_vertex_groups)]
        mesh.use_mirror_x = True
        mesh.use_mirror_vertex_groups = True
    return [f'{rig.name}: {old} -> {new}' for old, new in sorted(names.items())]
