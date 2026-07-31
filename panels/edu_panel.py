import bpy
import json
from bpy.app.handlers import persistent
from bpy.props import StringProperty, BoolProperty, BoolVectorProperty, PointerProperty, CollectionProperty, IntProperty, EnumProperty
from pathlib import Path

from..directories import saveFolderPaths, saveSettings, readJsonCached
from ..tasks.control_rig import controlRigOf, controlledRigs, isControlRig
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
    # the unit is parented UNDER its control rig, so deleting the unit would
    # otherwise strand the controller in the scene
    controller = controlRigOf(target)
    if controller is not None and controller is not target:
        if all(rig in doomed for rig in controlledRigs(controller)):
            doomed.append(controller)
    removed = 0
    for obj in doomed:
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
            removed += 1
        except (ReferenceError, RuntimeError):
            pass
    return removed


#   ---------------------------  #
#   Imported models list upkeep    #
#   ---------------------------  #

# Set while the deferred prune is queued, so the depsgraph handler does not
# stack one timer per update.
_prune_queued = False


def staleEntries(scene):
    """Indices of list entries whose object is no longer in the file.

    Only a full disappearance from bpy.data counts: an object merely unlinked
    from the scene, or sitting in an excluded collection, is still there and its
    entry has to stay.
    """
    stale = []
    for index, item in enumerate(scene.med2_toolkit_import_list):
        name = item.object_name or item.name
        if name and bpy.data.objects.get(name) is None:
            stale.append(index)
    return stale


def pruneImportList(scene):
    """Drop entries for deleted objects. Returns how many went."""
    stale = staleEntries(scene)
    for index in reversed(stale):
        scene.med2_toolkit_import_list.remove(index)
    if stale:
        scene.med2_toolkit_import_list_index = min(scene.med2_toolkit_import_list_index,
                                                   max(0, len(scene.med2_toolkit_import_list) - 1))
    return len(stale)


def runQueuedPrune():
    global _prune_queued
    _prune_queued = False
    for scene in bpy.data.scenes:
        units = getattr(scene, "med2_toolkit_units", None)
        if units is None or not units.auto_prune_list:
            continue
        removed = pruneImportList(scene)
        if removed:
            print("Medieval 2 Toolkit: dropped %d imported models entr%s whose object was deleted"
                  % (removed, "y" if removed == 1 else "ies"))
    return None


@persistent
def watchImportList(scene, depsgraph=None):
    """Queue a prune when an entry's object has gone.

    The check itself is a dict lookup per entry and runs on every depsgraph
    update, so the common case (nothing stale) costs nothing. The removal is
    deferred to a timer because writing scene data from inside
    depsgraph_update_post retriggers the handler.
    """
    global _prune_queued
    if _prune_queued or scene is None:
        return
    units = getattr(scene, "med2_toolkit_units", None)
    if units is None or not units.auto_prune_list:
        return
    if not scene.med2_toolkit_import_list or not staleEntries(scene):
        return
    _prune_queued = True
    bpy.app.timers.register(runQueuedPrune, first_interval=0)


@persistent
def pruneAfterLoad(_file_path):
    # a saved file can carry entries for objects that were deleted in a session
    # that never ran the handler (or with the toggle off at the time)
    runQueuedPrune()


class MED_2_TOOLKIT_Unit_data(bpy.types.PropertyGroup):
    with open(script_folder/('text/menu_settings.json'), 'r') as settings_input:
            bool_settings = json.load(settings_input)
    single_import_upgrades: BoolVectorProperty(name = "Upgrade levels", description = "Armour upgrade levels to import", size = UPGRADE_SLOTS, default = (True,) + (False,)*(UPGRADE_SLOTS-1))
    delete_with_item: BoolProperty(name = "Delete objects", description = "Also delete the armature and every object parented to it when removing entries from the imported models list", default = bool_settings.get('delete_with_item', True))
    auto_prune_list: BoolProperty(name = "Drop entries for deleted objects", description = "Remove an entry from the imported models list as soon as the armature it points at is deleted from the file", default = bool_settings.get('auto_prune_list', True))
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
        drawImportListFilters(layout, context)
        row = layout.row()
        row.template_list("MED_2_TOOLKIT_UL_Import_List", "Import_list", context.scene, "med2_toolkit_import_list", context.scene, "med2_toolkit_import_list_index")
        row = layout.row(align=True)
        row.operator("medieval2toolkit.add_armature_to_list", text="Add Selected").selection_only = True
        row.operator("medieval2toolkit.add_armature_to_list", text="Add All Unlisted").selection_only = False
        if context.scene.med2_toolkit_import_list_index >= 0 and context.scene.med2_toolkit_import_list:
            unit = context.scene.med2_toolkit_import_list[context.scene.med2_toolkit_import_list_index]
            col = layout.column()
            col.prop (unit, "id")
        layout.prop (context.scene.med2_toolkit_units, "delete_with_item", text="Delete objects with the entry")
        layout.prop (context.scene.med2_toolkit_units, "auto_prune_list", text="Drop entries for deleted objects")
        row = layout.row(align=True)
        row.operator("medieval2toolkit.remove_item", text="Remove item")
        row.operator("medieval2toolkit.purge_list", text="Purge list")
        if(context.mode != 'OBJECT'):
            layout.enabled = False

class MED_2_TOOLKIT_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="Name", description="Names of the imported units")
    id: StringProperty(name="Unit ID", description="IDs of the imported units")
    object_name: StringProperty(name="Object name", description="Name of the armature object this entry was imported as")
    # the card renderer needs it: units with no card_pic_dir/info_pic_dir in the
    # EDU are written into the owning faction's card folder
    faction: StringProperty(name="Faction", description="Faction codename this entry was imported for")
    use: BoolProperty(name="Include", description="Include this unit when creating card cameras", default=True)
    icon: StringProperty(name="Menu icon", description="")


# item.icon values, as an ownership-style filter for the list
UNIT_TYPE_FILTERS = [
    ('ALL', "All types", "Show every imported model"),
    ('unused', "Foot", "Units with no mount or engine"),
    ('mount', "Mounted", "Units riding a mount"),
    ('engine', "Engine", "Units crewing a siege engine"),
    ('custom', "Added by hand", "Armatures added to the list with Add Selected Armatures"),
]

SORT_ORDERS = [
    ('NONE', "Import order", "Leave the list in the order things were imported", 'SORTSIZE', 0),
    ('AZ', "A to Z", "Sort the list alphabetically", 'SORTALPHA', 1),
    ('ZA', "Z to A", "Sort the list reverse-alphabetically", 'SORT_DESC', 2),
]

def unitTypeIcon(item):
    if item.icon == 'mount':
        return 'SNAP_OFF'
    if item.icon == 'engine':
        return 'MOD_TINT'
    if item.icon == 'custom':
        return 'OUTLINER_OB_ARMATURE'
    return 'ARMATURE_DATA'


class MED_2_TOOLKIT_List_Filter(bpy.types.PropertyGroup):
    """Search / sort / type filter for the imported models list.

    These live on the scene rather than on the UIList so both the Unit Import and
    Unit Info panels can draw them above the list - a UIList's own draw_filter is
    hidden behind the little funnel arrow, which is where they used to be.
    """
    search: StringProperty(name = "Search", description = "Only show entries whose name matches", options = {'TEXTEDIT_UPDATE'})
    sort_order: EnumProperty(name = "Sort", description = "Order the list is shown in", items = SORT_ORDERS, default = 'NONE')
    unit_type: EnumProperty(name = "Type", description = "Only show imported models of this type", items = UNIT_TYPE_FILTERS, default = 'ALL')


def drawImportListFilters(layout, context):
    settings = context.scene.med2_toolkit_list_filter
    column = layout.column(align=True)
    column.prop(settings, "search", text="", icon='VIEWZOOM')
    row = column.row(align=True)
    row.prop(settings, "unit_type", text="")
    sort = row.row(align=True)
    for identifier, _label, _description, _icon, _number in SORT_ORDERS:
        sort.prop_enum(settings, "sort_order", identifier, text="")


class MED_2_TOOLKIT_OT_Check_Import_Items(bpy.types.Operator):
    bl_idname = "medieval2toolkit.check_import_items"
    bl_label = "Tick imported models"
    bl_description = "Tick, untick or invert the include boxes in the imported models list."
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(items = [('ALL', "All", ""), ('NONE', "None", ""), ('INVERT', "Invert", "")], default = 'ALL')

    @classmethod
    def poll(cls, context):
        return len(context.scene.med2_toolkit_import_list) > 0

    def execute(self, context):
        for item in context.scene.med2_toolkit_import_list:
            if self.mode == 'ALL':
                item.use = True
            elif self.mode == 'NONE':
                item.use = False
            else:
                item.use = not item.use
        return {"FINISHED"}


def listedObjectNames(scene):
    names = set()
    for item in scene.med2_toolkit_import_list:
        if item.object_name:
            names.add(item.object_name)
        if item.name:
            names.add(item.name)
    return names


def unlistedArmatures(context, selection_only):
    """Armatures in the scene that no import list entry points at.

    Control rigs are skipped and resolved to the skeleton they drive - the card
    tools want the unit, not its controller.
    """
    listed = listedObjectNames(context.scene)
    source = context.selected_objects if selection_only else context.scene.objects
    found = []
    for obj in source:
        if obj.type != 'ARMATURE':
            continue
        rigs = controlledRigs(obj) if isControlRig(obj) else [obj]
        for rig in rigs:
            if rig.name not in listed and rig not in found:
                found.append(rig)
    return found


class MED_2_TOOLKIT_OT_Add_Armature_To_List(bpy.types.Operator):
    bl_idname = "medieval2toolkit.add_armature_to_list"
    bl_label = "Add Armatures"
    bl_description = ("Add armatures that are in the scene but not in the imported models list, so hand-built "
                      "or hand-imported rigs can get a unit card too")
    bl_options = {"REGISTER", "UNDO"}

    selection_only: BoolProperty(
        name = "Selected only",
        description = "Add only the selected armatures. Untick to add every unlisted armature in the scene",
        default = True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    @classmethod
    def description(cls, context, properties):
        if properties.selection_only:
            return "Add the selected armatures to the imported models list so they can be given a unit card"
        return "Add every armature in the scene that is not already in the imported models list"

    def execute(self, context):
        armatures = unlistedArmatures(context, self.selection_only)
        if not armatures:
            if self.selection_only and not any(obj.type == 'ARMATURE' for obj in context.selected_objects):
                self.report({'WARNING'}, "No armature selected")
            else:
                self.report({'INFO'}, "Every armature in the scene is already in the list")
            return {'CANCELLED'}
        faction = ""
        cards = getattr(context.scene, "med2_toolkit_cards", None)
        if cards is not None:
            faction = cards.card_faction
        for armature in armatures:
            item = context.scene.med2_toolkit_import_list.add()
            item.name = armature.name
            # the card renderer files a card under this id, and looks it up in the
            # unit dictionary - a hand-built rig simply will not be in there, and
            # buildRenderQueue already falls back to the faction folder for those
            item.id = armature.name
            item.object_name = armature.name
            item.faction = faction
            item.use = True
            item.icon = 'custom'
        context.scene.med2_toolkit_import_list_index = len(context.scene.med2_toolkit_import_list) - 1
        self.report({'INFO'}, "Added %d armature(s): %s" % (len(armatures), ", ".join(a.name for a in armatures[:5])))
        return {'FINISHED'}


class MED_2_TOOLKIT_UL_Import_List(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(item, "use", text="")
            row.label(text=item.name, icon=unitTypeIcon(item))
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text = "")

    def draw_filter(self, context, layout):
        # the same controls the panel draws above the list, so the funnel menu
        # is not a second set of settings that disagree with it
        drawImportListFilters(layout, context)
        layout.prop(self, "use_filter_invert", text="Invert filter", icon='ARROW_LEFTRIGHT')

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        settings = context.scene.med2_toolkit_list_filter
        helper = bpy.types.UI_UL_list
        flags = []
        if settings.search:
            # reverse= here inverts which entries MATCH, not the sort order; the
            # sort direction is settings.sort_order and must not be fed to it
            flags = helper.filter_items_by_name(settings.search, self.bitflag_filter_item, items, "name")
        if not flags:
            flags = [self.bitflag_filter_item] * len(items)
        if settings.unit_type != 'ALL':
            for index, item in enumerate(items):
                # entries imported before the icon field existed read as foot units
                if (item.icon or 'unused') != settings.unit_type:
                    flags[index] &= ~self.bitflag_filter_item
        order = []
        if settings.sort_order != 'NONE':
            order = helper.sort_items_by_name(items, "name")
            if settings.sort_order == 'ZA':
                # sort_items_by_name returns each item's new position, so Z-A is
                # that position counted from the other end
                last = len(order) - 1
                order = [last - position for position in order]
        return flags, order

classes = [
    MED_2_TOOLKIT_Unit_data,
    MED_2_TOOLKIT_OT_Unit_Importer,
    MED_2_TOOLKIT_OT_Officer_Importer,
    MED_2_TOOLKIT_OT_Import_Full_Unit,
    MED_2_TOOLKIT_OT_Faction_Importer,
    MED_2_TOOLKIT_OT_Variations,
    MED_2_TOOLKIT_OT_Remove_Item,
    MED_2_TOOLKIT_OT_Purge_List,
    MED_2_TOOLKIT_OT_Check_Import_Items,
    MED_2_TOOLKIT_OT_Add_Armature_To_List,
    MED_2_TOOLKIT_List_Items,
    MED_2_TOOLKIT_List_Filter,
    MED_2_TOOLKIT_UL_Import_List,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_units = PointerProperty(type=MED_2_TOOLKIT_Unit_data)
    bpy.types.Scene.med2_toolkit_import_list = CollectionProperty(type = MED_2_TOOLKIT_List_Items)
    bpy.types.Scene.med2_toolkit_import_list_index = IntProperty(name = "Index of imported units", default = 0)
    bpy.types.Scene.med2_toolkit_list_filter = PointerProperty(type = MED_2_TOOLKIT_List_Filter)
    if watchImportList not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(watchImportList)
    if pruneAfterLoad not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(pruneAfterLoad)

def unregister():
    if watchImportList in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(watchImportList)
    if pruneAfterLoad in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(pruneAfterLoad)
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_units
    del bpy.types.Scene.med2_toolkit_import_list
    del bpy.types.Scene.med2_toolkit_import_list_index
    del bpy.types.Scene.med2_toolkit_list_filter