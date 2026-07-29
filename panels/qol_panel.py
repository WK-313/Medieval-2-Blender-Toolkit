import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty
from ..tasks.armature_tools import skeletonItems, parentToSkeleton
from ..tasks.export_checks import (
    OPT_SUFFIX, splitNumberSuffix, hasOptSuffix, addOptSuffix, removeOptSuffix, splitOptSuffix,
)

# Enum identifiers cannot safely carry spaces, so map them to the actual
# in-mesh prefix strings ("cannon ball0" really does contain a space).
PART_PREFIXES = [
    ('WEAPON0', 'Weapon0', 'weapon0'),
    ('WEAPON1', 'Weapon1', 'weapon1'),
    ('PRIMARYACTIVE0', 'PrimaryActive0', 'primaryactive0'),
    ('PRIMARYACTIVE1', 'PrimaryActive1', 'primaryactive1'),
    ('PRIMARYPASSIVE0', 'PrimaryPassive0', 'primarypassive0'),
    ('PRIMARYPASSIVE1', 'PrimaryPassive1', 'primarypassive1'),
    ('SECONDARYACTIVE0', 'SecondaryActive0', 'secondaryactive0'),
    ('SECONDARYACTIVE1', 'SecondaryActive1', 'secondaryactive1'),
    ('SECONDARYPASSIVE0', 'SecondaryPassive0', 'secondarypassive0'),
    ('SECONDARYPASSIVE1', 'SecondaryPassive1', 'secondarypassive1'),
    ('SHIELD0', 'Shield0', 'shield0'),
    ('SHIELD1', 'Shield1', 'shield1'),
    ('SHIELDACTIVE0', 'ShieldActive0', 'shieldactive0'),
    ('SHIELDACTIVE1', 'ShieldActive1', 'shieldactive1'),
    ('SHIELDPASSIVE0', 'ShieldPassive0', 'shieldpassive0'),
    ('SHIELDPASSIVE1', 'ShieldPassive1', 'shieldpassive1'),
    ('RAMROD0', 'Ramrod0', 'ramrod0'),
    ('CANNON_BALL0', 'Cannon Ball0', 'cannon ball0'),
    ('BALLISTA_ARROW0', 'Ballista Arrow0', 'ballista arrow0'),
]
PREFIX_LOOKUP = {identifier: prefix for identifier, _, prefix in PART_PREFIXES}


class MED_2_TOOLKIT_QOL_Data(bpy.types.PropertyGroup):
    vert_mapping: EnumProperty(
        name="Vertex Mapping",
        items=[
            ('NEAREST', "Nearest Vertex", ""),
            ('EDGEINTERP_NEAREST', "Nearest Edge Interpolated", ""),
            ('POLYINTERP_NEAREST', "Nearest Face Interpolated", ""),
        ],
        default='POLYINTERP_NEAREST'
    )
    clear_groups: BoolProperty(name = "Clear Existing Groups", default = True)
    skeleton: EnumProperty(name = "Skeleton", description = "Skeleton from the addon's armatures folder to parent selected meshes to", items = skeletonItems)
    rename_prefix: EnumProperty(name = "Part Prefix", description = "Prefix applied by Apply Prefix to Selected", items = [(i, label, '') for i, label, _ in PART_PREFIXES], default = 'PRIMARYACTIVE0')


class MED_2_TOOLKIT_OT_Weight_Transfer(bpy.types.Operator):
    """Transfer vertex weights from active to selected objects"""
    bl_idname = "medieval2toolkit.weight_transfer"
    bl_label = "Transfer Weights"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.med2_toolkit_qol

        source_obj = context.active_object
        if not source_obj or source_obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh")
            return {'CANCELLED'}

        selected_objs = [o for o in context.selected_objects if o.type == 'MESH' and o != source_obj]
        if not selected_objs:
            self.report({'WARNING'}, "No other mesh objects selected")
            return {'CANCELLED'}

        if settings.clear_groups:
            for obj in selected_objs:
                obj.vertex_groups.clear()

        orig_active = context.view_layer.objects.active
        orig_selected = context.selected_objects[:]

        for o in context.selected_objects:
            o.select_set(False)
        source_obj.select_set(True)
        for obj in selected_objs:
            obj.select_set(True)
        context.view_layer.objects.active = source_obj

        bpy.ops.object.data_transfer(
            data_type='VGROUP_WEIGHTS',
            vert_mapping=settings.vert_mapping,
            layers_select_src='ALL',
            layers_select_dst='NAME',
            mix_mode='REPLACE',
            mix_factor=1.0,
        )

        # soften the hard edges the mapping leaves behind
        for obj in selected_objs:
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', repeat=5)
            bpy.ops.object.mode_set(mode='OBJECT')

        for o in context.selected_objects:
            o.select_set(False)
        for o in orig_selected:
            o.select_set(True)
        context.view_layer.objects.active = orig_active

        self.report({'INFO'}, f"Transferred weights to {len(selected_objs)} object(s) and smoothed 5x")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Clean_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.clean_number_suffix"
    bl_label = "Clean Number Suffix"
    bl_description = "Remove the .001 style suffix from selected objects. If the base name is taken, the two objects swap names."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cleaned = 0
        for obj in context.selected_objects:
            # Only the trailing .001 number is stripped; an intentional __opt
            # marker sits inside the base and is preserved untouched
            # (object__opt.001 -> object__opt).
            base, number = splitNumberSuffix(obj.name)
            if number:
                holder = bpy.data.objects.get(base)
                if holder and holder is not obj:
                    # Steal the base name; the previous holder takes our suffix
                    suffixed_name = obj.name
                    obj.name = base + ".__swap__"
                    holder.name = suffixed_name
                obj.name = base
                cleaned += 1
        self.report({'INFO'}, f"Cleaned names of {cleaned} object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_Bones_Upper_To_Lower(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_bones_upper_to_lower"
    bl_label = "Rename Bones _R/_L → _r/_l"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        arm = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0

        for bone in arm.edit_bones:
            name = bone.name

            if name.endswith("_RThigh"):
                new = name.replace("_RThigh", "_rthigh")
            elif name.endswith("_LThigh"):
                new = name.replace("_LThigh", "_lthigh")
            else:
                new = name.replace("_R", "_r").replace("_L", "_l")

            if new != name:
                bone.name = new
                count += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Renamed {count} bones")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_Bones_Lower_To_Upper(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_bones_lower_to_upper"
    bl_label = "Rename Bones _r/_l → _R/_L"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        arm = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0

        for bone in arm.edit_bones:
            name = bone.name

            if name.endswith("_rthigh"):
                new = name.replace("_rthigh", "_RThigh")
            elif name.endswith("_lthigh"):
                new = name.replace("_lthigh", "_LThigh")
            else:
                new = name.replace("_r", "_R").replace("_l", "_L")

            if new != name:
                bone.name = new
                count += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Renamed {count} bones")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_To_Prefix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_to_prefix"
    bl_label = "Apply Prefix"
    bl_options = {'REGISTER', 'UNDO'}

    swap: BoolProperty(default = False)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    @classmethod
    def description(cls, context, properties):
        if properties.swap:
            return "x__y or x_y becomes <prefix>__y: the part before the first underscore is replaced with the chosen prefix"
        return "x becomes <prefix>__x: the whole current name is kept after the prefix"

    def execute(self, context):
        prefix = PREFIX_LOOKUP[context.scene.med2_toolkit_qol.rename_prefix]
        renamed = []
        for obj in context.selected_objects:
            name = obj.name
            # The trailing __opt marker (and any .001 number) is intentional:
            # set it aside so it isn't read as the prefix separator or collapsed
            # to a single underscore, then re-append it to the rebuilt name.
            core, opt, number = splitOptSuffix(name)
            if self.swap:
                if "__" in core:
                    suffix = core.split("__", 1)[1]
                elif "_" in core:
                    suffix = core.split("_", 1)[1]
                else:
                    suffix = core
            else:
                suffix = core
            # only the prefix separator may be a double underscore, so any
            # __ inside the kept part collapses to a single _
            suffix = suffix.replace("__", "_")
            new = "%s__%s%s%s" % (prefix, suffix, opt, number)
            if new != name:
                obj.name = new
                renamed.append("%s -> %s" % (name, obj.name))
        if renamed:
            self.report({'INFO'}, "Renamed %d object(s): %s" % (len(renamed), ", ".join(renamed)))
        else:
            self.report({'INFO'}, "No objects needed renaming")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Toggle_Opt_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_opt_suffix"
    bl_label = "Toggle __opt Suffix"
    bl_description = ("Add or remove the __opt optional-part marker on selected objects "
                      "(object <-> object__opt). It is inserted before any trailing number, "
                      "so object.001 becomes object__opt.001, and the cleanup tools leave it intact")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        renamed = []
        for obj in context.selected_objects:
            name = obj.name
            new = removeOptSuffix(name) if hasOptSuffix(name) else addOptSuffix(name)
            if new != name:
                obj.name = new
                renamed.append("%s -> %s" % (name, obj.name))
        if renamed:
            self.report({'INFO'}, "Toggled __opt on %d object(s): %s" % (len(renamed), ", ".join(renamed)))
        else:
            self.report({'INFO'}, "No objects needed changing")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Recreate_Simplebake_UV(bpy.types.Operator):
    bl_idname = "medieval2toolkit.recreate_simplebake_uv"
    bl_label = "Recreate SimpleBake UV"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            uv_layers = obj.data.uv_layers

            existing = uv_layers.get("SimpleBake")
            if existing:
                uv_layers.remove(existing)

            new_uv = uv_layers.new(name="SimpleBake")
            uv_layers.active = new_uv
            count += 1

        self.report({'INFO'}, f"Recreated SimpleBake UV on {count} mesh object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Remove_Baked_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.remove_baked_suffix"
    bl_label = "Remove _Baked Suffix"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.name.endswith("_Baked"):
                obj.name = obj.name[:-6]
                count += 1

        self.report({'INFO'}, f"Removed suffix from {count} object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_To_Skeleton(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_to_skeleton"
    bl_label = "Parent to Skeleton"
    bl_description = "Import the chosen skeleton and parent selected meshes to it, renaming vertex group _R/_L case to match the skeleton's bones. Selecting an armature re-rigs its meshes and removes the old skeleton."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=False)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Parented selection to skeleton")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_Sample_Weights(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_sample_weights"
    bl_label = "Rig with Sample Weights"
    bl_description = "Parent selected meshes to the skeleton and copy weights onto them from its sample body, then remove the sample meshes."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=True, delete_samples=True)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Rigged selection with sample weights")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_Sample_Weights_Keep(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_sample_weights_keep"
    bl_label = "Full Setup (Samples + Equipment)"
    bl_description = "Rig selected meshes with sample weights, keep the sample body for reference, and import the equipment props parented to the skeleton."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=True, delete_samples=False)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Rigged selection; samples and equipment kept in scene")
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Weight_Transfer(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Weight_Transfer"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Weight Transfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        layout.operator("medieval2toolkit.weight_transfer", icon='MOD_DATA_TRANSFER')
        layout.prop(settings, "vert_mapping")
        layout.prop(settings, "clear_groups")


class MED_2_TOOLKIT_PT_Armature(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Armature"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Armature"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        layout.prop(settings, "skeleton", text="Skeleton")
        col = layout.column(align=True)
        col.operator("medieval2toolkit.parent_to_skeleton", icon='ARMATURE_DATA')
        col.operator("medieval2toolkit.parent_sample_weights", icon='MOD_DATA_TRANSFER')
        col.operator("medieval2toolkit.parent_sample_weights_keep", icon='COMMUNITY')


class MED_2_TOOLKIT_PT_Rename_Tools(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Rename_Tools"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Rename Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        col = layout.column(align=True)
        col.operator("medieval2toolkit.clean_number_suffix", icon='FILE_REFRESH')
        col.operator("medieval2toolkit.rename_bones_upper_to_lower", icon='SORT_ASC')
        col.operator("medieval2toolkit.rename_bones_lower_to_upper", icon='SORT_DESC')
        layout.separator()
        col = layout.column(align=True)
        col.prop(settings, "rename_prefix", text="Prefix")
        op = col.operator("medieval2toolkit.rename_to_prefix", icon='ADD', text="Add Prefix (prefix__name)")
        op.swap = False
        op = col.operator("medieval2toolkit.rename_to_prefix", icon='ARROW_LEFTRIGHT', text="Swap Prefix (prefix__y)")
        op.swap = True
        col.operator("medieval2toolkit.toggle_opt_suffix", icon='CHECKBOX_HLT', text="Toggle __opt Suffix")


class MED_2_TOOLKIT_PT_QOL_Advanced(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_QOL_Advanced"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Advanced Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("medieval2toolkit.recreate_simplebake_uv", icon='UV')
        col.operator("medieval2toolkit.remove_baked_suffix", icon='X')


classes = [
    MED_2_TOOLKIT_QOL_Data,
    MED_2_TOOLKIT_OT_Weight_Transfer,
    MED_2_TOOLKIT_OT_Clean_Suffix,
    MED_2_TOOLKIT_OT_Rename_Bones_Upper_To_Lower,
    MED_2_TOOLKIT_OT_Rename_Bones_Lower_To_Upper,
    MED_2_TOOLKIT_OT_Rename_To_Prefix,
    MED_2_TOOLKIT_OT_Toggle_Opt_Suffix,
    MED_2_TOOLKIT_OT_Recreate_Simplebake_UV,
    MED_2_TOOLKIT_OT_Remove_Baked_Suffix,
    MED_2_TOOLKIT_OT_Parent_To_Skeleton,
    MED_2_TOOLKIT_OT_Parent_Sample_Weights,
    MED_2_TOOLKIT_OT_Parent_Sample_Weights_Keep,
    MED_2_TOOLKIT_PT_Weight_Transfer,
    MED_2_TOOLKIT_PT_Armature,
    MED_2_TOOLKIT_PT_Rename_Tools,
    MED_2_TOOLKIT_PT_QOL_Advanced,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_qol = PointerProperty(type=MED_2_TOOLKIT_QOL_Data)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_qol
