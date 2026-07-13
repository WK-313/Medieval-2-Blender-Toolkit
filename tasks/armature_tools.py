import bpy
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

def renameGroupsCase(obj, to_lower):
    for group in obj.vertex_groups:
        name = group.name
        if to_lower:
            if name.endswith('_RThigh'):
                new = name.replace('_RThigh', '_rthigh')
            elif name.endswith('_LThigh'):
                new = name.replace('_LThigh', '_lthigh')
            else:
                new = name.replace('_R', '_r').replace('_L', '_l')
        else:
            if name.endswith('_rthigh'):
                new = name.replace('_rthigh', '_RThigh')
            elif name.endswith('_lthigh'):
                new = name.replace('_lthigh', '_LThigh')
            else:
                new = name.replace('_r', '_R').replace('_l', '_L')
        if new != name:
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

    to_lower = skeletonUsesLowercase(armature)
    for obj in targets:
        renameGroupsCase(obj, to_lower)
        for modifier in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(modifier)
        obj.parent = armature
        obj.matrix_parent_inverse = armature.matrix_world.inverted()
        modifier = obj.modifiers.new('Armature', 'ARMATURE')
        modifier.object = armature

    result = 'Finished'
    if transfer_weights:
        source = next((o for o in imported if o.type == 'MESH' and o.name.lower().startswith('sample__body')), None)
        if source is None:
            result = 'Parented, but no sample__body mesh found inside %s' % variant
        else:
            transferSampleWeights(context, source, targets)

    # Imported meshes are never the user's originals, so only they are
    # candidates for cleanup here (sample bodies, the placeholder Icosphere).
    for obj in imported:
        if obj is armature or obj.type != 'MESH':
            continue
        is_sample = 'sample' in obj.name.lower()
        if delete_samples or not is_sample:
            bpy.data.objects.remove(obj, do_unlink=True)

    bpy.ops.object.select_all(action='DESELECT')
    for target in targets:
        target.select_set(True)
    context.view_layer.objects.active = armature
    return result
