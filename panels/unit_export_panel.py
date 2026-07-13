import bpy
from bpy.props import BoolProperty, StringProperty, PointerProperty
from ..directories import saveFolderPaths
from ..tasks.unit_exporter import exportArmatureGLB, exportToMeshIWTE, open_folder


class MED_2_TOOLKIT_Unit_Export_Data(bpy.types.PropertyGroup):
    export_visible_only: BoolProperty(name = "Visible Only", description = "Only export visible mesh children of the armature", default = True)
    export_animations: BoolProperty(name = "Export Animations", description = "Bake actions into the GLB. Slow and unnecessary for .mesh conversion, and reimports with the rig posed", default = False)
    export_glb_name: StringProperty(name = "GLB Name", description = "Name of the exported GLB file and its output subfolder", default = "export")
    last_export_dir: StringProperty(default = "", options = {'HIDDEN'})
    last_exported_glb: StringProperty(default = "", options = {'HIDDEN'})


class MED_2_TOOLKIT_OT_Export_Unit_GLB(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_glb"
    bl_label = "Export GLB + Convert Textures"
    bl_description = "Export the selected armature and its meshes to GLB and convert their textures to .texture files."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        saveFolderPaths()
        result = exportArmatureGLB(context)
        if result != "Finished":
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Export complete")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_iwte_mesh"
    bl_label = "Export to Mesh (IWTE)"
    bl_description = "Send the last exported GLB to IWTE to convert it into a .mesh file."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        saveFolderPaths()
        result = exportToMeshIWTE(context)
        if result != "Finished":
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "IWTE mesh export started")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Open_Export_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.open_export_folder"
    bl_label = "Open Output Folder"
    bl_description = "Open the last unit export folder in the file explorer."

    def execute(self, context):
        open_folder(context.scene.med2_toolkit_unit_export.last_export_dir)
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Unit_Export(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Unit_Export"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Unit Export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        export_data = context.scene.med2_toolkit_unit_export

        col = layout.column(align=True)
        col.prop(export_data, "export_visible_only")
        col.prop(export_data, "export_animations")
        col.prop(export_data, "export_glb_name")

        layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT')

        if export_data.last_export_dir:
            layout.operator("medieval2toolkit.open_export_folder", icon='FILE_FOLDER')

        layout.separator()
        layout.label(text="IWTE")
        layout.operator("medieval2toolkit.export_unit_iwte_mesh", icon='MOD_ARMATURE')
        if(context.mode != 'OBJECT'):
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Unit_Export_Data,
    MED_2_TOOLKIT_OT_Export_Unit_GLB,
    MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh,
    MED_2_TOOLKIT_OT_Open_Export_Folder,
    MED_2_TOOLKIT_PT_Unit_Export,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_unit_export = PointerProperty(type=MED_2_TOOLKIT_Unit_Export_Data)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_unit_export
