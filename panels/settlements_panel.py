import bpy
import os
from pathlib import Path
import json
from bpy.props import StringProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty, BoolProperty
from ..tasks.settlement_importer import settlementImporter
from ..tasks.task_writer import settlementTaskWriter
from..directories import saveFolderPaths, saveSettings


script_folder = Path(__file__).parent.parent

def sortFolders(self, context):
    with open(os.path.join(script_folder, "text", "settlement_folders.json"), 'r') as pkg_input:
        folders = json.load(pkg_input)
    folder_list = []
    for folder in folders:
        entry = (folder.lower(), folder.title(), "")
        folder_list.append(entry)
    entry = ("all", "All", "")
    folder_list.append(entry)
    return folder_list

def sortSettlements(self, context):
    with open(script_folder/('text/settlement_pkgs.json'), 'r') as import_settlements_input:
        settlements_dictionary = json.load(import_settlements_input)
    filter_folder = context.scene.med2_toolkit_settlements.settlement_folders
    filter_type = context.scene.med2_toolkit_settlements.pkg_types
    context.scene.med2_toolkit_settlements_list.clear()
    context.scene.med2_toolkit_settlements_list_index = 0
    for settlement in settlements_dictionary:
        if filter_folder == 'all' and (filter_type == 'all' or filter_type == settlements_dictionary[settlement]["type"]):
            item = bpy.context.scene.med2_toolkit_settlements_list.add()
            item.name = settlement.title()
            item.translation = settlements_dictionary[settlement]["name"]
            item.folder = settlements_dictionary[settlement]["folder"]
            item.world = settlements_dictionary[settlement]["world"]
        elif filter_folder in settlements_dictionary[settlement]["folder"] and (filter_type == 'all' or filter_type == settlements_dictionary[settlement]["type"]):
            item = bpy.context.scene.med2_toolkit_settlements_list.add()
            item.name = settlement.title()
            item.translation = settlements_dictionary[settlement]["name"]
            item.folder = settlements_dictionary[settlement]["folder"]
            item.world = settlements_dictionary[settlement]["world"]
    return{'FINISHED'}

class MED_2_TOOLKIT_Settlement_Data(bpy.types.PropertyGroup):
    with open(script_folder/('text/menu_settings.json'), 'r') as settings_input:
            bool_settings = json.load(settings_input)
    use_existing_settlement: BoolProperty(name = "Use existing", description = "If on, use already converted files when importing settlements", default = bool_settings['use_existing_settlement'])
    settlement_folders: EnumProperty(name = "Settlements", description = "List of settlement .worldpkgdesc files in the mod directory", items = sortFolders)
    pkg_types: EnumProperty(name = "Pkg Types", description = "PKG groups", items = [("settlement", "Settlement", ""), ("ambient", "Ambient", ""), ("ambientmisc", "Ambient Misc", ""), ("techtree", "Tech Tree", ""), ("rivercrossing", "River Crossing", ""), ("fieldfortification", "Field Fortification", ""), ("all", "All", "")])


class MED_2_TOOLKIT_PT_Settlements_Panel(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Settlements_Panel"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Settlements"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        if (context.scene.med2_toolkit_mode.mode_selection != 'settlements'):
            return False
        return True
    
    def draw(self, context):
        layout=self.layout
        layout.label(text = "W.I.P.")
        box = layout.box()
        col = box.column(align=True)
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.prop (context.scene.med2_toolkit_settlements, "use_existing_settlement", text="Use existing:", toggle = 1)
        row = layout.row(align=True)
        row.prop(context.scene.med2_toolkit_settlements, "settlement_folders", text="Folder")
        row.prop(context.scene.med2_toolkit_settlements, "pkg_types", text="Type")
        row.operator("medieval2toolkit.sort_settlements", icon = "FILE_REFRESH", text = "")
        col = layout.column()
        col.template_list("MED_2_TOOLKIT_UL_Settlement_List", "Settlements_list", context.scene, "med2_toolkit_settlements_list", context.scene, "med2_toolkit_settlements_list_index")
        if context.scene.med2_toolkit_settlements_list_index >= 0 and context.scene.med2_toolkit_settlements_list:
            settlement = context.scene.med2_toolkit_settlements_list[context.scene.med2_toolkit_settlements_list_index]
            col = layout.column(align=True)
            col.prop (settlement, "translation")
            col.prop (settlement, "world")
            col.prop (settlement, "folder")
        col = layout.column()
        col.operator("medieval2toolkit.import_settlement", text = "Import settlement")
        if(context.mode != 'OBJECT'):
            layout.enabled = False


class MED_2_TOOLKIT_OT_Sort_Settlements(bpy.types.Operator):
    bl_idname = "medieval2toolkit.sort_settlements"
    bl_label = "Sort Settlements"
    bl_description = "Filter the settlements into a list based on the selected folder."

    def execute(self, context):
        saveFolderPaths()
        saveSettings()
        sortSettlements(self, context)
        self.report({'INFO'}, "Updated settlement list.")
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Import_Settlement(bpy.types.Operator):
    bl_idname = "medieval2toolkit.import_settlement"
    bl_label = "Import Settlement"
    bl_description = "Import the selected settlement."

    def execute(self, context):
        settlement_folder = str(bpy.context.scene.med2_toolkit_reader.directory_settlements)
        name = context.scene.med2_toolkit_settlements_list[context.scene.med2_toolkit_settlements_list_index].name
        world = context.scene.med2_toolkit_settlements_list[context.scene.med2_toolkit_settlements_list_index].world
        saveFolderPaths()
        saveSettings()
        settlementTaskWriter()
        settlementImporter(settlement_folder, name, world)
        self.report({'INFO'}, "Finished importing settlement.")
        return{"FINISHED"}


class MED_2_TOOLKIT_Settlement_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="Pkg", description="Pkg file name")
    world: StringProperty(name="World", description="World file")
    translation: StringProperty(name="Name", description="Name of the settlement")
    folder: StringProperty(name="Folder", description="Location of the settlement")


class MED_2_TOOLKIT_UL_Settlement_List(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text = "")


classes = [
    MED_2_TOOLKIT_Settlement_Data,
    MED_2_TOOLKIT_PT_Settlements_Panel,
    MED_2_TOOLKIT_OT_Sort_Settlements,
    MED_2_TOOLKIT_OT_Import_Settlement,
    MED_2_TOOLKIT_Settlement_List_Items,
    MED_2_TOOLKIT_UL_Settlement_List,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_settlements = PointerProperty(type=MED_2_TOOLKIT_Settlement_Data)
    bpy.types.Scene.med2_toolkit_settlements_list = CollectionProperty(type = MED_2_TOOLKIT_Settlement_List_Items)
    bpy.types.Scene.med2_toolkit_settlements_list_index = IntProperty(name = "Index of the selected settlement", default = 0)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_settlements
    del bpy.types.Scene.med2_toolkit_settlements_list
    del bpy.types.Scene.med2_toolkit_settlements_list_index
