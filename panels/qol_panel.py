import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty
from ..tasks.armature_tools import skeletonItems, parentToSkeleton


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

        for o in context.selected_objects:
            o.select_set(False)
        for o in orig_selected:
            o.select_set(True)
        context.view_layer.objects.active = orig_active

        self.report({'INFO'}, f"Transferred weights to {len(selected_objs)} object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Clean_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.clean_number_suffix"
    bl_label = "Clean Number Suffix"
    bl_description = "Remove the .001 style suffix from selected objects. If the base name is taken, the two objects swap names."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cleaned = 0
        for obj in context.selected_objects:
            if "." in obj.name and obj.name.split(".")[-1].isdigit():
                base = obj.name.rsplit(".", 1)[0]
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
    bl_description = "Import the chosen skeleton and parent selected meshes to it, renaming vertex group _R/_L case to match the skeleton's bones."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

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
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

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
        return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)

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
        col = layout.column(align=True)
        col.operator("medieval2toolkit.clean_number_suffix", icon='FILE_REFRESH')
        col.operator("medieval2toolkit.rename_bones_upper_to_lower", icon='SORT_ASC')
        col.operator("medieval2toolkit.rename_bones_lower_to_upper", icon='SORT_DESC')


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
