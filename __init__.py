
bl_info = {
    "name" : "Medieval 2 Toolkit",
    "author" : "WK",
    "description" : "Bulk import models",
    "blender" : (4, 0, 0),
    "version" : (0, 8, 28, 7),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}

import bpy
import bpy.utils
import sys
import pickle
from bpy.props import StringProperty, BoolProperty
from pathlib import Path
from bpy_extras.io_utils import ImportHelper
from . import EDU_converter, strat_import, single_import, textures_to_assets, bake_textures
script_folder = Path(__file__).parent


def Read_Mod(directory):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_mod"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    EDU_converter.mod_reader(bpy.path.abspath(directory))


def Import_Faction(import_faction, directory, upg_model):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_units"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    EDU_converter.importer(bpy.path.abspath(directory), import_faction, 0, 0, 1, upg_model)


def Import_Unit(import_faction, import_unit, directory, upg_model):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_units"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    EDU_converter.single_importer(bpy.path.abspath(directory), import_faction, import_unit, 0, 0, 1, upg_model)

def Sort_Factions(self, context):
    with open(script_folder/('text/available_factions.pkl'), 'rb') as import_factions_input:
        factions = pickle.load(import_factions_input)
    faction_list = []
    for faction in factions:
        entry = (faction, faction, "")
        faction_list.append(entry)
    return(faction_list)

def Sort_By_Faction(self, context):
    with open(script_folder/('text/master_dictionary.pkl'), 'rb') as master_input:
        master_dictionary = pickle.load(master_input)
    import_faction = context.scene.med2_tools.import_faction_single
    faction_units = []
    for unit in master_dictionary:
        if import_faction in unit["factions"]:
            entry = (unit["name"], unit["name"], "")
            faction_units.append(entry)
    return(faction_units)


def Import_Strat(directory):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_strat"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    strat_import.strat_importer(bpy.path.abspath(directory))


def Import_Single_Dae(directory):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_single_dae"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    single_import.single_importer(bpy.path.abspath(directory))


def Textures_to_Assets(directory):
    # Save the directory
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
        directories = pickle.load(directories_output)
        directories["directory_textures"] = directory
    with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
        pickle.dump(directories, directories_output)
    # Run script
    textures_to_assets.tex_to_asset(bpy.path.abspath(directory))


def Bake_textures(self, context):
    # Settings
    resolution = context.scene.med2_tools.bake_resolution
    alpha_toggle = context.scene.med2_tools.bake_alpha
    reset_uvs = context.scene.med2_tools.bake_reset_uv
    rotation_toggle = context.scene.med2_tools.bake_uv_rotate
    create_material = context.scene.med2_tools.bake_material
    bake_type = context.scene.med2_tools.bake_type
    bake_textures.bake_textures(resolution, alpha_toggle, reset_uvs, rotation_toggle, create_material, bake_type)


class MEDIMPORTER_OT_Properties(bpy.types.PropertyGroup):
    with open(script_folder/('text/directories.pkl'), 'rb') as directories_list:
        try:
            file_paths = pickle.load(directories_list)
        except EOFError:
            print("Empty directories.pkl file. Using default paths")
            file_paths = {
                "directory_mod": "C:\\Program Files",
                "directory_units": "C:\\Program Files",
                "directory_output": "C:\\Program Files",
                "directory_strat": "C:\\Program Files",
                "directory_single_dae": "C:\\Program Files",
                "directory_textures": "C:\\Program Files"
                }
            with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
                pickle.dump(file_paths, directories_output)
    directory_mod: StringProperty(name = "Mod data folder", description = "Directory to read mod data from", default = file_paths["directory_mod"], subtype = "DIR_PATH")
    directory_units: StringProperty(name = "Units folder", description = "Directory to get unit models from", default = file_paths["directory_units"], subtype = "DIR_PATH")
    directory_output: StringProperty(name = "Output directory", description = "Directory to save the unit cards to", default = file_paths["directory_output"], subtype = "DIR_PATH")
    directory_strat: StringProperty(name = "Strat folder", description = "Directory to get strat models from", default = file_paths["directory_strat"], subtype = "DIR_PATH")
    directory_single_dae: StringProperty(name = "Settlement .dae", description = "Directory to get strat models from", default = file_paths["directory_single_dae"], subtype = "FILE_PATH")
    directory_textures: StringProperty(name = "Textures folder", description = "Directory to get textures from", default = file_paths["directory_textures"], subtype = "DIR_PATH")

    import_faction: bpy.props.EnumProperty(name = "Faction list", description = "Select Faction", items = Sort_Factions)
    import_faction_single: bpy.props.EnumProperty(name = "Faction list", description = "Select Faction", items = Sort_Factions)
    import_unit: bpy.props.EnumProperty(name = "Unit list", description = "Select Unit", items = Sort_By_Faction)
    upg_model: bpy.props.IntProperty(name="Upgrade tier", description = "Select armour upgrade level", default = 0, min = 0, max = 3)
    upg_model_single: bpy.props.IntProperty(name="Upgrade tier", description = "Select armour upgrade level", default = 0, min = 0, max = 3)
    controller_type: bpy.props.EnumProperty(name="IK type", description = "Select armour upgrade level", items = [(entry, entry, "") for entry in ["IK_Infantry", "IK_Archer", "IK_Dwarf"]])
    bake_resolution: bpy.props.IntProperty(name="Texture resolution", description = "Select baked texture size", default = 1024, min = 1, soft_max = 4096)
    bake_alpha: bpy.props.BoolProperty(name="Texture Alpha", description = "Select whenever to use transparent background or not", default = False)
    bake_reset_uv: bpy.props.BoolProperty(name="Automatic UVs", description = "Select whenever to use reset bake UVs or not", default = False)
    bake_uv_rotate: bpy.props.BoolProperty(name="UV Rotation", description = "Select whenever to rotate UVs or to keep the original alignment", default = False)
    bake_material: bpy.props.BoolProperty(name="Create Material", description = "Select whenever to use create material for baked textures or not", default = False)
    bake_type: bpy.props.EnumProperty(name = "Bake Type", description = "Select Which textures to bake", items = [('Diffuse','Diffuse',''),('Normal','Normal',''),('Both','Both',''),('None','None','')])

class MEDIMPORTER_PT_Toolkit(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Toolkit"
    bl_label = "Medieval 2 Toolkit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"

    def draw(self, context):
        if(context.mode == 'OBJECT'):
            col = self.layout.column(align=True)


class MEDIMPORTER_PT_Mod_Data(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Mod_Data"
    bl_parent_id = "MEDIMPORTER_PT_Toolkit"
    bl_label = "Mod Data"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"

    def draw(self, context):
        if(context.mode == 'OBJECT'):
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_mod", text="")
            col.operator ("med2toolkit.reader", text="Read Mod Data")


class MEDIMPORTER_OT_Sorter(bpy.types.Operator):
    bl_idname = "med2toolkit.sorter"
    bl_label = "Select Mod Data Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Sort_Factions(self, context)
        Sort_By_Faction(self, context)
        return{"FINISHED"}


class MEDIMPORTER_OT_Reader(bpy.types.Operator):
    bl_idname = "med2toolkit.reader"
    bl_label = "Select Mod Data Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Read_Mod(context.scene.med2_tools.directory_mod)
        return{"FINISHED"}


class MEDIMPORTER_PT_Importer(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Faction_Importer"
    bl_parent_id = "MEDIMPORTER_PT_Toolkit"
    bl_label = "Import Units"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"

    def draw(self, context):
        if(context.mode == 'OBJECT'):
            layout=self.layout
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_units", text="")
            layout.label(text = "Import Faction")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "import_faction", text="")
            col.prop (context.scene.med2_tools, "upg_model", text="Armour upgrade level:")
            col.operator ("med2toolkit.importer", text="Import Faction")
            layout.label(text = "Import Single Unit")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "import_faction_single", text="")
            col.prop (context.scene.med2_tools, "import_unit", text="")
            col.prop (context.scene.med2_tools, "upg_model_single", text="Armour upgrade level:")
            col.operator ("med2toolkit.singe_importer", text="Import Unit")


class MEDIMPORTER_OT_Importer(bpy.types.Operator):
    bl_idname = "med2toolkit.importer"
    bl_label = "Select Models Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        inputs = context.scene.med2_tools
        Import_Faction(context.scene.med2_tools.import_faction, context.scene.med2_tools.directory_units, context.scene.med2_tools.upg_model)
        return{"FINISHED"}


class MEDIMPORTER_OT_Single_Importer(bpy.types.Operator):
    bl_idname = "med2toolkit.singe_importer"
    bl_label = "Select Models Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        inputs = context.scene.med2_tools
        Import_Unit(context.scene.med2_tools.import_faction_single, context.scene.med2_tools.import_unit, context.scene.med2_tools.directory_units, context.scene.med2_tools.upg_model_single)
        return{"FINISHED"}
 


class MEDIMPORTER_PT_Cards(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Cards"
    bl_parent_id = "MEDIMPORTER_PT_Toolkit"
    bl_label = "Unit Cards"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        if(context.mode == 'OBJECT'):
            layout=self.layout
            layout.label(text = "Output Path:")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_output", text="")
            col.operator("med2toolkit.variations", text="Randomize Variations")
            col.operator("med2toolkit.rendered", text="Render Unit Cards")

class MEDIMPORTER_PT_Misc(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Misc"
    bl_parent_id = "MEDIMPORTER_PT_Toolkit"
    bl_label = "Misc."
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        if(context.mode == 'OBJECT'):
            layout=self.layout
            layout.label(text = "Generate IK controller")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "controller_type", text="")
            col.operator("med2toolkit.controller", text="Generate IK controller")
            layout=self.layout
            layout.label(text = "Import Strat Models")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_strat", text="")
            col.operator("med2toolkit.strat", text="Import strat models")
            layout=self.layout
            layout.label(text = "Import Settlement")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_single_dae", text="")
            col.operator("med2toolkit.single_dae", text="Import Settlement")
            layout=self.layout
            layout.label(text = "Textures to assets")
            col = self.layout.column(align=True)
            col.prop (context.scene.med2_tools, "directory_textures", text="")
            col.operator("med2toolkit.tex_to_asset", text="Convert textures to assets")

class MEDIMPORTER_PT_Exp(bpy.types.Panel):
    bl_idname = "MEDIMPORTER_PT_Exp"
    bl_parent_id = "MEDIMPORTER_PT_Misc"
    bl_label = "Experimental"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Med2 Toolkit"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
            if(context.mode == 'OBJECT'):
                layout=self.layout
                layout.label(text = "Bake textures")
                col = self.layout.column(align=True)
                col.prop (context.scene.med2_tools, "bake_resolution", text="Bake Resolution:")
                col.prop (context.scene.med2_tools, "bake_alpha", text="Use alpha transparency:")
                col.prop (context.scene.med2_tools, "bake_reset_uv", text="Automatic Bake UVs:")
                col.prop (context.scene.med2_tools, "bake_uv_rotate", text="Lock UV Rotation:")
                col.prop (context.scene.med2_tools, "bake_material", text="Generate Material:")
                col.prop (context.scene.med2_tools, "bake_type", text="Type")
                if context.object.type == 'MESH' and len(context.object.data.materials) != 0 and len(context.selected_objects) != 0:
                    col.operator("med2toolkit.bake_textures", text="Bake selected textures")

class MEDIMPORTER_OT_Controller(bpy.types.Operator):
    bl_idname = "med2toolkit.controller"
    bl_label = "Randomize unit variations for the selection"
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        if len(context.selected_objects) == 0: return False
        elif len(context.selected_objects) > 1: return False
        return context.object.select_get() and context.object.type == 'ARMATURE'

    def execute(self, context):
        EDU_converter.create_controller(context.scene.med2_tools.controller_type)
        return{"FINISHED"}  



class MEDIMPORTER_OT_Randomizer(bpy.types.Operator):
    bl_idname = "med2toolkit.variations"
    bl_label = "Randomize unit variations for the selection"
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        if len(context.selected_objects) == 0: return False
        return context.object.select_get() and context.object.type == 'ARMATURE'

    def execute(self, context):
        EDU_converter.hide_variations()
        return{"FINISHED"}  


class MEDIMPORTER_OT_Renderer(bpy.types.Operator):
    bl_idname = "med2toolkit.rendered"
    bl_label = "Render unit cards"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # Save the directory
        with open(script_folder/('text/directories.pkl'), 'rb') as directories_output:
            directories = pickle.load(directories_output)
            directories["directory_output"] = context.scene.med2_tools.directory_output
        with open(script_folder/('text/directories.pkl'), 'wb') as directories_output:
            pickle.dump(directories, directories_output)
        # Run script
        EDU_converter.renderer(context.scene.med2_tools.directory_output)
        return{"FINISHED"}


class MEDIMPORTER_OT_Strat(bpy.types.Operator):
    bl_idname = "med2toolkit.strat"
    bl_label = "Select Models Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Import_Strat(context.scene.med2_tools.directory_strat)
        return{"FINISHED"}


class MEDIMPORTER_OT_Single_Dae(bpy.types.Operator):
    bl_idname = "med2toolkit.single_dae"
    bl_label = "Select .dae File"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Import_Single_Dae(context.scene.med2_tools.directory_single_dae)
        return{"FINISHED"}


class MEDIMPORTER_OT_Tex_to_Asset(bpy.types.Operator):
    bl_idname = "med2toolkit.tex_to_asset"
    bl_label = "Select Textures Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Textures_to_Assets(context.scene.med2_tools.directory_textures)
        return{"FINISHED"}

class MEDIMPORTER_OT_Bake_textures(bpy.types.Operator):
    bl_idname = "med2toolkit.bake_textures"
    bl_label = "Select Textures Folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        Bake_textures(self, context)
        return{"FINISHED"}

classes = [
    MEDIMPORTER_PT_Toolkit,
    MEDIMPORTER_OT_Sorter,
    MEDIMPORTER_OT_Properties,
    MEDIMPORTER_PT_Mod_Data,
    MEDIMPORTER_PT_Importer,
    MEDIMPORTER_PT_Cards,
    MEDIMPORTER_PT_Misc,
    MEDIMPORTER_PT_Exp,
    MEDIMPORTER_OT_Reader,
    MEDIMPORTER_OT_Importer,
    MEDIMPORTER_OT_Controller,
    MEDIMPORTER_OT_Randomizer,
    MEDIMPORTER_OT_Renderer,
    MEDIMPORTER_OT_Single_Importer,
    MEDIMPORTER_OT_Strat,
    MEDIMPORTER_OT_Single_Dae,
    MEDIMPORTER_OT_Tex_to_Asset,
    MEDIMPORTER_OT_Bake_textures,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_tools = bpy.props.PointerProperty(type=MEDIMPORTER_OT_Properties)
    bpy.types.Scene.med2_factions = bpy.props.EnumProperty(name = "", description = "Select Faction", items = Sort_Factions)
    bpy.types.Scene.med2_unit = bpy.props.EnumProperty(name = "", description = "Select Unit", items = Sort_By_Faction)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_tools
    del bpy.types.Scene.med2_factions
    del bpy.types.Scene.med2_unit
    
if __name__ == "__main__":
    register()