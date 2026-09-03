
bl_info = {
    "name" : "Medieval 2 Toolkit V1.4.8",
    "author" : "WK",
    "description" : "Collection of tools and features for modders of Medieval 2: Total War",
    "blender" : (5, 0, 0),
    "version" : (1, 4, 8),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}

import bpy
from .directories import ensureDataFiles
ensureDataFiles()
from .panels import mod_data, edu_panel, bmdb_panel, settlements_panel, unit_export_panel, unit_info_panel, qol_panel, pose_panel, strat_panel
from .panels import multi_panel
from bpy.props import EnumProperty, PointerProperty


class MED_2_TOOLKIT_Mode_Selection(bpy.types.PropertyGroup):
    # The values are what every panel's poll() tests, so they are kept as they
    # were. The order here is NOT the strip's - multi_panel.SECTIONS carries
    # that, and only the classic layout's button grid draws in this order.
    # Reordering these items would re-point every saved .blend, since an enum
    # is stored as the item's position, not its identifier.
    mode_selection: EnumProperty(
        items = [("unit_import", "Import", "Read a mod's units and models in - EDU and BMDB"),
                 ("unit_export", "Export", "Take a finished unit back out to the mod"),
                 ("strat", "Strat", "Turn a battle unit into a campaign map model and convert it to .cas"),
                 ("settlements", "Settlement", "Settlement pieces"),
                 ("qol", "QOL", "Rigging, renaming, weights, poses and the other everyday tools"),
                 ("unit_info", "Unit Cards", "Build the card scene and render unit cards")],
        name = "Mode selection", description = "Select the workmode", default = "unit_import")


class MED_2_TOOLKIT_PT_Main_Panel(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Medieval 2 Toolkit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    def draw(self, context):
        multi_panel.drawMainPanel(context, self.layout)


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
    unit_info_panel.register()
    qol_panel.register()
    pose_panel.register()
    strat_panel.register()
    # last: it imports the panel classes the modules above define
    multi_panel.register()

def unregister():
    multi_panel.unregister()
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_mode
    mod_data.unregister()
    edu_panel.unregister()
    bmdb_panel.unregister()
    settlements_panel.unregister()
    unit_export_panel.unregister()
    unit_info_panel.unregister()
    qol_panel.unregister()
    pose_panel.unregister()
    strat_panel.unregister()

if __name__ == "__main__":
    register()