import bpy
import json
import uuid
from bpy.app.handlers import persistent
from bpy.props import StringProperty, BoolProperty, BoolVectorProperty, PointerProperty, CollectionProperty, IntProperty, EnumProperty
from pathlib import Path

from..directories import saveFolderPaths, saveSettings, readJsonCached
from ..tasks.card_renderer import TARGET_TAG
from ..tasks.control_rig import controlRigOf, controlledRigs, isControlRig
from ..tasks.importer import unitChecker, fileChecker, unitImporter, modelImporter, importedArmature, hideVariations, postImport
from ..tasks.task_writer import unitTaskWriter, engineTaskWriter
from ..tasks.unit_groups import adoptGroup, deriveRole, groupId, groupParts, groupRoot, unitRole


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
    # descr_sm_factions order is nobody's idea of findable - the dropdown is
    # alphabetical, here and everywhere else a faction is picked
    faction_list.sort(key=lambda entry: entry[1].lower())
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
    to it. Returns the number of objects removed.

    A root entry takes the whole unit with it - a mount takes its riders, an
    engine takes its crew - which the plain child walk only covers while none of
    them has a control rig; once one does, the part hangs off its controller
    instead. A sub-entry takes only its own armature.
    """
    target = trackedObject(item)
    if target is None:
        return 0
    members = [target] if item.is_part else groupParts(target)
    doomed = []
    for member in members:
        for obj in list(member.children_recursive) + [member]:
            if obj not in doomed:
                doomed.append(obj)
    for member in members:
        # the unit is parented UNDER its control rig, so deleting the unit would
        # otherwise strand the controller in the scene
        controller = controlRigOf(member)
        if controller is None or controller in doomed:
            continue
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

# Custom property tying an entry to its object. Object names are the only thing
# the list used to have, so renaming an armature stranded the entry - and with
# auto-prune on, deleted it. The entry and the object share a uid instead, which
# a rename cannot touch; names are only used to find the object the first time.
LIST_UID_KEY = "med2_list_uid"

# Set while the deferred sync is queued, so the depsgraph handler does not
# stack one timer per update.
_sync_queued = False

# Entries the sync could not resolve. A genuinely deleted object with auto-prune
# off would otherwise queue a fresh pass on every depsgraph update forever.
_unresolved = set()


def entryKey(item):
    return item.uid or item.object_name or item.name


def taggedObjects(uid):
    """Every object carrying a uid. More than one means the rig was duplicated
    after it was listed, and the copy took the tag with it."""
    if not uid:
        return []
    return [obj for obj in bpy.data.objects if obj.get(LIST_UID_KEY) == uid]


def trackedObject(item):
    """The object an import list entry points at, following renames.

    The name is tried first because it is a dict lookup; the scan over
    bpy.data.objects only runs once the name has gone, which is exactly the
    renamed-or-deleted case. An ambiguous uid (a duplicated rig) is left alone
    rather than guessed at, so the entry behaves as it did before uids existed.
    """
    name = item.object_name or item.name
    obj = bpy.data.objects.get(name) if name else None
    if obj is not None and (not item.uid or obj.get(LIST_UID_KEY) in (None, item.uid)):
        return obj
    matches = taggedObjects(item.uid)
    return matches[0] if len(matches) == 1 else None


def tagEntry(item, obj, fresh=False):
    """Give an entry and its object a shared uid. Returns True if it wrote one.

    `fresh` mints a new id instead of adopting the object's: a rig duplicated
    after it was listed brings the original's tag along with it, and the copy has
    to have its own before it goes into the list under its own entry.
    """
    uid = (None if fresh else (item.uid or obj.get(LIST_UID_KEY))) or uuid.uuid4().hex[:12]
    written = False
    if item.uid != uid:
        item.uid = uid
        written = True
    if obj.get(LIST_UID_KEY) != uid:
        obj[LIST_UID_KEY] = uid
        written = True
    return written


def retargetCardCameras(old_name, new_name):
    """Point card cameras that named a rig at its new name. Without this a rename
    drops the camera back on the guess-by-collection fallback, which can hand a
    collection's other unit back."""
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and obj.get(TARGET_TAG, "") == old_name:
            obj[TARGET_TAG] = new_name


def syncImportList(scene, prune=True):
    """Follow renames and, when `prune` is on, drop entries whose object really
    is gone. Returns (renamed, pruned).

    Only a full disappearance from bpy.data counts as gone: an object merely
    unlinked from the scene, or sitting in an excluded collection, is still there
    and its entry has to stay.
    """
    renamed = 0
    stale = []
    seen = set()
    for index, item in enumerate(scene.med2_toolkit_import_list):
        obj = trackedObject(item)
        if obj is None:
            stale.append(index)
            _unresolved.add(entryKey(item))
            continue
        _unresolved.discard(entryKey(item))
        tagEntry(item, obj)
        if item.uid in seen:
            # two entries pointing at one id: a duplicated rig carried the tag
            tagEntry(item, obj, fresh=True)
        seen.add(item.uid)
        old_name = item.object_name or item.name
        if obj.name != old_name:
            item.object_name = obj.name
            # an entry labelled with the object's own name follows it; a unit
            # imported from the EDU keeps the unit name it was listed under
            if item.name == old_name:
                item.name = obj.name
            retargetCardCameras(old_name, obj.name)
            renamed += 1
    if not prune:
        return renamed, 0
    for index in reversed(stale):
        scene.med2_toolkit_import_list.remove(index)
    if stale:
        scene.med2_toolkit_import_list_index = min(scene.med2_toolkit_import_list_index,
                                                   max(0, len(scene.med2_toolkit_import_list) - 1))
    return renamed, len(stale)


def runQueuedSync():
    global _sync_queued
    _sync_queued = False
    for scene in bpy.data.scenes:
        units = getattr(scene, "med2_toolkit_units", None)
        if units is None:
            continue
        renamed, removed = syncImportList(scene, prune=units.auto_prune_list)
        if renamed:
            print("Medieval 2 Toolkit: followed %d rename%s in the imported models list"
                  % (renamed, "" if renamed == 1 else "s"))
        if removed:
            print("Medieval 2 Toolkit: dropped %d imported models entr%s whose object was deleted"
                  % (removed, "y" if removed == 1 else "ies"))
    return None


def pendingEntries(scene):
    """Entries the deferred pass could still do something about: one whose object
    is not where it was (renamed or deleted), or that has no uid yet."""
    pending = []
    for item in scene.med2_toolkit_import_list:
        name = item.object_name or item.name
        if not item.uid or (name and bpy.data.objects.get(name) is None):
            pending.append(item)
    return pending


@persistent
def watchImportList(scene, depsgraph=None):
    """Queue a sync when an entry's object has been renamed or has gone.

    The check itself is a dict lookup per entry and runs on every depsgraph
    update, so the common case (everything where it was) costs nothing. The work
    is deferred to a timer because writing scene data from inside
    depsgraph_update_post retriggers the handler.
    """
    global _sync_queued
    if _sync_queued or scene is None:
        return
    units = getattr(scene, "med2_toolkit_units", None)
    if units is None or not scene.med2_toolkit_import_list:
        return
    pending = pendingEntries(scene)
    if not pending or all(entryKey(item) in _unresolved for item in pending):
        return
    _sync_queued = True
    bpy.app.timers.register(runQueuedSync, first_interval=0)


@persistent
def pruneAfterLoad(_file_path):
    # a saved file can carry entries for objects that were renamed or deleted in
    # a session that never ran the handler (or with the toggle off at the time)
    _unresolved.clear()
    runQueuedSync()


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
        # a unit entry takes its mount/rider sub-entries with it, or they would
        # be left in the list hanging under nothing
        doomed = entryGroupIndexes(imported_list, imported_list_index)
        if not doomed:
            return{"CANCELLED"}
        removed = 0
        if context.scene.med2_toolkit_units.delete_with_item:
            # only the entry the user picked deletes objects: a unit root
            # already takes its whole family, and the sub-entries point inside it
            removed = deleteImportedObjects(imported_list[imported_list_index])
        for index in reversed(doomed):
            imported_list.remove(index)
        context.scene.med2_toolkit_import_list_index = min(max(0, imported_list_index - 1), len(imported_list) -1)
        if context.scene.med2_toolkit_units.delete_with_item:
            self.report({'INFO'}, "Removed %d entr%s and deleted %d object(s)"
                        % (len(doomed), "y" if len(doomed) == 1 else "ies", removed))
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
                # a sub-entry's armature is already inside its unit's family, so
                # by the time the loop reaches it there is nothing left to delete
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
    # shared with the object as a custom property, so renaming the rig does not
    # strand (or, with auto-prune on, delete) its entry
    uid: StringProperty(name="Tracking id", description="Id shared with the object this entry points at", options={'HIDDEN'})
    # the card renderer needs it: units with no card_pic_dir/info_pic_dir in the
    # EDU are written into the owning faction's card folder
    faction: StringProperty(name="Faction", description="Faction codename this entry was imported for")
    use: BoolProperty(name="Include", description="Include this unit when creating card cameras", default=True)
    icon: StringProperty(name="Menu icon", description="")
    # A mount or a siege engine is several armatures - the mount plus a rider or
    # crew member each - so its entry folds them underneath it. They all share
    # the group id written onto the objects themselves by tasks/unit_groups.
    group: StringProperty(name="Unit group", description="Id shared by every armature of a mount or siege engine", options={'HIDDEN'})
    is_part: BoolProperty(name="Part of a unit", description="This entry is one armature of a mount or siege engine, not a unit of its own", options={'HIDDEN'})
    role: StringProperty(name="Role", description="What this armature is within the unit - the mount itself, a rider, a crew member")
    expanded: BoolProperty(name="Show the parts", description="Show the mount, riders and crew that make up this unit", default=False)


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
    if item.is_part:
        # the row is already indented under its unit, so the icon says which
        # armature of it this is rather than repeating the unit's type
        return 'BONE_DATA'
    if item.icon == 'mount':
        return 'SNAP_OFF'
    if item.icon == 'engine':
        return 'MOD_TINT'
    if item.icon == 'custom':
        return 'OUTLINER_OB_ARMATURE'
    return 'ARMATURE_DATA'


def groupIndexes(imported_list):
    """({group id: unit entry index}, {group id: [sub-entry indexes]}) in one
    pass over the list - the list runs to a whole faction, so nothing here may
    scan it again per entry."""
    roots = {}
    parts = {}
    for index, item in enumerate(imported_list):
        if not item.group:
            continue
        if item.is_part:
            parts.setdefault(item.group, []).append(index)
        else:
            roots.setdefault(item.group, index)
    return roots, parts


def groupEntries(imported_list):
    """{group id: [indexes]} of the sub-entries in the list, in list order."""
    return groupIndexes(imported_list)[1]


def entryGroupIndexes(imported_list, index):
    """Every index Remove item should take with `index`: a unit entry takes its
    own sub-entries, a sub-entry goes on its own."""
    if not (0 <= index < len(imported_list)):
        return []
    item = imported_list[index]
    indexes = [index]
    if item.group and not item.is_part:
        indexes.extend(groupEntries(imported_list).get(item.group, []))
    return sorted(set(indexes))


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
    tools want the unit, not its controller. A rider or crew member is resolved
    to the unit it belongs to, so a mount is offered once rather than once per
    armature it carries; adding it brings its parts in as sub-entries.
    """
    listed = listedObjectNames(context.scene)
    source = context.selected_objects if selection_only else context.scene.objects
    found = []
    for obj in source:
        if obj.type != 'ARMATURE':
            continue
        rigs = controlledRigs(obj) if isControlRig(obj) else [obj]
        for rig in rigs:
            root = groupRoot(rig) or rig
            if root.name in listed or root in found:
                continue
            found.append(root)
    return found


def unitParts(root):
    """[(object, role)] for the armatures a unit carries, tagging them if they
    were never tagged - a mount imported before groups existed, or one built by
    hand. Empty for a unit that is a single armature."""
    parts = groupParts(root)
    if len(parts) < 2:
        return []
    adoptGroup(root)
    return [(part, unitRole(part) or deriveRole(root, part, index))
            for index, part in enumerate(parts[1:], start=1)]


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
        imported_list = context.scene.med2_toolkit_import_list
        parts_added = 0
        for armature in armatures:
            # a mount or an engine added by hand folds its riders in underneath
            # it, the same way an imported one does
            parts = unitParts(armature)
            group = groupId(armature) if parts else ""
            item = imported_list.add()
            item.name = armature.name
            # the card renderer files a card under this id, and looks it up in the
            # unit dictionary - a hand-built rig simply will not be in there, and
            # buildRenderQueue already falls back to the faction folder for those
            item.id = armature.name
            item.object_name = armature.name
            item.faction = faction
            item.use = True
            item.icon = 'custom'
            item.group = group
            # entries made by the importer are tagged by the deferred sync on the
            # next depsgraph update; these can be tagged straight away
            tagEntry(item, armature, fresh=True)
            for part, role in parts:
                part_item = imported_list.add()
                part_item.name = role
                part_item.id = armature.name
                part_item.object_name = part.name
                part_item.faction = faction
                part_item.use = True
                part_item.icon = 'custom'
                part_item.group = group
                part_item.role = role
                part_item.is_part = True
                tagEntry(part_item, part, fresh=True)
                parts_added += 1
        context.scene.med2_toolkit_import_list_index = len(imported_list) - 1
        message = "Added %d armature(s): %s" % (len(armatures), ", ".join(a.name for a in armatures[:5]))
        if parts_added:
            message += " (+%d rider/crew armature(s))" % parts_added
        self.report({'INFO'}, message)
        return {'FINISHED'}


class MED_2_TOOLKIT_UL_Import_List(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            if item.is_part:
                # indented under its unit; filter_items only ever shows these
                # while that unit's arrow is open
                row.separator(factor=2.0)
            elif item.group:
                row.prop(item, "expanded", text="", emboss=False,
                         icon='DISCLOSURE_TRI_DOWN' if item.expanded else 'DISCLOSURE_TRI_RIGHT')
            else:
                # keeps the tick boxes of ordinary units in the same column as
                # the ones that have an arrow
                row.label(text="", icon='BLANK1')
            row.prop(item, "use", text="")
            row.label(text=item.name, icon=unitTypeIcon(item))
            if item.group and not item.is_part:
                # counted once per draw in filter_items, never per row - this
                # list runs to a whole faction and a scan per row is a scan
                # squared
                count = getattr(self, "_part_counts", {}).get(item.group, 0)
                if count:
                    sub = row.row()
                    sub.alignment = 'RIGHT'
                    sub.label(text="%d" % (count + 1))
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
        roots, parts = groupIndexes(items)
        # the row badge reads this rather than scanning the list again per row
        self._part_counts = {group: len(indexes) for group, indexes in parts.items()}
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
        # Sub-entries follow their unit rather than the filters: a rider is only
        # ever shown when its unit is shown AND that unit's arrow is open, so a
        # search that happens to match "Rider 1" cannot leave a row hanging
        # under nothing.
        for group, indexes in parts.items():
            root_index = roots.get(group)
            if root_index is None:
                # the unit entry has gone; its parts stand on their own
                continue
            visible = (items[root_index].expanded
                       and bool(flags[root_index] & self.bitflag_filter_item))
            for index in indexes:
                if visible:
                    flags[index] |= self.bitflag_filter_item
                else:
                    flags[index] &= ~self.bitflag_filter_item
        order = []
        if settings.sort_order != 'NONE':
            order = self.sortWithParts(items, parts, settings.sort_order == 'ZA')
        return flags, order

    def sortWithParts(self, items, parts, reverse):
        """Alphabetical by unit, with each unit's parts kept right underneath it.

        Sorting the flat list would scatter a mount's riders across the whole
        list - they are named "Rider 1", not after the unit - so only the unit
        entries are sorted and their parts are re-emitted behind them.
        """
        roots = [(index, item) for index, item in enumerate(items) if not item.is_part]
        roots.sort(key=lambda entry: entry[1].name.lower(), reverse=reverse)
        remaining = dict(parts)
        sequence = []
        for index, item in roots:
            sequence.append(index)
            if item.group:
                sequence.extend(remaining.pop(item.group, []))
        # a part whose unit entry has been removed still has to land somewhere
        for leftover in remaining.values():
            sequence.extend(leftover)
        neworder = [0] * len(items)
        for position, index in enumerate(sequence):
            neworder[index] = position
        return neworder

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