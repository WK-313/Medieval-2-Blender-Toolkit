import bpy
import json
import time
import traceback
import uuid
from bpy.app.handlers import persistent
from bpy.props import StringProperty, BoolProperty, BoolVectorProperty, PointerProperty, CollectionProperty, IntProperty, EnumProperty
from pathlib import Path

from..directories import saveFolderPaths, saveSettings, readJsonCached
from ..tasks.card_renderer import TARGET_TAG
from ..tasks.control_rig import controlRigOf, controlledRigs, isControlRig
from ..tasks.importer import unitChecker, fileChecker, unitImporter, modelImporter, importedArmature, hideVariations, postImport, missingModelPaths
from ..tasks.iwte_run import IWTE_STALL_SECONDS, abortIWTEJob, iwteStalled, redrawView3D
from ..tasks.task_writer import unitTaskWriter, engineTaskWriter, startTask
from ..tasks.unit_groups import adoptGroup, deriveRole, groupId, groupParts, groupRoot, unitRole
from .unit_export_panel import SEVERITY_ORDER, askAboutStall, showResultsPopup


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

    @classmethod
    def poll(cls, context):
        return _import_job is None

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

    @classmethod
    def poll(cls, context):
        return _import_job is None

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

# ---------------------------------------------------------------------------
# Batch importing
#
# Import Full Unit and Import faction are minutes of work, not seconds: a
# faction is every unit, every armour upgrade and optionally every officer, and
# the first import of any of them waits on IWTE converting .mesh files as well.
# Run straight through, that is Blender sitting frozen with nothing on screen,
# and no way to tell a slow import from a crashed one. So both go through the
# modal operator below instead: one model per timer tick, a progress bar naming
# the model it is on, and Esc to stop.
#
# The IWTE conversion is hoisted out of the per-unit loop and run ONCE for the
# whole batch, watched from the same timer rather than blocking. That is a fix
# in its own right - the task file is only truncated by unitTaskWriter at the
# start, so a faction import used to hand IWTE a task that grew by one unit each
# time round and re-converted everything already in it.
_import_job = None


def convertedCount(job):
    return sum(1 for path in job['convert_expected'] if path.exists())


def importProgress(job):
    """0-1 across both phases. The conversion is counted as the first fifth of
    the job whenever there is one to do - it has no common unit with "models
    imported", so any split is a guess, and this one at least keeps the bar
    moving through the part that takes longest."""
    if job['phase'] == 'convert':
        total = job['convert_total']
        return 0.2 * (job['convert_done'] / total if total else 1.0)
    share = 0.2 if job['convert_total'] else 0.0
    total = len(job['queue'])
    return share + (1.0 - share) * (job['index'] / total if total else 1.0)


def buildImportQueue(unit_info_list, import_officers):
    """One entry per model the batch will import, in the order it imports them.

    A unit's officers follow its armour upgrades so the whole unit lands
    together, and each entry carries both the file name the progress bar shows
    and the longer description under it."""
    queue = []
    for index, unit_info in enumerate(unit_info_list):
        unit_id = unit_info.get('ID', 'unit')
        models = unit_info['Model']
        for level in range(len(models)):
            queue.append({'kind': 'upgrade', 'unit': index, 'unit_info': unit_info,
                          'level': level, 'unit_id': unit_id, 'label': models[level],
                          'detail': "%s - upgrade %d" % (unit_id, level)})
        if import_officers:
            officers = unit_info['Officers']
            for position, officer in enumerate(officers):
                queue.append({'kind': 'officer', 'unit': index, 'unit_info': unit_info,
                              'officer': officer, 'unit_id': unit_id, 'label': officer,
                              'first': position == 0,
                              'detail': "%s - officer %d of %d" % (unit_id, position + 1, len(officers))})
    return queue


def prepareConversions(model_folder, unit_info_list, import_officers):
    """Everything the batch needs and has not got, appended to the IWTE task
    files but NOT handed to IWTE - the caller runs one conversion for the lot
    and watches it. Returns the list of conversions to run."""
    unitTaskWriter()
    engineTaskWriter()
    missing_units, missing_engines = [], []
    for unit_info in unit_info_list:
        for level in range(len(unit_info['Model'])):
            units, engines = unitChecker(model_folder, [unit_info], level, defer=True)
            missing_units += units
            missing_engines += engines
        if import_officers:
            missing_units += fileChecker(model_folder, unit_info['Officers'], defer=True)
    # a model shared by several units is in the task file once, so count it once
    missing_units = list(dict.fromkeys(missing_units))
    missing_engines = list(dict.fromkeys(missing_engines))
    conversions = []
    if missing_units:
        conversions.append({'task': 'toolkit_bmdb_task.txt',
                            'expected': missingModelPaths(model_folder, missing_units, []),
                            'what': "Converting %d unit mesh%s with IWTE"
                                    % (len(missing_units), "" if len(missing_units) == 1 else "es")})
    if missing_engines:
        conversions.append({'task': 'toolkit_engine_task.txt',
                            'expected': missingModelPaths(model_folder, [], missing_engines),
                            'what': "Converting %d siege engine%s with IWTE"
                                    % (len(missing_engines), "" if len(missing_engines) == 1 else "s")})
    return conversions


def importStep(context, job):
    """Import one model. Anything that goes wrong is recorded and the batch
    carries on - one bad officer should not cost you the other thirty-nine
    units, and the results popup lists everything at the end."""
    entry = job['queue'][job['index']]
    job['index'] += 1
    try:
        runImportEntry(job, entry)
    except Exception as error:
        traceback.print_exc()
        job['results'].append(('ERROR', "%s: %s" % (entry['detail'], error)))


def runImportEntry(job, entry):
    unit_info = entry['unit_info']
    model_folder = job['model_folder']
    faction = job['faction']

    if entry['unit'] != job['current_unit']:
        if job['current_unit'] is not None:
            # the unit just finished decides where the next one starts
            job['coordinates'][0] = job['unit_x'] + round(job['unit_width']*0.5, 1) + 0.25
        job['unit_x'] = job['coordinates'][0]
        job['unit_width'] = 0
        job['current_unit'] = entry['unit']

    if entry['kind'] == 'upgrade':
        level = entry['level']
        # defer: the whole batch was converted up front, so anything still
        # missing here is something IWTE did not write. Say so rather than
        # starting another blocking conversion for every unit in the faction.
        missing_units, missing_engines = unitChecker(model_folder, [unit_info], level, defer=True)
        for model_id in missing_units + missing_engines:
            job['results'].append(('WARNING', "%s was not converted - %s will be missing a model"
                                              % (model_id, entry['unit_id'])))
        if job['mode'] == 'faction':
            # apply_offset=False: every upgrade of this unit shares unit_x and
            # only stacks upward on Z, so the auto x-spacing must stay off
            offset = unitImporter(model_folder, unit_info, faction,
                                  [job['unit_x'], 0, level * UPGRADE_Z_STEP], level,
                                  apply_offset=False)
            job['unit_width'] = max(job['unit_width'], offset)
        else:
            offset = unitImporter(model_folder, unit_info, faction, job['coordinates'], level)
            job['coordinates'][0] += round(offset*0.5, 1) + 0.25
        job['last_offset'] = offset
        job['imported'] += 1
        return

    if entry.get('first'):
        for model_id in fileChecker(model_folder, unit_info['Officers'], defer=True):
            job['results'].append(('WARNING', "%s was not converted - an officer of %s will be missing"
                                              % (model_id, entry['unit_id'])))
        if job['mode'] == 'faction':
            job['officer_at'] = [job['unit_x'], 0, 0]
            job['officer_step'] = 2
        else:
            # Import Full Unit lines the officers up behind the unit, spaced by
            # the width the last upgrade reported
            step = round(job['last_offset']*0.5, 1)*2
            job['officer_at'] = [0, -step, 0]
            job['officer_step'] = step

    officer = entry['officer']
    model_info = job['bmdb'].get(officer) if job['bmdb'] else None
    if model_info is None:
        job['results'].append(('WARNING', "%s is not in the model dictionary - officer skipped" % officer))
        return
    existing = set(bpy.data.objects)
    result, width, z_offset = modelImporter(model_folder, officer, faction, model_info, officer)
    if result != 0:
        imported = importedArmature(existing)
        if imported:
            imported.location = list(job['officer_at'])
            imported.location[2] += z_offset
        job['imported'] += 1
    job['officer_at'][1] -= job['officer_step']


def postImportInView(context):
    """postImport frames the scene and reads the 3D view's shading mode, so it
    needs a VIEW_3D to run in. Called straight out of execute() it had one; from
    a modal timer the context can be any area, and view3d.view_all then raises
    "context is incorrect". Find a view and run it there."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            region = next((entry for entry in area.regions if entry.type == 'WINDOW'), None)
            if region is None:
                continue
            with context.temp_override(window=window, area=area, region=region,
                                       space_data=area.spaces.active):
                postImport(None, bpy.context)
            return


def drawImportProgress(layout, job):
    box = layout.box()
    box.label(text=job['title'], icon='IMPORT')
    if job['phase'] == 'convert':
        box.progress(factor=importProgress(job), type='BAR',
                     text="IWTE: %d/%d converted" % (job['convert_done'], job['convert_total']))
        box.label(text=job['convert_what'], icon='FILE_REFRESH')
    else:
        # a draw() that raises takes the whole sidebar down with it, so the
        # queue is indexed defensively even though startBatch refuses an empty one
        entry = job['queue'][min(job['index'], len(job['queue']) - 1)] if job['queue'] else None
        box.progress(factor=importProgress(job), type='BAR',
                     text="%d/%d  %s" % (job['index'], len(job['queue']),
                                         entry['label'] if entry else ""))
        if entry:
            box.label(text=entry['detail'], icon='ARMATURE_DATA')
    box.label(text="%ds elapsed - press Esc to stop" % int(time.time() - job['start']), icon='TIME')


class BatchImportBase:
    """Shared modal machinery for Import Full Unit and Import faction."""

    _timer = None
    mode = 'faction'
    title = "Import"

    def startBatch(self, context, unit_info_list, import_officers, hide_variations):
        global _import_job
        model_folder = bpy.context.scene.med2_toolkit_reader.directory_models
        saveFolderPaths()
        saveSettings()
        queue = buildImportQueue(unit_info_list, import_officers)
        if not queue:
            self.report({'ERROR'}, "Nothing to import")
            return {'CANCELLED'}
        try:
            conversions = prepareConversions(model_folder, unit_info_list, import_officers)
        except (OSError, KeyError) as error:
            self.report({'ERROR'}, "Could not write the IWTE task file: %s" % error)
            return {'CANCELLED'}
        bmdb = None
        if import_officers:
            with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
                bmdb = json.load(bmdb_input)
        _import_job = {
            'mode': self.mode, 'title': self.title,
            'queue': queue, 'index': 0, 'imported': 0, 'results': [],
            'model_folder': model_folder,
            'faction': context.scene.med2_toolkit_units.import_faction,
            'bmdb': bmdb, 'hide_variations': hide_variations,
            'coordinates': [0, 0, 0], 'unit_x': 0.0, 'unit_width': 0.0,
            'current_unit': None, 'last_offset': 0.0,
            'officer_at': [0, 0, 0], 'officer_step': 2,
            'start': time.time(),
            'conversions': conversions, 'convert_index': 0, 'process': None,
            'convert_expected': [path for entry in conversions for path in entry['expected']],
            'convert_total': sum(len(entry['expected']) for entry in conversions),
            'convert_done': 0, 'convert_what': "",
            'phase': 'convert' if conversions else 'import',
            'stall_interval': IWTE_STALL_SECONDS, 'stall_deadline': None,
        }
        if bpy.app.background or context.window is None:
            # no event loop to hang a timer on, so the whole batch runs here
            while not self.step(context):
                if _import_job['phase'] == 'convert' and _import_job['process'] is not None:
                    time.sleep(0.25)
            return self.finish(context)
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        redrawView3D(context)
        return {'RUNNING_MODAL'}

    def step(self, context):
        """One tick of work. True once the whole batch is done."""
        job = _import_job
        if job['phase'] == 'convert':
            return self.convertStep(context, job)
        if job['index'] >= len(job['queue']):
            return True
        importStep(context, job)
        return job['index'] >= len(job['queue'])

    def convertStep(self, context, job):
        job['convert_done'] = convertedCount(job)
        process = job['process']
        if process is None:
            if job['convert_index'] >= len(job['conversions']):
                job['phase'] = 'import'
                return not job['queue']
            conversion = job['conversions'][job['convert_index']]
            job['convert_what'] = conversion['what']
            try:
                job['process'] = startTask(context.scene.med2_toolkit_reader.directory_iwte,
                                           conversion['task'])
            except (OSError, RuntimeError) as error:
                job['results'].append(('ERROR', "IWTE could not be started: %s" % error))
                return self.skipConversions(job)
            job['stall_interval'] = IWTE_STALL_SECONDS
            job['stall_deadline'] = time.time() + IWTE_STALL_SECONDS
            return False
        if job.get('aborted'):
            job['results'].append(('WARNING', "IWTE conversion aborted - anything it had not "
                                              "written yet will be missing from the import"))
            return self.skipConversions(job)
        if process.poll() is None:
            if iwteStalled(job):
                askAboutStall(context, job, job['convert_what'])
            return False
        job['process'] = None
        job['convert_index'] += 1
        job['stall_deadline'] = None
        return False

    def skipConversions(self, job):
        """Give up on the remaining conversions and import what is on disk."""
        job['process'] = None
        job['aborted'] = False
        job['convert_index'] = len(job['conversions'])
        job['stall_deadline'] = None
        job['phase'] = 'import'
        return not job['queue']

    def modal(self, context, event):
        if _import_job is None:
            return {'FINISHED'}
        if event.type == 'ESC':
            _import_job['results'].append(('WARNING', "Cancelled after %d model(s)" % _import_job['imported']))
            if _import_job.get('process') is not None:
                abortIWTEJob(_import_job)
                _import_job['process'] = None
            return self.stop(context)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        done = self.step(context)
        context.window_manager.progress_update(int(importProgress(_import_job) * 100))
        redrawView3D(context)
        return self.stop(context) if done else {'RUNNING_MODAL'}

    def stop(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        result = self.finish(context)
        redrawView3D(context)
        return result

    def finish(self, context):
        global _import_job
        job = _import_job
        _import_job = None
        if job['hide_variations']:
            hideVariations()
        if not bpy.app.background:
            postImportInView(context)
        elapsed = time.time() - job['start']
        failed = sum(1 for level, _ in job['results'] if level == 'ERROR')
        problems = len(job['results'])
        job['results'].append(('INFO', "Imported %d model(s) in %.1fs" % (job['imported'], elapsed)))
        showResultsPopup(context, "%s: %d model(s), %d problem(s)"
                                  % (job['title'], job['imported'], problems),
                         sorted(job['results'], key=lambda result: SEVERITY_ORDER.get(result[0], 2)))
        self.report({'ERROR'} if failed else {'INFO'}, job['results'][-1][1])
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Import_Full_Unit(BatchImportBase, bpy.types.Operator):
    bl_idname = "medieval2toolkit.full_unit_importer"
    bl_label = "Import full unit"
    bl_description = "Import the selected unit with all its officers and variations."
    bl_options = {"REGISTER"}

    mode = 'full_unit'
    title = "Import Full Unit"

    @classmethod
    def poll(cls, context):
        return _import_job is None

    def execute(self, context):
        unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        return self.startBatch(context, [unit_info], True,
                               context.scene.med2_toolkit_units.hide_toggle)


class MED_2_TOOLKIT_OT_Faction_Importer(BatchImportBase, bpy.types.Operator):
    bl_idname = "medieval2toolkit.faction_importer"
    bl_label = "Import faction"
    bl_description = ("Import all units of the selected faction according to the ownership, "
                      "with every armour upgrade stacked on Z. Optionally also import each "
                      "unit's officers, placed behind it on -Y.")
    bl_options = {"REGISTER"}

    mode = 'faction'
    title = "Import faction"

    @classmethod
    def poll(cls, context):
        return _import_job is None

    def execute(self, context):
        unit_info_list = [json.loads(unit[0]) for unit in sortUnits(self, context)
                          if unit[0] != 'none']
        if not unit_info_list:
            self.report({'ERROR'}, "No units for this faction and ownership filter")
            return {'CANCELLED'}
        return self.startBatch(context, unit_info_list,
                               context.scene.med2_toolkit_units.faction_import_officers,
                               False)


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
        if _import_job is not None:
            drawImportProgress(layout, _import_job)
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