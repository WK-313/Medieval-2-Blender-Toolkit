import bpy
import os
import json
import subprocess
from pathlib import Path
from..directories import saveFolderPaths, saveSettings
from ..tasks.task_writer import unitTaskWriter
from ..tasks.importer import fileChecker, modelImporter, importedArmature, postImport
from bpy.props import StringProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty

script_folder = Path(__file__).parent.parent

def sortFactions(self, context):
    with open(script_folder/('text/available_factions.json'), 'r') as import_factions_input:
        factions = json.load(import_factions_input)
    faction_list = [('all', 'All', "")]
    for faction in factions:
        entry = (factions[faction], faction, "")
        faction_list.append(entry)
    return(faction_list)


def countModels():
    with open(script_folder/('text/model_dictionary.json'), 'r') as import_bmdb_input:
        bmdb_dictionary = json.load(import_bmdb_input)
    return(len(bmdb_dictionary))


def sortModels(self, context):
    with open(script_folder/('text/model_dictionary.json'), 'r') as import_bmdb_input:
        bmdb_dictionary = json.load(import_bmdb_input)
    import_faction = context.scene.med2_toolkit_bmdb_data.filter_faction
    context.scene.med2_toolkit_bmdb_list.clear()
    context.scene.med2_toolkit_bmdb_list_index = 0
    for model in bmdb_dictionary:
        if import_faction == 'all':
            item = bpy.context.scene.med2_toolkit_bmdb_list.add()
            item.name = model
            item.folder = bmdb_dictionary[model]['Folder']
            item.bmdb_info = json.dumps(bmdb_dictionary[model])
        elif import_faction in bmdb_dictionary[model]['Textures']:
            item = bpy.context.scene.med2_toolkit_bmdb_list.add()
            item.name = model
            item.folder = bmdb_dictionary[model]['Folder']
            item.bmdb_info = json.dumps(bmdb_dictionary[model])
    return{'FINISHED'}


# Blender only keeps pointers to the strings an EnumProperty items callback
# returns, so the list has to stay referenced until the next query or the
# entries render blank. Same workaround as the EDU panel's faction/unit enums.
_model_faction_items = []

def modelFactions(self, context):
    """Texture variants of the selected model, one entry per faction. Factions
    whose textures are identical to an earlier faction's are labelled
    "Faction (Same as Other)" so the genuinely unique variants stand out."""
    global _model_faction_items
    with open(script_folder/('text/available_factions.json'), 'r') as import_factions_input:
        factions_named = json.load(import_factions_input)
    with open(script_folder/('text/model_dictionary.json'), 'r') as import_bmdb_input:
        bmdb_dictionary = json.load(import_bmdb_input)
    # available_factions.json maps display name -> codename; invert it once
    # instead of scanning it per faction (and never fall through to the
    # previous loop's entry when a codename is missing from it)
    faction_names = {code: name for name, code in factions_named.items()}
    factions = []
    model = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].name
    model_textures = bmdb_dictionary[model]['Textures']
    first_use = {}
    for faction in model_textures:
        faction_name = faction_names.get(faction, faction)
        fingerprint = tuple(model_textures[faction])
        original = first_use.get(fingerprint)
        if original is None:
            first_use[fingerprint] = faction_name
            label = faction_name
            description = ", ".join(model_textures[faction])
        else:
            label = "%s (Same as %s)" % (faction_name, original)
            description = "Uses the same textures as %s: %s" % (original, ", ".join(model_textures[faction]))
        factions.append((faction, label, description))
    _model_faction_items = factions
    return(_model_faction_items)


class MED_2_TOOLKIT_OT_Model_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.model_importer"
    bl_label = "Import model"
    bl_description = "Import the selected model with the chosen textures."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
            bmdb_dictionary = json.load(bmdb_input)
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].factions
        model = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].name
        model_info = json.loads(context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].bmdb_info)
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unitTaskWriter()
        fileChecker(model_folder, [model])
        existing = set(bpy.data.objects)
        result, width, z_offset = modelImporter(model_folder, model, faction, model_info, model)
        if result != 0:
            imported = importedArmature(existing)
            if imported:
                imported.location = coordinates
                imported.location[2] += z_offset
        postImport(self, context)
        return{"FINISHED"}


class MED_2_TOOLKIT_BMDB_data(bpy.types.PropertyGroup):
    filter_faction: EnumProperty(name = "Faction list", description = "Factions found in descr_sm_factions", items = sortFactions)


class MED_2_TOOLKIT_PT_BMDB_Import(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_BMDB_Import"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "BMDB"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    # bl_options = {"HIDE_HEADER"}

    @classmethod
    def poll(cls, context):
        if (context.scene.med2_toolkit_mode.mode_selection != 'unit_import'):
            return False
        return True

    def draw(self, context):
        layout=self.layout
        box = layout.box()
        box.label(text = "Models found: {}".format(countModels()))
        row = box.row(align=True)
        row.prop (context.scene.med2_toolkit_bmdb_data, "filter_faction", text="Filter by faction")
        row.operator("medieval2toolkit.bmdb_filter", icon = "FILE_REFRESH", text = "")
        row = layout.row(align=True)
        row.template_list("MED_2_TOOLKIT_UL_BMDB_List", "BMDB_list", context.scene, "med2_toolkit_bmdb_list", context.scene, "med2_toolkit_bmdb_list_index")
        if context.scene.med2_toolkit_bmdb_list_index >= 0 and context.scene.med2_toolkit_bmdb_list:
            model = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index]
            col = layout.column()
            col.prop (model, "name")
            col.prop (model, "factions")
            col.operator("medieval2toolkit.model_importer", text="Import model")
            col.operator("medieval2toolkit.model_folder", text="Open model folder")
        if(context.mode != 'OBJECT'):
            layout.enabled = False


class MED2_TOOLKIT_OT_BMDB_Filter(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_filter"
    bl_label = "Filter Battlemodels_DB"
    bl_description = "Filter models by factions that have textures assigned."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        sortModels(self, context)
        return{"FINISHED"}


class MED2_TOOLKIT_OT_Model_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.model_folder"
    bl_label = "Open model folder"
    bl_description = "Opens the model folder in the file explorer"
    def execute(self, context):
        with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
            bmdb_dictionary = json.load(bmdb_input)
        mod_path = bpy.context.scene.med2_toolkit_reader.directory_mod_data
        model_name = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].name
        model_mesh = bmdb_dictionary[model_name]['Mesh'].replace('.glb', '.mesh')
        model_path = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].folder
        target_file = os.path.join(mod_path, model_path, model_mesh)
        subprocess.run(r'explorer /select, "'+str(Path(target_file))+'"')
        return{"FINISHED"}


class MED_2_TOOLKIT_BMDB_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="ID", description="ID of the unit")
    folder: StringProperty(name="Folder", description="Location of the model")
    factions: EnumProperty(name = "Texture variant", description = "List of factions with textures assigned", items = modelFactions)
    bmdb_info: StringProperty(name="Model info", description="Information about the model, such as mesh name and texture variants")


class MED_2_TOOLKIT_UL_BMDB_List(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text = "")


classes = [
    MED_2_TOOLKIT_OT_Model_Importer,
    MED_2_TOOLKIT_BMDB_data,
    MED2_TOOLKIT_OT_BMDB_Filter,
    MED2_TOOLKIT_OT_Model_Folder,
    MED_2_TOOLKIT_BMDB_List_Items,
    MED_2_TOOLKIT_UL_BMDB_List,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_bmdb_data = PointerProperty(type=MED_2_TOOLKIT_BMDB_data)
    bpy.types.Scene.med2_toolkit_bmdb_list = CollectionProperty(type = MED_2_TOOLKIT_BMDB_List_Items)
    bpy.types.Scene.med2_toolkit_bmdb_list_index = IntProperty(name = "Index of imported units", default = 0)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_bmdb_data
    del bpy.types.Scene.med2_toolkit_bmdb_list
    del bpy.types.Scene.med2_toolkit_bmdb_list_index