import json
from pathlib import Path

import bpy
from bpy.props import StringProperty

from ..directories import saveFolderPaths, saveSettings
from ..tasks import bmdb_reader, edu_reader, settlements_reader
from .bmdb_panel import sortModels
from .settlements_panel import sortSettlements

script_folder = Path(__file__).parent.parent


def readMod(self, context):
    if context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_directory = context.scene.med2_toolkit_reader.mods_filtered
    else:
        mod_directory = context.scene.med2_toolkit_reader.directory_mod_data
    settlements_result = settlements_reader.findPKGs()
    if settlements_result != "Finished":
        self.report({"ERROR"}, settlements_result)
    edu_result = edu_reader.eduReader(bpy.path.abspath(mod_directory))
    if edu_result != "Finished":
        self.report({"ERROR"}, edu_result)
    bmdb_result = bmdb_reader.bmdbReader(bpy.path.abspath(mod_directory))
    if bmdb_result != "Finished":
        self.report({"ERROR"}, bmdb_result)
    sortModels(self, context)
    sortSettlements(self, context)


def modString():
    with open(script_folder / ("text/directories.json"), "r") as directories_list:
        file_paths = json.load(directories_list)
    mod_list = file_paths["directory_mod_list"]
    return mod_list


def refreshMods(self, context):
    master_directory = Path(context.scene.med2_toolkit_reader.directory_med2) / "mods"
    mods = []
    if master_directory.exists():
        for mod_folder in master_directory.iterdir():
            if not mod_folder.is_dir():
                continue
            for subdir in mod_folder.iterdir():
                if subdir.is_dir() and subdir.name == "data":
                    mods.append(str(subdir))
    with open(script_folder / "text" / "directories.json", "r") as directories_list:
        file_paths = json.load(directories_list)
    file_paths["directory_mod_list"] = ",".join(mods)
    with open(script_folder / "text" / "directories.json", "w") as directories_output:
        json.dump(file_paths, directories_output, indent=2)


def modList(self, context):
    mod_string = context.scene.med2_toolkit_reader.list_holder
    mod_list = mod_string.split(",")
    enum_list = []
    for mod in mod_list:
        # entry = (mod, mod, "")
        try:
            display_name = Path(mod).parent.name
        except Exception:
            display_name = mod
        entry = (mod, display_name, mod)
        enum_list.append(entry)
    entry = ("custom", "Custom", "")
    enum_list.append(entry)
    return enum_list


class MED2_TOOLKIT_OT_Properties(bpy.types.PropertyGroup):
    with open(script_folder / ("text/directories.json"), "r") as directories_list:
        try:
            file_paths = json.load(directories_list)
        except EOFError:
            file_paths = {
                "directory_med2": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War",
                "directory_iwte": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War\\mods",
                "directory_mod_list": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War\\mods",
                "directory_mod_data": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War\\mods",
                "directory_models": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War\\mods",
                "directory_settlements": "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Medieval II Total War\\mods",
            }
            with open(
                script_folder / ("text/directories.json"), "w"
            ) as directories_output:
                json.dump(file_paths, directories_output, indent=2)
    list_holder: StringProperty(
        name="Mod list",
        description="String list of mod folders",
        default=file_paths["directory_mod_list"],
    )
    directory_med2: StringProperty(
        name="Medieval 2 path",
        description="Directory to vanilla Medieval 2",
        default=file_paths["directory_med2"],
        subtype="DIR_PATH",
    )
    directory_iwte: StringProperty(
        name="IWTE path",
        description="IWTE.exe location",
        default=file_paths["directory_iwte"],
        subtype="DIR_PATH",
    )
    mods_filtered: bpy.props.EnumProperty(
        name="Mods",
        description="List of mods with data folders in the Medieval 2 directory",
        items=modList,
    )
    directory_mod_data: StringProperty(
        name="Mod data path",
        description="Directory to read mod data from",
        default=file_paths["directory_mod_data"],
        subtype="DIR_PATH",
    )
    directory_models: StringProperty(
        name="Unit output path",
        description="Directory to save extracted unit models",
        default=file_paths["directory_models"],
        subtype="DIR_PATH",
    )
    directory_settlements: StringProperty(
        name="Settlement output path",
        description="Directory to save extracted settlement models",
        default=file_paths["directory_settlements"],
        subtype="DIR_PATH",
    )


class MED2_TOOLKIT_OT_Refresh_Mods(bpy.types.Operator):
    bl_idname = "medieval2toolkit.refresh_mods"
    bl_label = "Refresh Mod List"
    bl_description = "Refresh the list of available mods."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        refreshMods(self, context)
        bpy.context.scene.med2_toolkit_reader.list_holder = modString()
        self.report({"INFO"}, "Updated mod list.")
        return {"FINISHED"}


class MED2_TOOLKIT_OT_Reader(bpy.types.Operator):
    bl_idname = "medieval2toolkit.reader"
    bl_label = "Select Mod Data Folder"
    bl_description = "Read the unit and model data from the specified mod."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        saveFolderPaths()
        saveSettings()
        readMod(self, context)
        self.report({"INFO"}, "Finished reading mod data.")
        return {"FINISHED"}


class MED2_TOOLKIT_PT_Mod_Data(bpy.types.Panel):
    bl_idname = "MED2_TOOLKIT_PT_Mod_Data"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Paths"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Medieval 2 Toolkit"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.prop(context.scene.med2_toolkit_reader, "directory_med2", text="Medieval 2")
        col.prop(context.scene.med2_toolkit_reader, "directory_iwte", text="IWTE")
        if context.scene.med2_toolkit_mode.mode_selection == "units":
            col.prop(
                context.scene.med2_toolkit_reader,
                "directory_models",
                text="Unit Output",
            )
        else:
            col.prop(
                context.scene.med2_toolkit_reader,
                "directory_settlements",
                text="Settlement Output",
            )
        row = col.row(align=True)
        row.prop(context.scene.med2_toolkit_reader, "mods_filtered", text="Mod")
        row.operator("medieval2toolkit.refresh_mods", icon="FILE_REFRESH", text="")
        if context.scene.med2_toolkit_reader.mods_filtered == "custom":
            col.prop(
                context.scene.med2_toolkit_reader,
                "directory_mod_data",
                text="Manual Path",
            )
        col = layout.column(align=True)
        col.operator("medieval2toolkit.reader", text="Read Mod Data")
        if context.mode != "OBJECT":
            layout.enabled = False


classes = [
    MED2_TOOLKIT_OT_Properties,
    MED2_TOOLKIT_OT_Refresh_Mods,
    MED2_TOOLKIT_OT_Reader,
    MED2_TOOLKIT_PT_Mod_Data,
]


def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_reader = bpy.props.PointerProperty(
        type=MED2_TOOLKIT_OT_Properties
    )


def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
