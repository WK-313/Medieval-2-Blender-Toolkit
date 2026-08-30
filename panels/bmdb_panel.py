import bpy
import os
import json
from pathlib import Path
from..directories import saveFolderPaths, saveSettings, readJsonCached
from ..tasks.task_writer import unitTaskWriter
from ..tasks.importer import fileChecker, modelImporter, importedArmature, postImport
from ..tasks.unit_exporter import reveal_file
from bpy.props import StringProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty

script_folder = Path(__file__).parent.parent

MODEL_DICTIONARY = script_folder/'text'/'model_dictionary.json'
AVAILABLE_FACTIONS = script_folder/'text'/'available_factions.json'

def modelDictionaryVersion():
    """mtime of model_dictionary.json, so caches drop when Read Mod Data runs."""
    try:
        return os.path.getmtime(MODEL_DICTIONARY)
    except OSError:
        return None


# Blender only keeps pointers to the strings an EnumProperty items callback
# returns, so the list has to stay referenced until the next query or the
# entries render blank. Same workaround as the EDU panel's faction/unit enums.
_filter_faction_items = []

def sortFactions(self, context):
    global _filter_faction_items
    factions = readJsonCached(AVAILABLE_FACTIONS)
    faction_list = [('all', 'All', "")]
    for faction in factions:
        entry = (factions[faction], faction, "")
        faction_list.append(entry)
    _filter_faction_items = faction_list
    return(_filter_faction_items)


def countModels():
    return(len(readJsonCached(MODEL_DICTIONARY)))


def sortModels(self, context):
    bmdb_dictionary = readJsonCached(MODEL_DICTIONARY)
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
    snapToSearch(self, context)
    return{'FINISHED'}


def searchTerms(text):
    """The search box split into terms. Every term has to appear somewhere in
    the name, so "eng knight" finds ug_english_knight."""
    return [term for term in text.lower().split() if term]


def modelMatches(name, terms):
    lowered = name.lower()
    return all(term in lowered for term in terms)


def snapToSearch(self, context):
    """Move the selection onto the first model the search matches.

    The search filters the UIList rather than rebuilding the collection - with
    a few thousand models, rebuilding on every keystroke is not something the
    panel can keep up with - so the list index has to be walked onto a visible
    row itself, or the details and Import button below the list would go on
    describing a model the filter has hidden. Called on every keystroke and
    again after a rebuild, which parks the index on row 0 regardless."""
    terms = searchTerms(context.scene.med2_toolkit_bmdb_data.search)
    if not terms:
        return
    models = context.scene.med2_toolkit_bmdb_list
    index = context.scene.med2_toolkit_bmdb_list_index
    if 0 <= index < len(models) and modelMatches(models[index].name, terms):
        return
    for position, model in enumerate(models):
        if modelMatches(model.name, terms):
            context.scene.med2_toolkit_bmdb_list_index = position
            return


# Same GC guard as above, plus a cache keyed by the selected model: this
# callback runs several times per redraw, and scrolling the model list redraws
# on every event, so rebuilding the variant labels each time lags the panel.
_model_faction_items = []
_model_faction_cache = {'key': None}

def modelFactions(self, context):
    """Texture variants of the selected model, one entry per faction. Factions
    whose textures are identical to an earlier faction's are labelled
    "Faction (Same as Other)" so the genuinely unique variants stand out."""
    global _model_faction_items
    model = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].name
    key = (modelDictionaryVersion(), model)
    if _model_faction_cache['key'] == key:
        return _model_faction_items
    factions_named = readJsonCached(AVAILABLE_FACTIONS)
    bmdb_dictionary = readJsonCached(MODEL_DICTIONARY)
    # available_factions.json maps display name -> codename; invert it once
    # instead of scanning it per faction (and never fall through to the
    # previous loop's entry when a codename is missing from it)
    faction_names = {code: name for name, code in factions_named.items()}
    factions = []
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
    _model_faction_cache['key'] = key
    return(_model_faction_items)


class MED_2_TOOLKIT_OT_Model_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.model_importer"
    bl_label = "Import model"
    bl_description = "Import the selected model with the chosen textures."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
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
    # TEXTEDIT_UPDATE applies the value on every keystroke instead of waiting
    # for Return, which is what makes the list narrow as you type
    search: StringProperty(name = "Search", description = "Show only models whose name contains what you type. Several words all have to match, in any order, so \"eng knight\" finds ug_english_knight", default = "", options = {'TEXTEDIT_UPDATE'}, update = snapToSearch)


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
        search = context.scene.med2_toolkit_bmdb_data.search
        row = layout.row(align=True)
        row.prop (context.scene.med2_toolkit_bmdb_data, "search", text="", icon="VIEWZOOM")
        if search:
            row.operator("medieval2toolkit.bmdb_clear_search", icon = "X", text = "")
            terms = searchTerms(search)
            shown = sum(1 for model in context.scene.med2_toolkit_bmdb_list if modelMatches(model.name, terms))
            layout.label(text="%d of %d models match" % (shown, len(context.scene.med2_toolkit_bmdb_list)),
                         icon='CHECKMARK' if shown else 'ERROR')
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


class MED2_TOOLKIT_OT_BMDB_Clear_Search(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_clear_search"
    bl_label = "Clear Search"
    bl_description = "Empty the search box and show every model again"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.med2_toolkit_bmdb_data.search = ""
        return{"FINISHED"}


class MED2_TOOLKIT_OT_Model_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.model_folder"
    bl_label = "Open model folder"
    bl_description = "Opens the model folder in the file explorer"
    def execute(self, context):
        bmdb_dictionary = readJsonCached(MODEL_DICTIONARY)
        mod_path = bpy.context.scene.med2_toolkit_reader.directory_mod_data
        model_name = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].name
        model_mesh = bmdb_dictionary[model_name]['Mesh'].replace('.glb', '.mesh')
        model_path = context.scene.med2_toolkit_bmdb_list[context.scene.med2_toolkit_bmdb_list_index].folder
        target_file = os.path.join(mod_path, model_path, model_mesh)
        reveal_file(target_file)
        return{"FINISHED"}


class MED_2_TOOLKIT_BMDB_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="ID", description="ID of the unit")
    folder: StringProperty(name="Folder", description="Location of the model")
    factions: EnumProperty(name = "Texture variant", description = "List of factions with textures assigned", items = modelFactions)
    bmdb_info: StringProperty(name="Model info", description="Information about the model, such as mesh name and texture variants")


class MED_2_TOOLKIT_UL_BMDB_List(bpy.types.UIList):
    def filter_items(self, context, data, property):
        """Hide the rows the search box does not match. Returning empty lists
        means "no filtering, no reordering", which is the untouched list."""
        terms = searchTerms(context.scene.med2_toolkit_bmdb_data.search)
        if not terms:
            return [], []
        models = getattr(data, property)
        return [self.bitflag_filter_item if modelMatches(model.name, terms) else 0
                for model in models], []

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
    MED2_TOOLKIT_OT_BMDB_Clear_Search,
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