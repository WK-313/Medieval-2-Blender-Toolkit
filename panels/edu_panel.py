import bpy
import json
from bpy.props import StringProperty, BoolProperty, BoolVectorProperty, PointerProperty, CollectionProperty, IntProperty, EnumProperty
from pathlib import Path

from..directories import saveFolderPaths, saveSettings, readJsonCached
from ..tasks.importer import unitChecker, fileChecker, unitImporter, modelImporter, importedArmature, hideVariations, postImport
from ..tasks.task_writer import unitTaskWriter, engineTaskWriter


script_folder = Path(__file__).parent.parent

# Blender keeps only pointers - not Python references - to the strings an
# EnumProperty items callback returns, so once Python garbage-collects them the
# dropdown renders blank/greyed entries (it shows up as a couple of random units
# going grey on long faction lists). Hold the last-returned items alive so the
# strings survive until the next query. This is the documented workaround in the
# EnumProperty "There is a known bug with using a callback" note.
_faction_enum_items = []
_unit_enum_items = []

def sortFactions(self, context):
    global _faction_enum_items
    factions = readJsonCached(script_folder/('text/available_factions.json'))
    faction_list = []
    for faction in factions:
        entry = (factions[faction], faction, "")
        faction_list.append(entry)
    _faction_enum_items = faction_list
    return _faction_enum_items

def sortUnits(self, context):
    global _unit_enum_items
    unit_dictionary = readJsonCached(script_folder/('text/unit_dictionary.json'))
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
        faction_units = [('none','None','')]
    _unit_enum_items = faction_units
    return _unit_enum_items

# Armour upgrade slots the unit importer offers as tick boxes. The EDU allows
# levels 0-3, so four bools cover every unit in the dictionary; anything beyond
# that is simply not offered.
UPGRADE_SLOTS = 4

# Vertical clearance between a unit's stacked armour upgrades on Z. Models
# don't report their own height (selectionBoundingBox only returns width and
# the bottom z_offset), so this is a flat guess rather than a measured gap.
UPGRADE_Z_STEP = 2.5

def upgradeModels(context):
    """Model IDs of the selected unit, one per armour upgrade level."""
    if context.scene.med2_toolkit_units.import_unit == 'none':
        return []
    try:
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
    except ValueError:
        return []
    return unit_info['Model'][:UPGRADE_SLOTS]


def selectedUpgrades(context):
    """Ticked armour upgrade levels that the selected unit actually has."""
    upgrades = context.scene.med2_toolkit_units.single_import_upgrades
    return [index for index in range(len(upgradeModels(context))) if upgrades[index]]


def deleteImportedObjects(item):
    """Delete the rig an import list entry points at, plus everything parented
    to it. Returns the number of objects removed."""
    target = bpy.data.objects.get(item.object_name) if item.object_name else None
    if target is None:
        # entries imported before object_name existed, and any rig that was
        # never renamed, still match on the list name
        target = bpy.data.objects.get(item.name)
    if target is None:
        return 0
    doomed = list(target.children_recursive) + [target]
    removed = 0
    for obj in doomed:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except (ReferenceError, RuntimeError):
            pass
    return removed


class MED_2_TOOLKIT_Unit_data(bpy.types.PropertyGroup):
    with open(script_folder/('text/menu_settings.json'), 'r') as settings_input:
            bool_settings = json.load(settings_input)
    single_import_upgrades: BoolVectorProperty(name = "Upgrade levels", description = "Armour upgrade levels to import", size = UPGRADE_SLOTS, default = (True,) + (False,)*(UPGRADE_SLOTS-1))
    delete_with_item: BoolProperty(name = "Delete objects", description = "Also delete the armature and every object parented to it when removing entries from the imported models list", default = bool_settings.get('delete_with_item', True))
    import_faction: EnumProperty(name = "Faction list", description = "List of factions", items = sortFactions)
    import_unit: EnumProperty(name = "Unit list", description = "List of units in faction", items = sortUnits)
    import_filter: EnumProperty(name = "Ownership filter", description = "Unit ownership filter", items = [('ownership','Ownership',''),('era 0','Era 0',''),('era 1','Era 1',''),('era 2','Era 2','')], default = 1)
    faction_import_officers: BoolProperty(name = "Import Officers", description = "Also import each unit's officers, placed behind it on the -Y axis", default = False)
    use_existing: BoolProperty(name = "Use existing", description = "Toggle between using existing .GLB files or always converting from .mesh", default =  bool_settings['use_existing'])
    hide_toggle: BoolProperty(name = "Hide variations", description = "Toggle to automatically hide model variations when importing units", default = bool_settings['hide_toggle'])
    frame_toggle: BoolProperty(name = "Frame models", description = "Toggle to automatically focus the view on imported models", default = bool_settings['frame_toggle'])
    textured_toggle: BoolProperty(name = "Display textures", description = "Toggle to automatically change to solid texture mode", default = bool_settings['textured_toggle'])
    primary_secondary: EnumProperty(name = "Skeleton type", description = "Choose which skeleton to use when converting", items = [('primary','Primary',''),('secondary','Secondary','')])


class MED_2_TOOLKIT_OT_Unit_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.unit_importer"
    bl_label = "Import unit"
    bl_description = "Import the ticked armour upgrades of the selected unit."
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        upgrades = selectedUpgrades(context)
        if not upgrades:
            self.report({'ERROR'}, "Tick at least one upgrade level to import")
            return{"CANCELLED"}
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        # first ticked upgrade sits at the origin, the rest march out along +X
        # using the same half-width spacing as Import Full Unit
        coordinates = [0, 0, 0]
        saveFolderPaths()
        saveSettings()
        unitTaskWriter()
        engineTaskWriter()
        for upgrade in upgrades:
            unitChecker(model_folder, [unit_info], upgrade)
            offset = unitImporter(model_folder, unit_info, faction, coordinates, upgrade)
            coordinates[0] += round(offset*0.5, 1) + 0.25
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
            existing = set(bpy.data.objects)
            result, width, z_offset = modelImporter(model_folder, officer, faction, model_info, officer)
            if result != 0:
                imported = importedArmature(existing)
                if imported:
                    imported.location = coordinates
                    imported.location[2] += z_offset
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
            existing = set(bpy.data.objects)
            result, width, z_offset = modelImporter(model_folder, officer, faction, model_info, officer)
            if result != 0:
                imported = importedArmature(existing)
                if imported:
                    imported.location = coordinates
                    imported.location[2] += z_offset
            coordinates[1] -= round(offset*0.5, 1)*2
        if context.scene.med2_toolkit_units.hide_toggle:
            hideVariations()
        postImport(self, context)
        return{"FINISHED"}

class MED_2_TOOLKIT_OT_Faction_Importer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.faction_importer"
    bl_label = "Import faction"
    bl_description = ("Import all units of the selected faction according to the ownership, "
                      "with every armour upgrade stacked on Z. Optionally also import each "
                      "unit's officers, placed behind it on -Y.")
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        faction = context.scene.med2_toolkit_units.import_faction
        import_officers = context.scene.med2_toolkit_units.faction_import_officers
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

        if import_officers:
            with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
                bmdb_dictionary = json.load(bmdb_input)

        for unit_info in unit_info_list:
            unit_x = coordinates[0]
            unit_width = 0
            for level in range(len(unit_info['Model'])):
                unitChecker(model_folder, [unit_info], level)
                # apply_offset=False: every upgrade of this unit shares unit_x,
                # only stacking upward on Z, so the auto x-spacing must stay off
                upgrade_coordinates = [unit_x, 0, level * UPGRADE_Z_STEP]
                offset = unitImporter(model_folder, unit_info, faction, upgrade_coordinates, level, apply_offset=False)
                unit_width = max(unit_width, offset)
            coordinates[0] = unit_x + round(unit_width*0.5, 1) + 0.25

            if import_officers:
                officers = unit_info['Officers']
                fileChecker(model_folder, officers)
                officer_coordinates = [unit_x, 0, 0]
                for officer in officers:
                    model_info = bmdb_dictionary[officer]
                    existing = set(bpy.data.objects)
                    result, width, z_offset = modelImporter(model_folder, officer, faction, model_info, officer)
                    if result != 0:
                        imported = importedArmature(existing)
                        if imported:
                            imported.location = officer_coordinates
                            imported.location[2] += z_offset
                    officer_coordinates[1] -= 2

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
    bl_description = "Remove the selected item from the list, and its objects when Delete objects is ticked."
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_import_list
    def execute(self, context):
        imported_list = context.scene.med2_toolkit_import_list
        imported_list_index = context.scene.med2_toolkit_import_list_index
        removed = 0
        if context.scene.med2_toolkit_units.delete_with_item:
            removed = deleteImportedObjects(imported_list[imported_list_index])
        imported_list.remove(imported_list_index)
        context.scene.med2_toolkit_import_list_index = min(max(0, imported_list_index - 1), len(imported_list) -1)
        if context.scene.med2_toolkit_units.delete_with_item:
            self.report({'INFO'}, "Removed item and deleted %d object(s)" % removed)
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Purge_List(bpy.types.Operator):
    bl_idname = "medieval2toolkit.purge_list"
    bl_label = "Purge list"
    bl_description = "Remove all items from the list, and their objects when Delete objects is ticked."
    bl_options = {"REGISTER", "UNDO"}
    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_import_list
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        imported_list = context.scene.med2_toolkit_import_list
        removed = 0
        if context.scene.med2_toolkit_units.delete_with_item:
            for item in imported_list:
                removed += deleteImportedObjects(item)
        imported_list.clear()
        context.scene.med2_toolkit_import_list_index = 0
        if context.scene.med2_toolkit_units.delete_with_item:
            self.report({'INFO'}, "Purged list and deleted %d object(s)" % removed)
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
        upgrade_models = upgradeModels(context)
        if upgrade_models:
            box = layout.box()
            box.label(text="Upgrade levels:")
            grid = box.column(align=True)
            for index, model_id in enumerate(upgrade_models):
                entry = grid.row(align=True)
                entry.prop (context.scene.med2_toolkit_units, "single_import_upgrades", index=index, text=str(index))
                entry.label(text=model_id)
        col = layout.column(align=True)
        col.operator("medieval2toolkit.unit_importer", text="Import unit")
        col.operator("medieval2toolkit.officer_importer", text="Import officers")
        col.operator("medieval2toolkit.full_unit_importer", text="Import Full Unit")
        if context.scene.med2_toolkit_units.import_unit == 'none':
            col.enabled = False
        col = layout.column(align=True)
        col.prop (context.scene.med2_toolkit_units, "faction_import_officers", text="Import Officers")
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
        layout.prop (context.scene.med2_toolkit_units, "delete_with_item", text="Delete objects with the entry")
        row = layout.row(align=True)
        row.operator("medieval2toolkit.remove_item", text="Remove item")
        row.operator("medieval2toolkit.purge_list", text="Purge list")
        if(context.mode != 'OBJECT'):
            layout.enabled = False

class MED_2_TOOLKIT_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Names of the imported units")
    id: StringProperty(name="Unit ID", description="IDs of the imported units")
    object_name: StringProperty(name="Object name", description="Name of the armature object this entry was imported as")
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