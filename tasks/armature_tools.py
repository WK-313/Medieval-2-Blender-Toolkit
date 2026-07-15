import bpy
from mathutils import Matrix
from pathlib import Path

addon_folder = Path(__file__).parent.parent

def armaturesFolder():
    return addon_folder/'armatures'

# Kept alive at module level: Blender requires dynamic EnumProperty item
# strings to stay referenced, otherwise they get garbage collected.
_skeleton_items = []

def skeletonItems(self, context):
    global _skeleton_items
    items = []
    folder = armaturesFolder()
    if folder.exists():
        for glb in sorted(folder.glob('*.glb')):
            stem = glb.stem
            # Equipment.glb holds unrigged sample meshes, not a skeleton
            if stem.lower().endswith('_sample') or stem.lower() == 'equipment':
                continue
            items.append((stem, stem, ''))
    if not items:
        items = [('none', 'None', 'No skeleton .glb files found in the armatures folder')]
    _skeleton_items = items
    return _skeleton_items

def skeletonUsesLowercase(armature):
    for bone in armature.data.bones:
        if '_R' in bone.name or '_L' in bone.name:
            return False
    return True

def caseConvertedName(name, to_lower):
    if to_lower:
        if name.endswith('_RThigh'):
            return name.replace('_RThigh', '_rthigh')
        if name.endswith('_LThigh'):
            return name.replace('_LThigh', '_lthigh')
        return name.replace('_R', '_r').replace('_L', '_l')
    if name.endswith('_rthigh'):
        return name.replace('_rthigh', '_RThigh')
    if name.endswith('_lthigh'):
        return name.replace('_lthigh', '_LThigh')
    return name.replace('_r', '_R').replace('_l', '_L')

def mergeGroupInto(obj, source, target):
    """Fold source's weights into target (clamped sum) and delete source."""
    source_index = source.index
    target_index = target.index
    for vertex in obj.data.vertices:
        weight = 0.0
        existing = 0.0
        for entry in vertex.groups:
            if entry.group == source_index:
                weight = entry.weight
            elif entry.group == target_index:
                existing = entry.weight
        if weight > 0.0:
            target.add([vertex.index], min(1.0, existing + weight), 'REPLACE')
    obj.vertex_groups.remove(source)

def renameGroupsCase(obj, to_lower):
    # Repair numbered duplicates (bone_rhand.001) left behind by earlier
    # collisions before converting case.
    for group in list(obj.vertex_groups):
        if "." in group.name and group.name.split(".")[-1].isdigit():
            base = obj.vertex_groups.get(group.name.rsplit(".", 1)[0])
            if base is not None:
                mergeGroupInto(obj, group, base)
    # Renaming onto a name that already exists would silently produce a .001
    # group; merge into the existing group instead so weights are reused.
    for group in list(obj.vertex_groups):
        new = caseConvertedName(group.name, to_lower)
        if new == group.name:
            continue
        existing = obj.vertex_groups.get(new)
        if existing is not None:
            mergeGroupInto(obj, group, existing)
        else:
            group.name = new

def transferSampleWeights(context, source, targets):
    settings = context.scene.med2_toolkit_qol
    if settings.clear_groups:
        for target in targets:
            target.vertex_groups.clear()
    bpy.ops.object.select_all(action='DESELECT')
    source.select_set(True)
    for target in targets:
        target.select_set(True)
    context.view_layer.objects.active = source
    bpy.ops.object.data_transfer(
        data_type='VGROUP_WEIGHTS',
        vert_mapping=settings.vert_mapping,
        layers_select_src='ALL',
        layers_select_dst='NAME',
        mix_mode='REPLACE',
        mix_factor=1.0,
    )

def importEquipment(context, armature, to_lower):
    equipment_path = armaturesFolder()/'Equipment.glb'
    if not equipment_path.exists():
        return
    previous_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(equipment_path))
    imported = [o for o in bpy.data.objects if o not in previous_objects]
    # Re-home the weighted props onto the main skeleton first, then drop the
    # equipment rig and placeholder junk that shipped alongside them.
    for obj in imported:
        if obj.type != 'MESH' or not obj.vertex_groups:
            continue
        renameGroupsCase(obj, to_lower)
        for modifier in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(modifier)
        world_matrix = obj.matrix_world.copy()
        obj.parent = armature
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = world_matrix
        modifier = obj.modifiers.new('Armature', 'ARMATURE')
        modifier.object = armature
    for obj in imported:
        if obj.type != 'MESH' or not obj.vertex_groups:
            bpy.data.objects.remove(obj, do_unlink=True)

def parentToSkeleton(context, transfer_weights=False, delete_samples=True):
    skeleton = context.scene.med2_toolkit_qol.skeleton
    if skeleton == 'none':
        return 'No skeleton .glb files found in the armatures folder'
    targets = [o for o in context.selected_objects if o.type == 'MESH']
    if not targets:
        return 'Select at least one mesh object'

    variant = skeleton + ('_Sample' if transfer_weights else '') + '.glb'
    glb_path = armaturesFolder()/variant
    if not glb_path.exists():
        return 'Missing %s in the armatures folder' % variant

    previous_objects = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported = [o for o in bpy.data.objects if o not in previous_objects]
    armature = next((o for o in imported if o.type == 'ARMATURE'), None)
    if armature is None:
        for o in imported:
            bpy.data.objects.remove(o, do_unlink=True)
        return 'No armature found inside %s' % variant

    # The GLBs can carry a stray pose; weight transfer maps between evaluated
    # meshes, so the sample body must sit at its bind pose or nothing lines up.
    for pose_bone in armature.pose.bones:
        pose_bone.matrix_basis = Matrix.Identity(4)

    # Rename weights first, before any parenting, so group case always
    # matches the new skeleton by the time the rig is attached.
    to_lower = skeletonUsesLowercase(armature)
    for obj in targets:
        renameGroupsCase(obj, to_lower)

    for obj in targets:
        for modifier in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(modifier)
        world_matrix = obj.matrix_world.copy()
        obj.parent = armature
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_world = world_matrix
        modifier = obj.modifiers.new('Armature', 'ARMATURE')
        modifier.object = armature

    result = 'Finished'
    source = None
    if transfer_weights:
        source = next((o for o in imported if o.type == 'MESH' and o.name.lower().startswith('sample__body')), None)
        if source is None:
            result = 'Parented, but no sample__body mesh found inside %s' % variant
        else:
            context.view_layer.update()
            transferSampleWeights(context, source, targets)

    # Imported meshes are never the user's originals, so only they are
    # candidates for cleanup here (sample bodies, the placeholder Icosphere).
    for obj in imported:
        if obj is armature or obj.type != 'MESH':
            continue
        is_sample = 'sample' in obj.name.lower()
        if delete_samples or not is_sample:
            if obj is source:
                source = None
            bpy.data.objects.remove(obj, do_unlink=True)

    # Full setup mode also brings in the equipment reference props.
    if transfer_weights and not delete_samples:
        importEquipment(context, armature, to_lower)

    # Leave the transfer setup visible: sample body active, the user's
    # meshes passively selected, so a manual re-transfer is one click away.
    bpy.ops.object.select_all(action='DESELECT')
    for target in targets:
        target.select_set(True)
    if source is not None:
        source.select_set(True)
        context.view_layer.objects.active = source
    else:
        context.view_layer.objects.active = armature
    return result
