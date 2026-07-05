import bpy
import json
from bpy.props import StringProperty, BoolProperty, PointerProperty, CollectionProperty, IntProperty, EnumProperty
from pathlib import Path

from..directories import saveFolderPaths, saveSettings
from ..tasks.importer import unitChecker, fileChecker, unitImporter, modelImporter, hideVariations, postImport
from ..tasks.task_writer import unitTaskWriter, engineTaskWriter


script_folder = Path(__file__).parent.parent

def sortFactions(self, context):
    with open(script_folder/('text/available_factions.json'), 'r') as import_factions_input:
        factions = json.load(import_factions_input)
    faction_list = []
    for faction in factions:
        entry = (factions[faction], faction, "")
        faction_list.append(entry)
    return(faction_list)

def sortUnits(self, context):
    with open(script_folder/('text/unit_dictionary.json'), 'r') as import_unit_input:
        unit_dictionary = json.load(import_unit_input)
    import_faction = context.scene.med2_toolkit_units.import_faction
    filter = context.scene.med2_toolkit_units.import_filter
    faction_units = []
    for unit in unit_dictionary:
        if not import_faction in unit_dictionary[unit]['Owners'][filter]:
            continue
        unit_info = json.dumps(unit_dictionary[unit])
        entry = (unit_info, unit, "")
        faction_units.append(entry)
    if len(faction_units) == 0:
         return [('none','None','')]
    return(faction_units)

def sortUpgrades(self, context):
    unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
    upgrade_models = []
    for upgrade in unit_info['Model']:
        upgrade_models.append(upgrade)
    try:
        upgrade = upgrade_models[context.scene.med2_toolkit_units.single_import_upgrade]
    except IndexError:
        upgrade = upgrade_models[-1]
    return(upgrade)


class MED_2_TOOLKIT_Unit_data(bpy.types.PropertyGroup):
    with open(script_folder/('text/menu_settings.json'), 'r') as settings_input:
            bool_settings = json.load(settings_input)
    single_import_upgrade: IntProperty(name = "Upgrade level", description = "Number of units armour upgrades", default = 0, min = 0, soft_max = 3)
    import_faction: EnumProperty(name = "Faction list", description = "List of factions", items = sortFactions)
    import_unit: EnumProperty(name = "Unit list", description = "List of units in faction", items = sortUnits)
    import_filter: EnumProperty(name = "Ownership filter", description = "Unit ownership filter", items = [('ownership','Ownership',''),('era 0','Era 0',''),('era 1','Era 1',''),('era 2','Era 2','')], default = 1)
    import_upgrade: IntProperty(name = "Armour upgrade", description = "Armour upgrade level", default = 0, min = 0, max = 3)
    use_existing: BoolProperty(name = "Use existing", description = "Toggle between using existing .GLB files or always converting from .mesh", default =  bool_settings['use_existing'])
    hide_toggle: BoolProperty(name = "Hide variations", description = "Toggle to automatically hide model variations when importing units", default = bool_settings['hide_toggle'])
    frame_toggle: BoolProperty(name = "Frame models", description = "Toggle to automatically focus the view on imported models", default = bool_settings['frame_toggle'])
    textured_toggle: BoolProperty(name = "Display textures", description = "Toggle to automatically change to solid texture mode", default = bool_settings['textured_toggle'])
    primary_secondary: EnumProperty(name = "Skeleton type", description = "Choose which skeleton to use when converting", items = [('primary','Primary',''),('secondary','Secondary','')])


class MED_2_TOOLKIT_OT_Unit_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.unit_importer"
    bl_label = "Import unit"
    bl_description = "Import the selected armour upgrade of the selected unit."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        upgrade = context.scene.med2_toolkit_units.single_import_upgrade
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unitTaskWriter()
        engineTaskWriter()
        unitChecker(model_folder, [unit_info], upgrade)
        unitImporter(model_folder, unit_info, faction, coordinates, upgrade)
        postImport(self, context)
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Officer_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.officer_importer"
    bl_label = "Import officer"
    bl_description = "Import the officers of the selected unit."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
            bmdb_dictionary = json.load(bmdb_input)

        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        officers = unit_info['Officers']
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unitTaskWriter()
        engineTaskWriter()
        fileChecker(model_folder, officers)
        for officer in officers:
            model_info = bmdb_dictionary[officer]
            modelImporter(model_folder, officer, faction, coordinates, model_info, officer)
            coordinates[1] -= 2
        postImport(self, context)
        return{"FINISHED"}

class MED_2_TOOLKIT_OT_Import_Full_Unit(bpy.types.Operator):
    bl_idname = "medieval2toolkit.full_unit_importer"
    bl_label = "Import full unit"
    bl_description = "Import the selected unit with all its officers and variations."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        upgrades = unit_info['Model']
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unitTaskWriter()
        engineTaskWriter()
        for upgrade in range(len(upgrades)):
            unitChecker(model_folder, [unit_info], upgrade)
            offset = unitImporter(model_folder, unit_info, faction, coordinates, upgrade)
            coordinates[0] += round(offset*0.5, 1) + 0.25

        with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
            bmdb_dictionary = json.load(bmdb_input)
        officers = unit_info['Officers']
        coordinates = [0, -round(offset*0.5, 1)*2, 0]
        fileChecker(model_folder, officers)
        for officer in officers:
            model_info = bmdb_dictionary[officer]
            modelImporter(model_folder, officer, faction, coordinates, model_info, officer)
            coordinates[1] -= round(offset*0.5, 1)*2
        if context.scene.med2_toolkit_units.hide_toggle:
            hideVariations()
        postImport(self, context)
        return{"FINISHED"}

class MED_2_TOOLKIT_OT_Faction_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.faction_importer"
    bl_label = "Import faction"
    bl_description = "Import all units of the selected faction according to the ownership."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        upgrade = context.scene.med2_toolkit_units.import_upgrade
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unit_list = sortUnits(self, context)
        unit_info_list = []
        for unit in unit_list:
            unit_info = json.loads(unit[0])
            unit_info_list.append(unit_info)
        unitTaskWriter()
        engineTaskWriter()
        unitChecker(model_folder, unit_info_list, upgrade)
        for unit_info in unit_info_list:
            offset = unitImporter(model_folder, unit_info, faction, coordinates, upgrade)
            coordinates[0] += round(offset*0.5, 1) + 0.25
        postImport(self, context)
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Variations(bpy.types.Operator):
    bl_idname = "medieval2toolkit.variations"
    bl_label = "Reroll variations"
    bl_description = "Automatically hide variations and randomise appearance."
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        if len(context.selected_objects) == 0: return False
        return context.object.select_get() and context.object.type == 'ARMATURE'
    def execute(self, context):
        hideVariations()
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Remove_Item(bpy.types.Operator):
    bl_idname = "medieval2toolkit.remove_item"
    bl_label = "Remove item"
    bl_description = "Remove the selected item from the list."
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_import_list
    def execute(self, context):
        imported_list = context.scene.med2_toolkit_import_list
        imported_list_index = context.scene.med2_toolkit_import_list_index
        imported_list.remove(imported_list_index)
        context.scene.med2_toolkit_import_list_index = min(max(0, imported_list_index - 1), len(imported_list) -1)
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Purge_List(bpy.types.Operator):
    bl_idname = "medieval2toolkit.purge_list"
    bl_label = "Purge list"
    bl_description = "Remove all items from the list."
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_import_list
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        imported_list = context.scene.med2_toolkit_import_list
        imported_list.clear()
        context.scene.med2_toolkit_import_list_index = 0
        return{"FINISHED"}




class MED_2_TOOLKIT_PT_EDU_Import(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_EDU_Import"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "EDU"
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
        col = box.column(align=True)
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.prop (context.scene.med2_toolkit_units, "hide_toggle", text="Hide variations:", toggle = 1)
        grid.prop (context.scene.med2_toolkit_units, "use_existing", text="Use existing:", toggle = 1)
        grid.prop (context.scene.med2_toolkit_units, "frame_toggle", text="Frame imported:", toggle = 1)
        grid.prop (context.scene.med2_toolkit_units, "textured_toggle", text="Solid textured:", toggle = 1)
        col = layout.column(align=True)
        col.prop (context.scene.med2_toolkit_units, "import_faction", text="Faction")
        col.prop (context.scene.med2_toolkit_units, "import_filter", text="Filter")
        col.prop (context.scene.med2_toolkit_units, "import_unit", text="Unit")
        col.prop (context.scene.med2_toolkit_units, "primary_secondary", text="Skeleton")
        row = col.row()
        if context.scene.med2_toolkit_units.import_unit != 'none':
            row.prop (context.scene.med2_toolkit_units, "single_import_upgrade", text="Upgrade level:")
            row.label(text=sortUpgrades(self, context))
        col = layout.column(align=True)
        col.operator("medieval2toolkit.unit_importer", text="Import unit")
        col.operator("medieval2toolkit.officer_importer", text="Import officers")
        col.operator("medieval2toolkit.full_unit_importer", text="Import Full Unit")
        if context.scene.med2_toolkit_units.import_unit == 'none':
            row.enabled = False
            col.enabled = False
        col = layout.column(align=True)
        col.prop (context.scene.med2_toolkit_units, "import_upgrade", text="Upgrade level:")
        col.operator("medieval2toolkit.faction_importer", text="Import faction")
        col = layout.column(align=True)
        col.operator("medieval2toolkit.variations", text="Shuffle variations")
        layout.label(text = "Imported Models")
        row = layout.row()
        row.template_list("MED_2_TOOLKIT_UL_Import_List", "Import_list", context.scene, "med2_toolkit_import_list", context.scene, "med2_toolkit_import_list_index")
        if context.scene.med2_toolkit_import_list_index >= 0 and context.scene.med2_toolkit_import_list:
            unit = context.scene.med2_toolkit_import_list[context.scene.med2_toolkit_import_list_index]
            col = layout.column()
            col.prop (unit, "id")
        row = layout.row(align=True)
        row.operator("medieval2toolkit.remove_item", text="Remove item")
        row.operator("medieval2toolkit.purge_list", text="Purge list")
        if(context.mode != 'OBJECT'):
            layout.enabled = False

class MED_2_TOOLKIT_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Names of the imported units")
    id: StringProperty(name="Unit ID", description="IDs of the imported units")
    icon: StringProperty(name="Menu icon", description="")

class MED_2_TOOLKIT_UL_Import_List(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        unit_type = 'ARMATURE_DATA'
        if item.icon == 'mount':
            unit_type = 'SNAP_OFF'
        elif item.icon == 'engine':
            unit_type = 'MOD_TINT'
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name, icon = unit_type)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text = "")

classes = [
    MED_2_TOOLKIT_Unit_data,
    MED_2_TOOLKIT_OT_Unit_Importer,
    MED_2_TOOLKIT_OT_Officer_Importer,
    MED_2_TOOLKIT_OT_Import_Full_Unit,
    MED_2_TOOLKIT_OT_Faction_Importer,
    MED_2_TOOLKIT_OT_Variations,
    MED_2_TOOLKIT_OT_Remove_Item,
    MED_2_TOOLKIT_OT_Purge_List,
    MED_2_TOOLKIT_PT_EDU_Import,
    MED_2_TOOLKIT_List_Items,
    MED_2_TOOLKIT_UL_Import_List,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_units = PointerProperty(type=MED_2_TOOLKIT_Unit_data)
    bpy.types.Scene.med2_toolkit_import_list = CollectionProperty(type = MED_2_TOOLKIT_List_Items)
    bpy.types.Scene.med2_toolkit_import_list_index = IntProperty(name = "Index of imported units", default = 0)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_units
    del bpy.types.Scene.med2_toolkit_import_list
    del bpy.types.Scene.med2_toolkit_import_list_index