
bl_info = {
    "name" : "Medieval 2 Toolkit V1.0.2",
    "author" : "WK",
    "description" : "Collection of tools and features for modders of Medieval 2: Total War",
    "blender" : (5, 0, 0),
    "version" : (1, 0, 2),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}

import bpy
from .directories import ensureDataFiles
ensureDataFiles()
from .panels import mod_data, edu_panel, bmdb_panel, settlements_panel, unit_export_panel, qol_panel
from bpy.props import EnumProperty, PointerProperty


class MED_2_TOOLKIT_Mode_Selection(bpy.types.PropertyGroup):
    mode_selection: EnumProperty(items = [("unit_import", "Unit Import", ""), ("unit_export", "Unit Export", ""), ("settlements", "Settlements", ""), ("qol", "QOL", "")], name = "Mode selection", description = "Select the workmode")

class MED_2_TOOLKIT_PT_Main_Panel(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Medieval 2 Toolkit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    def draw(self, context):
        layout=self.layout
        layout.label(text = "Workmode:")
        col = layout.column(align=True)
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.prop(context.scene.med2_toolkit_mode, "mode_selection", expand=True)


classes = [
    MED_2_TOOLKIT_PT_Main_Panel,
    MED_2_TOOLKIT_Mode_Selection,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_mode = PointerProperty(type=MED_2_TOOLKIT_Mode_Selection)
    mod_data.register()
    edu_panel.register()
    bmdb_panel.register()
    settlements_panel.register()
    unit_export_panel.register()
    qol_panel.register()

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_mode
    mod_data.unregister()
    edu_panel.unregister()
    bmdb_panel.unregister()
    settlements_panel.unregister()
    unit_export_panel.unregister()
    qol_panel.unregister()

if __name__ == "__main__":
    register()