import bpy
import json
import math
import os
import time
from pathlib import Path
from bpy.props import BoolProperty, StringProperty, PointerProperty, CollectionProperty, EnumProperty, IntProperty
from ..directories import saveFolderPaths, loadStoredValue, storeValue
from ..tasks.unit_exporter import exportArmatureGLB, exportToMeshIWTE, open_folder, selectedModFolder, defaultTaskTemplate
from ..tasks.export_checks import runSelectCleanup, exportMeshes, uniqueMaterials, materialImages, activeExportArmature, exportSettings
from ..tasks.bmdb_writer import parseRelativeUnitPath, parseSpriteAndFooter, bmdbEntryNames

script_folder = Path(__file__).parent.parent

# Kept alive at module level: Blender requires dynamic EnumProperty item
# strings to stay referenced, otherwise they get garbage collected.
_material_items = []
_material_items_none = []

def exportSetMaterials(context):
    armature = activeExportArmature(context)
    if not armature:
        return []
    return uniqueMaterials(exportMeshes(context, armature))

def materialItems(self, context):
    global _material_items
    items = [(m.name, m.name, '') for m in exportSetMaterials(context)]
    if not items:
        items = [('none', 'None', 'No materials found on the armature meshes')]
    _material_items = items
    return _material_items

def materialItemsNone(self, context):
    global _material_items_none
    items = [('none', 'None', 'No attach material')]
    items += [(m.name, m.name, '') for m in exportSetMaterials(context)]
    _material_items_none = items
    return _material_items_none


def genBlankNormalsToggled(self, context):
    """When Generate Blank Normal Maps is switched on, auto-fill the normal
    output names as <main>_norm / <attach>_norm from the effective main and
    attach texture names. Materials that already have a normal map keep their
    output name untouched."""
    if not self.gen_blank_normals:
        return
    main_mat = bpy.data.materials.get(self.material_main)
    attach_mat = bpy.data.materials.get(self.material_attach) if self.material_attach != 'none' else None
    main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
    attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

    def base_name(image, requested):
        if requested:
            return requested
        if image:
            return os.path.splitext(os.path.basename(image.filepath) or image.name)[0]
        return ""

    if main_norm is None:
        name = base_name(main_diff, self.out_main)
        if name:
            self.out_main_norm = name + "_norm"
    if attach_mat and attach_norm is None:
        name = base_name(attach_diff, self.out_attach)
        if name:
            self.out_attach_norm = name + "_norm"


# Kept alive at module level like the material items (GC guard).
_copy_faction_items = []
_copy_unit_items = []

def copyFactionItems(self, context):
    global _copy_faction_items
    try:
        with open(script_folder/'text'/'available_factions.json', 'r') as factions_input:
            factions = json.load(factions_input)
    except (OSError, ValueError):
        factions = {}
    items = [(faction_id, display_name, '') for display_name, faction_id in factions.items()]
    if not items:
        items = [('none', 'None', 'Run Read Mod Data first')]
    _copy_faction_items = items
    return _copy_faction_items

def copyUnitItems(self, context):
    global _copy_unit_items
    try:
        with open(script_folder/'text'/'unit_dictionary.json', 'r') as units_input:
            unit_dictionary = json.load(units_input)
    except (OSError, ValueError):
        unit_dictionary = {}
    items = []
    for unit, info in unit_dictionary.items():
        try:
            if self.copy_faction not in info['Owners'][self.copy_filter]:
                continue
        except (KeyError, TypeError):
            continue
        items.append((json.dumps(info), unit, ''))
    if not items:
        items = [('none', 'None', '')]
    _copy_unit_items = items
    return _copy_unit_items


def bmdbUnitPathChanged(self, context):
    if self.bmdb_unit_path:
        storeValue('last_bmdb_unit_path', self.bmdb_unit_path)

# True while prefillCopyFields assigns values, so copyFieldChanged doesn't
# store a rig's untouched defaults over the remembered last-used selection.
_prefilling = False

def copyFieldChanged(self, context):
    if _prefilling:
        return
    self.copy_initialized = True
    for prop, key in (('copy_faction', 'last_copy_faction'), ('copy_filter', 'last_copy_filter'), ('copy_unit', 'last_copy_unit')):
        value = getattr(self, prop)
        if value and value != 'none':
            storeValue(key, value)

def iwteTemplateChanged(self, context):
    if self.iwte_task_template:
        storeValue('last_iwte_task_template', self.iwte_task_template)

def prefillCopyFields(export_data):
    """Fill a rig's untouched copy-from fields with the last used selection."""
    global _prefilling
    if export_data.copy_initialized:
        return
    export_data.copy_initialized = True
    stored = [(prop, loadStoredValue(key)) for prop, key in
              (('copy_faction', 'last_copy_faction'), ('copy_filter', 'last_copy_filter'), ('copy_unit', 'last_copy_unit'))]
    _prefilling = True
    try:
        for prop, value in stored:
            if value and value != 'none':
                try:
                    setattr(export_data, prop, value)
                except TypeError:
                    pass  # stored value not in the current mod's lists
    finally:
        _prefilling = False

def generateBmdbToggled(self, context):
    """Prefill a fresh rig's BMDB fields with the last used values when the
    entry generation is switched on, instead of starting blank."""
    if not self.generate_bmdb:
        return
    if not self.bmdb_unit_path:
        self.bmdb_unit_path = loadStoredValue('last_bmdb_unit_path')
    prefillCopyFields(self)

def copyFromUnitToggled(self, context):
    if self.copy_from_unit:
        prefillCopyFields(self)


class MED_2_TOOLKIT_Export_Faction(bpy.types.PropertyGroup):
    name: StringProperty(name = "Faction", description = "Display name of the faction")
    faction_id: StringProperty(name = "Faction ID", description = "Internal faction id used in battle_models.modeldb")
    enabled: BoolProperty(name = "Owned", description = "Include this faction in the generated BMDB entry", default = False)


class MED_2_TOOLKIT_Unit_Export_Data(bpy.types.PropertyGroup):
    export_visible_only: BoolProperty(name = "Visible Only", description = "Only export visible mesh children of the armature", default = True)
    export_animations: BoolProperty(name = "Export Animations", description = "Bake actions into the GLB. Slow and unnecessary for .mesh conversion, and reimports with the rig posed", default = False)
    bmdb_entry_name: StringProperty(name = "BMDB Entry Name", description = "Model name at the top of the generated BMDB entry. Leave blank to use the mesh name")
    export_glb_name: StringProperty(name = "Mesh Name", description = "Name of the exported GLB/mesh file and its output subfolder", default = "export")
    last_export_dir: StringProperty(default = "", options = {'HIDDEN'})
    last_exported_glb: StringProperty(default = "", options = {'HIDDEN'})
    material_main: EnumProperty(name = "Main Material", description = "Material treated as the unit's main texture", items = materialItems)
    material_attach: EnumProperty(name = "Attach Material", description = "Material treated as the attachment texture", items = materialItemsNone)
    out_main: StringProperty(name = "Main", description = "Output name for the main texture (no extension)")
    out_main_norm: StringProperty(name = "Main Normal", description = "Output name for the main normal map (no extension)")
    out_attach: StringProperty(name = "Attach", description = "Output name for the attachment texture (no extension)")
    out_attach_norm: StringProperty(name = "Attach Normal", description = "Output name for the attachment normal map (no extension)")
    gen_blank_normals: BoolProperty(name = "Generate Blank Normal Maps", description = "Copy a blank normal map of matching size from the addon's normals folder for materials without one. Auto-fills the normal output names as <main>_norm / <attach>_norm", default = False, update = genBlankNormalsToggled)
    generate_bmdb: BoolProperty(name = "Generate BMDB Entry", description = "Write a battle_models.modeldb entry text file on export. Prefills the mesh path and copy-from unit with the last used values", default = False, update = generateBmdbToggled)
    bmdb_unit_path: StringProperty(name = "Mesh Path", description = "Folder for the unit's mesh inside the mod's data folder; only the part after \\data\\ is used. Remembered as the default for new rigs", subtype = 'DIR_PATH', update = bmdbUnitPathChanged)
    bmdb_sprite: StringProperty(name = "Sprite", description = "Sprite path for the entry, e.g. unit_sprites/example_sprite.spr")
    bmdb_footer: StringProperty(name = "Footer", description = "Entry footer (mounts/weapons/animation block). Use \\n for line breaks")
    copy_from_unit: BoolProperty(name = "Copy sprite and animations from a unit", description = "Parse the sprite and footer from an existing unit in the mod's battle_models.modeldb", default = False, update = copyFromUnitToggled)
    copy_faction: EnumProperty(name = "Faction", description = "Faction whose unit list to copy from", items = copyFactionItems, update = copyFieldChanged)
    copy_filter: EnumProperty(name = "Ownership filter", description = "Unit ownership filter", items = [('ownership','Ownership',''),('era 0','Era 0',''),('era 1','Era 1',''),('era 2','Era 2','')], default = 1, update = copyFieldChanged)
    copy_unit: EnumProperty(name = "Unit", description = "Unit to copy the sprite and footer from", items = copyUnitItems, update = copyFieldChanged)
    copy_initialized: BoolProperty(default = False, options = {'HIDDEN'})
    iwte_task_template: StringProperty(name = "IWTE Task Template", description = "Task template used for this rig's GLB to .mesh conversion. Blank = the last used / Paths template, adopted on the first conversion", subtype = 'FILE_PATH', update = iwteTemplateChanged)


SEVERITY_ORDER = {'ERROR': 0, 'WARNING': 1, 'INFO': 2}
SEVERITY_ICONS = {'ERROR': 'CANCEL', 'WARNING': 'ERROR', 'INFO': 'INFO'}

def showResultsPopup(context, title, results):
    if bpy.app.background:
        return
    def draw(menu, _context):
        for level, message in results:
            menu.layout.label(text=message, icon=SEVERITY_ICONS.get(level, 'INFO'))
    worst = min((SEVERITY_ORDER.get(level, 2) for level, _ in results), default=2)
    icon = ('CANCEL', 'ERROR', 'CHECKMARK')[worst]
    context.window_manager.popup_menu(draw, title=title, icon=icon)


class MED_2_TOOLKIT_OT_Select_Cleanup(bpy.types.Operator):
    bl_idname = "medieval2toolkit.select_cleanup"
    bl_label = "Check Model for Export"
    bl_description = "Select the armature and its meshes (deselecting everything else), auto-fix names and duplicate materials, and report any problems before exporting."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        results = runSelectCleanup(context)

        # auto-assign materials named *_main / *_attach to the dropdowns
        export_data = exportSettings(context)
        for material in exportSetMaterials(context):
            lowered = material.name.lower()
            try:
                if '_main' in lowered and export_data.material_main != material.name:
                    export_data.material_main = material.name
                    results.append(('INFO', "Auto-assigned main material: %s" % material.name))
                elif '_attach' in lowered and export_data.material_attach != material.name:
                    export_data.material_attach = material.name
                    results.append(('INFO', "Auto-assigned attach material: %s" % material.name))
            except TypeError:
                pass

        # errors first so the most severe findings are instantly visible
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0}
        for level, message in results:
            self.report({level}, message)
            counts[level] += 1
        showResultsPopup(context, "Cleanup: %d error(s), %d warning(s), %d note(s)" % (counts['ERROR'], counts['WARNING'], counts['INFO']), results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Factions_Refresh(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_factions_refresh"
    bl_label = "Refresh Factions"
    bl_description = "Load the faction list from the last Read Mod Data into the active armature's entry."

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        factions_file = script_folder/'text'/'available_factions.json'
        try:
            with open(factions_file, 'r') as factions_input:
                factions = json.load(factions_input)
        except FileNotFoundError:
            factions = {}
        if not factions:
            self.report({'ERROR'}, "No factions found - run Read Mod Data first")
            return {'CANCELLED'}
        collection = activeExportArmature(context).med2_toolkit_export_factions
        previous = {item.faction_id: item.enabled for item in collection}
        collection.clear()
        for display_name, faction_id in factions.items():
            if 'spawning' in display_name.lower() or 'spawning' in faction_id.lower():
                continue
            item = collection.add()
            item.name = display_name
            item.faction_id = faction_id
            item.enabled = previous.get(faction_id, False)
        # merc is a bmdb-only codename, not a faction in descr_sm_factions
        if not any(item.faction_id == 'merc' for item in collection):
            item = collection.add()
            item.name = "Mercs"
            item.faction_id = "merc"
            item.enabled = previous.get("merc", False)
        self.report({'INFO'}, "Loaded %d factions" % len(collection))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Factions_Set(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_factions_set"
    bl_label = "Select All / None"
    bl_description = "Enable or disable ownership for all factions at once."

    select: BoolProperty(default = True)

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        for item in activeExportArmature(context).med2_toolkit_export_factions:
            item.enabled = self.select
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Faction_Toggle(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_faction_toggle"
    bl_label = "Toggle Faction Ownership"
    bl_options = {"INTERNAL"}

    index: IntProperty()

    @classmethod
    def description(cls, context, properties):
        armature = activeExportArmature(context)
        factions = armature.med2_toolkit_export_factions if armature else []
        if 0 <= properties.index < len(factions):
            return "Codename = %s" % factions[properties.index].faction_id
        return "Toggle ownership"

    def execute(self, context):
        armature = activeExportArmature(context)
        if armature is None:
            return {'CANCELLED'}
        factions = armature.med2_toolkit_export_factions
        if 0 <= self.index < len(factions):
            factions[self.index].enabled = not factions[self.index].enabled
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Copy_Sprite_Footer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.copy_sprite_footer"
    bl_label = "Copy Sprite and Footer"
    bl_description = "Parse the selected unit's sprite and footer from the mod's battle_models.modeldb into the fields below."

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        mod_folder = selectedModFolder(context)
        export_data = exportSettings(context)
        try:
            unit_info = json.loads(export_data.copy_unit)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Select a unit first (run Read Mod Data if the list is empty)")
            return {'CANCELLED'}
        if not unit_info.get('Model'):
            self.report({'ERROR'}, "Selected unit has no models")
            return {'CANCELLED'}
        model_name = unit_info['Model'][0]
        sprite, footer, error = parseSpriteAndFooter(bpy.path.abspath(mod_folder), model_name)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        export_data.bmdb_sprite = sprite
        export_data.bmdb_footer = footer.replace("\n", "\\n")
        self.report({'INFO'}, "Copied from '%s': sprite %s, footer %d line(s)" % (model_name, sprite, footer.count("\n") + 1))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Unit_GLB(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_glb"
    bl_label = "Export GLB + Convert Textures"
    bl_description = "Export the selected armature and its meshes to GLB, convert textures to .texture files, and optionally write a BMDB entry."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        saveFolderPaths()
        result = exportArmatureGLB(context)
        if not result.startswith("Finished"):
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        if result == "Finished":
            self.report({'INFO'}, "Export complete")
        else:
            notes = result[len("Finished, but: "):].split("; ")
            self.report({'WARNING'}, "Export complete, but: " + "; ".join(notes))
            showResultsPopup(context, "Export finished with warnings", [('WARNING', n) for n in notes])
        return {'FINISHED'}


# The one running IWTE conversion, shared with the Export panel so it can draw
# a progress bar. IWTE gives no percentage feedback, so the bar eases toward
# full over time and jumps to done when the mesh lands on disk. The .mesh can
# appear well after the IWTE process exits, so the watcher keeps polling the
# folder until the file shows up (or updates) or the wait times out.
_iwte_job = None

# How long to keep watching the folder after the IWTE process has exited.
IWTE_MESH_TIMEOUT = 300.0
# The mesh counts as written once it has stopped growing for this long.
IWTE_QUIET_SECONDS = 1.0

def iwteProgress(elapsed):
    return 1.0 - math.exp(-elapsed / 10.0)

def redrawView3D(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def iwteMeshReady(job):
    """True once the .mesh exists, is newer than any pre-existing file, and
    has stopped changing (same size as last check and quiet for a moment)."""
    try:
        stat = os.stat(job['mesh_path'])
    except OSError:
        return False
    if job['previous_mtime'] is not None and stat.st_mtime <= job['previous_mtime']:
        return False
    if stat.st_size <= 0 or time.time() - stat.st_mtime < IWTE_QUIET_SECONDS:
        return False
    if stat.st_size != job.get('last_size'):
        job['last_size'] = stat.st_size
        return False
    return True

def finishIWTEJob(job, success):
    """Compose the (level, message) report for a finished conversion."""
    elapsed = time.time() - job['start']
    if success:
        size = os.stat(job['mesh_path']).st_size
        return ('INFO', "IWTE conversion finished: %s (%d KB) in %.1fs" % (job['mesh_name'], max(1, size // 1024), elapsed))
    returncode = job['process'].returncode
    verb = "updated" if job['previous_mtime'] is not None else "created"
    return ('ERROR', "IWTE exited (code %s) but %s was not %s within %ds - check the task file and IWTE window" % (returncode, job['mesh_name'], verb, int(IWTE_MESH_TIMEOUT)))


class MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_iwte_mesh"
    bl_label = "Export to Mesh (IWTE)"
    bl_description = "Send the last exported GLB to IWTE to convert it into a .mesh file, showing progress until the conversion finishes."
    bl_options = {"REGISTER"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return _iwte_job is None and activeExportArmature(context) is not None

    def execute(self, context):
        global _iwte_job
        saveFolderPaths()
        result = exportToMeshIWTE(context)
        if isinstance(result, str):
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        _iwte_job = result
        if bpy.app.background or context.window is None:
            # Headless: no event loop for timers, wait for IWTE and then poll
            # the folder for the mesh the same way the modal timer does.
            result['process'].wait()
            deadline = time.time() + IWTE_MESH_TIMEOUT
            success = iwteMeshReady(result)
            while not success and time.time() < deadline:
                time.sleep(0.5)
                success = iwteMeshReady(result)
            return self.finish(context, success)
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        redrawView3D(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        job = _iwte_job
        wm = context.window_manager
        wm.progress_update(int(iwteProgress(time.time() - job['start']) * 100))
        redrawView3D(context)
        if iwteMeshReady(job):
            return self.stop(context, True)
        if job['process'].poll() is None:
            return {'RUNNING_MODAL'}
        # process gone: keep watching the folder, IWTE writes the mesh late
        if job.get('exit_time') is None:
            job['exit_time'] = time.time()
        if time.time() - job['exit_time'] < IWTE_MESH_TIMEOUT:
            return {'RUNNING_MODAL'}
        return self.stop(context, False)

    def stop(self, context, success):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        result = self.finish(context, success)
        redrawView3D(context)
        return result

    def finish(self, context, success):
        global _iwte_job
        job = _iwte_job
        _iwte_job = None
        level, message = finishIWTEJob(job, success)
        if level == 'ERROR':
            showResultsPopup(context, "IWTE conversion failed", [(level, message)])
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        showResultsPopup(context, "IWTE conversion finished", [(level, message)])
        self.report({'INFO'}, message)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Open_Export_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.open_export_folder"
    bl_label = "Open Output Folder"
    bl_description = "Open the armature's last unit export folder in the file explorer."

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        open_folder(exportSettings(context).last_export_dir)
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Unit_Export(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Unit_Export"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Unit Export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        armature = activeExportArmature(context)
        if not armature:
            layout.label(text="Select an armature to edit its export settings", icon='INFO')
            return
        export_data = armature.med2_toolkit_unit_export
        layout.label(text="Armature: %s" % armature.name, icon='ARMATURE_DATA')

        col = layout.column(align=True)
        col.prop(export_data, "export_visible_only")
        col.prop(export_data, "export_animations")
        col.prop(export_data, "bmdb_entry_name")
        col.prop(export_data, "export_glb_name")

        # entry name falls back to the mesh name, same as the BMDB writer
        entry_name = export_data.bmdb_entry_name or export_data.export_glb_name
        if entry_name:
            existing = bmdbEntryNames(bpy.path.abspath(selectedModFolder(context)))
            if existing is not None and entry_name.lower() in existing:
                col.label(text="BMDB entry '%s' already exists in this mod" % entry_name, icon='ERROR')

        layout.operator("medieval2toolkit.select_cleanup", icon='CHECKMARK')

        if context.mode != 'OBJECT':
            layout.enabled = False


class MED_2_TOOLKIT_PT_Export_Materials(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Export_Materials"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Materials + Textures"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        armature = activeExportArmature(context)
        if not armature:
            layout.label(text="Select an armature to list materials", icon='INFO')
            return
        export_data = armature.med2_toolkit_unit_export

        materials = exportSetMaterials(context)
        if len(materials) > 2:
            layout.label(text="More than 2 materials found (%d)" % len(materials), icon='ERROR')

        col = layout.column(align=True)
        col.prop(export_data, "material_main", text="Main")
        main_mat = bpy.data.materials.get(export_data.material_main)
        if main_mat:
            col.prop(main_mat, "name", text="Rename", icon='MATERIAL')
        col.separator()
        col.prop(export_data, "material_attach", text="Attach")
        attach_mat = bpy.data.materials.get(export_data.material_attach) if export_data.material_attach != 'none' else None
        if attach_mat:
            col.prop(attach_mat, "name", text="Rename", icon='MATERIAL')

        main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
        attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

        layout.separator()
        layout.label(text="Output Names:")
        grid = layout.column(align=True)

        header = grid.row(align=True)
        header_split = header.split(factor=0.45, align=True)
        header_split.label(text="Current output names")
        header_split.label(text="New output names (blank = current)")

        def image_row(label, image, prop_name):
            row = grid.row(align=True)
            split = row.split(factor=0.45, align=True)
            split.label(text="%s: %s" % (label, image.name if image else "missing"), icon='IMAGE_DATA' if image else 'X')
            split.prop(export_data, prop_name, text="")

        image_row("Main", main_diff, "out_main")
        image_row("Main Normal", main_norm, "out_main_norm")
        if attach_mat:
            image_row("Attach", attach_diff, "out_attach")
            image_row("Attach Normal", attach_norm, "out_attach_norm")

        if (main_mat and not main_norm) or (attach_mat and not attach_norm):
            layout.prop(export_data, "gen_blank_normals")


class MED_2_TOOLKIT_PT_Export_BMDB(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Export_BMDB"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "BMDB Entry"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        armature = activeExportArmature(context)
        if not armature:
            layout.label(text="Select an armature to edit its BMDB entry", icon='INFO')
            return
        export_data = armature.med2_toolkit_unit_export

        layout.prop(export_data, "generate_bmdb")
        if not export_data.generate_bmdb:
            return

        row = layout.row(align=True)
        row.label(text="Ownership:")
        row.operator("medieval2toolkit.export_factions_refresh", icon='FILE_REFRESH', text="")
        op = row.operator("medieval2toolkit.export_factions_set", text="All")
        op.select = True
        op = row.operator("medieval2toolkit.export_factions_set", text="None")
        op.select = False
        factions = armature.med2_toolkit_export_factions
        if not factions:
            layout.label(text="Press refresh after Read Mod Data", icon='INFO')
        else:
            grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
            for index, item in enumerate(factions):
                op = grid.operator("medieval2toolkit.export_faction_toggle", text=item.name,
                                   depress=item.enabled, icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT')
                op.index = index
            layout.label(text="Hover over a faction to see its codename", icon='INFO')

        layout.separator()
        col = layout.column(align=True)
        col.prop(export_data, "bmdb_unit_path", text="Mesh Path")
        relative = parseRelativeUnitPath(export_data.bmdb_unit_path) if export_data.bmdb_unit_path else ""
        if relative:
            col.label(text="Entry path: %s" % relative, icon='FILE_FOLDER')
        col.prop(export_data, "bmdb_sprite", text="Sprite")
        col.prop(export_data, "bmdb_footer", text="Footer")

        layout.prop(export_data, "copy_from_unit")
        if export_data.copy_from_unit:
            col = layout.column(align=True)
            col.prop(export_data, "copy_faction", text="Faction")
            col.prop(export_data, "copy_filter", text="Filter")
            col.prop(export_data, "copy_unit", text="Unit")
            col.operator("medieval2toolkit.copy_sprite_footer", icon='COPYDOWN')


class MED_2_TOOLKIT_PT_Export_Run(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Export_Run"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        export_data = exportSettings(context)

        if export_data is None:
            layout.label(text="Select an armature to export", icon='INFO')
            return
        if export_data.generate_bmdb:
            layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT', text="Export GLB + Convert Textures + BMDB")
        else:
            layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT')
        if export_data.last_export_dir:
            layout.operator("medieval2toolkit.open_export_folder", icon='FILE_FOLDER')
        layout.separator()
        layout.label(text="IWTE")
        col = layout.column(align=True)
        col.prop(export_data, "iwte_task_template", text="Task Template")
        if not export_data.iwte_task_template:
            fallback = defaultTaskTemplate(context.scene.med2_toolkit_reader)
            if fallback:
                col.label(text="Blank = %s" % os.path.basename(fallback.strip('"')), icon='FILE_TEXT')
        if _iwte_job is not None:
            elapsed = time.time() - _iwte_job['start']
            verb = "Converting" if _iwte_job['process'].returncode is None else "Waiting for"
            layout.progress(factor=iwteProgress(elapsed), type='BAR',
                            text="%s %s... %ds" % (verb, _iwte_job['mesh_name'], int(elapsed)))
        else:
            layout.operator("medieval2toolkit.export_unit_iwte_mesh", icon='MOD_ARMATURE')
        if context.mode != 'OBJECT':
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Export_Faction,
    MED_2_TOOLKIT_Unit_Export_Data,
    MED_2_TOOLKIT_OT_Select_Cleanup,
    MED_2_TOOLKIT_OT_Export_Factions_Refresh,
    MED_2_TOOLKIT_OT_Export_Factions_Set,
    MED_2_TOOLKIT_OT_Export_Faction_Toggle,
    MED_2_TOOLKIT_OT_Copy_Sprite_Footer,
    MED_2_TOOLKIT_OT_Export_Unit_GLB,
    MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh,
    MED_2_TOOLKIT_OT_Open_Export_Folder,
    MED_2_TOOLKIT_PT_Unit_Export,
    MED_2_TOOLKIT_PT_Export_Materials,
    MED_2_TOOLKIT_PT_Export_BMDB,
    MED_2_TOOLKIT_PT_Export_Run,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    # Stored on the Object (the armature) so every rig keeps its own export
    # settings, saved with the .blend.
    bpy.types.Object.med2_toolkit_unit_export = PointerProperty(type=MED_2_TOOLKIT_Unit_Export_Data)
    bpy.types.Object.med2_toolkit_export_factions = CollectionProperty(type=MED_2_TOOLKIT_Export_Faction)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Object.med2_toolkit_unit_export
    del bpy.types.Object.med2_toolkit_export_factions
