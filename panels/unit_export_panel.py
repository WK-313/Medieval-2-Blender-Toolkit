import bpy
import json
import math
import os
import time
from pathlib import Path
from bpy.props import BoolProperty, StringProperty, PointerProperty, CollectionProperty, EnumProperty, IntProperty
from ..directories import saveFolderPaths, loadStoredValue, storeValue, readJsonCached
from ..tasks.unit_exporter import exportArmatureGLB, exportToMeshIWTE, open_folder, selectedModFolder, defaultTaskTemplate, bmdbEntryText, normalFileName
from ..tasks.export_checks import runSelectCleanup, exportMeshes, uniqueMaterials, materialImages, activeExportArmature, exportSettings, forceTextures, baseName, checkUVSpace, deselectAll, autoAssignMaterials, autoAssignUV
from ..tasks.bmdb_writer import parseRelativeUnitPath, parseSpriteAndFooter, bmdbEntryNames
from ..tasks.iwte_run import (IWTE_OUTPUT_TIMEOUT, finishIWTEJob, iwteOutputReady,
                              iwteProgress, redrawView3D, waitForIWTEJob)
from ..tasks import bmdb_install, modeldb, iwte_tasks

script_folder = Path(__file__).parent.parent

# Kept alive at module level: Blender requires dynamic EnumProperty item
# strings to stay referenced, otherwise they get garbage collected.
_material_items = []
_material_items_none = []
_task_sample_items = []

def exportSetMaterials(context):
    armature = activeExportArmature(context)
    if not armature:
        return []
    return uniqueMaterials(exportMeshes(context, armature))

def materialItems(self, context):
    global _material_items
    # 'None' first so an untouched rig has no main material rather than
    # silently adopting whichever material happens to come first
    items = [('none', 'None', 'No main material picked yet - run Check Model for Export or choose one')]
    items += [(m.name, m.name, '') for m in exportSetMaterials(context)]
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
    main_mat = bpy.data.materials.get(self.material_main) if self.material_main != 'none' else None
    attach_mat = bpy.data.materials.get(self.material_attach) if self.material_attach != 'none' else None
    main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
    attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

    def base_name(image, requested):
        if requested:
            return requested
        if image:
            return os.path.splitext(os.path.basename(image.filepath) or image.name)[0]
        return ""

    def norm_name(name):
        # insert _norm before the file extension so black_numenorean.png
        # becomes black_numenorean_norm.png, not black_numenorean.png_norm
        root, ext = os.path.splitext(name)
        return root + "_norm" + ext

    # a slot pointed at a normal map file keeps that file's name unless the
    # user typed one, so it is not renamed here
    if main_norm is None and not self.norm_main_file:
        name = base_name(main_diff, self.out_main)
        if name:
            self.out_main_norm = norm_name(name)
    if attach_mat and attach_norm is None and not self.norm_attach_file:
        name = base_name(attach_diff, self.out_attach)
        if name:
            self.out_attach_norm = norm_name(name)


# Kept alive at module level like the material items (GC guard). The unit
# list is also cached per (file version, faction, filter): the items callback
# runs on every redraw and rebuilding ~900 units of JSON identifiers each
# time lags the whole panel.
_copy_faction_items = []
_copy_unit_cache = {'key': None, 'items': [('none', 'None', '')]}

def copyFactionItems(self, context):
    global _copy_faction_items
    factions = readJsonCached(script_folder/'text'/'available_factions.json')
    items = [(faction_id, display_name, '') for display_name, faction_id in factions.items()]
    items.sort(key=lambda item: item[1].lower())
    if not items:
        items = [('none', 'None', 'Run Read Mod Data first')]
    _copy_faction_items = items
    return _copy_faction_items

def copyUnitItems(self, context):
    path = script_folder/'text'/'unit_dictionary.json'
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    key = (mtime, self.copy_faction, self.copy_filter)
    if _copy_unit_cache['key'] == key:
        return _copy_unit_cache['items']
    unit_dictionary = readJsonCached(path)
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
    _copy_unit_cache['key'] = key
    _copy_unit_cache['items'] = items
    return _copy_unit_cache['items']


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

def taskSampleItems(self, context):
    global _task_sample_items
    items = [('auto', 'Auto (from skeleton)',
              "Use the bundled sample task file for the skeleton this rig is parented to. "
              "Rigs that are not on one of the QOL skeletons fall back to the last used / Paths template"),
             ('custom', 'Custom File',
              "Use the task file picked with the browse button next to the Task Template above")]
    for path in iwte_tasks.sampleTaskFiles():
        items.append((path.name, "%s sample" % iwte_tasks.sampleTaskLabel(path.name), path.name))
    _task_sample_items = items
    return _task_sample_items

def taskSampleChanged(self, context):
    """Point the rig's task template at the picked sample. 'Custom File' leaves
    the browsed path alone; 'Auto' re-resolves it from the rig's skeleton."""
    choice = self.iwte_task_sample
    if choice == 'custom':
        return
    if choice == 'auto':
        path, _skeleton = iwte_tasks.autoSampleTask(self.id_data)
    else:
        path = str(iwte_tasks.sampleTasksFolder()/choice)
    self.iwte_task_template = path if path and os.path.isfile(path) else ""

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
    select_wrong_uv: BoolProperty(name = "Select objects with wrong UV", description = "After the check, select the objects whose UVs are in the wrong tile and enter UV/edit mode on them", default = False)
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
    ignore_diffuse_alpha: BoolProperty(name = "Ignore Diffuse Alpha", description = "Write the main and attachment textures with a fully opaque alpha channel. The game reads the diffuse alpha as transparency, so a texture painted with an unused or half-empty alpha channel makes those parts of the unit see-through in game - this throws that alpha away. Leave it off when the alpha is a deliberate cutout (hair, chainmail gaps, banners). Normal maps are never touched: their alpha is the specular map, not a cutout", default = False)
    norm_main_file: StringProperty(name = "Main Normal File", description = "Normal map image on disk to use for the main texture when the material has no normal map wired in. It is converted to .dds and .texture with the rest of the export and named in the BMDB entry, so a normal map painted in an image editor needs no separate IWTE run. Leave the output name blank to keep the file's own name", subtype = 'FILE_PATH')
    norm_attach_file: StringProperty(name = "Attach Normal File", description = "Normal map image on disk to use for the attachment texture when the material has no normal map wired in. It is converted to .dds and .texture with the rest of the export and named in the BMDB entry, so a normal map painted in an image editor needs no separate IWTE run. Leave the output name blank to keep the file's own name", subtype = 'FILE_PATH')
    gen_blank_normals: BoolProperty(name = "Generate Blank Normal Maps", description = "Copy a blank normal map of matching size from the addon's normals folder for materials without one. Auto-fills the normal output names as <main>_norm / <attach>_norm", default = False, update = genBlankNormalsToggled)
    generate_bmdb: BoolProperty(name = "Generate BMDB Entry", description = "Build a battle_models.modeldb entry for this rig. Prefills the mesh path and copy-from unit with the last used values", default = False, update = generateBmdbToggled)
    bmdb_mode: EnumProperty(
        name = "Entry goes to",
        description = "What happens with the entry this panel builds",
        items = [('txt', 'Text File', "Write the entry beside the export as <mesh name>_bmdb.txt, to paste into battle_models.modeldb by hand. Nothing in the mod is touched"),
                 ('install', 'Install to Mod', "Write the entry straight into the mod's battle_models.modeldb and copy the mesh and textures into the mod, from the Install to Mod panel. Adds, renames or replaces an entry and keeps the file's entry count correct"),
                 ('both', 'Both', "Write the <mesh name>_bmdb.txt beside the export AND install into the mod from the Install to Mod panel. The same entry text either way, so the txt is a record of what was installed")],
        default = 'txt')
    bmdb_unit_path: StringProperty(name = "Mesh Path", description = "Folder for the unit's mesh inside the mod's data folder; only the part after \\data\\ is used. Remembered as the default for new rigs", subtype = 'DIR_PATH', update = bmdbUnitPathChanged)
    bmdb_sprite: StringProperty(name = "Sprite", description = "Sprite path for the entry, e.g. unit_sprites/example_sprite.spr")
    bmdb_footer: StringProperty(name = "Footer", description = "Entry footer (mounts/weapons/animation block). Use \\n for line breaks")
    copy_from_unit: BoolProperty(name = "Copy sprite and animations from a unit", description = "Parse the sprite and footer from an existing unit in the mod's battle_models.modeldb", default = False, update = copyFromUnitToggled)
    copy_faction: EnumProperty(name = "Faction", description = "Faction whose unit list to copy from", items = copyFactionItems, update = copyFieldChanged)
    copy_filter: EnumProperty(name = "Ownership filter", description = "Unit ownership filter", items = [('ownership','Ownership',''),('era 0','Era 0',''),('era 1','Era 1',''),('era 2','Era 2','')], default = 1, update = copyFieldChanged)
    copy_unit: EnumProperty(name = "Unit", description = "Unit to copy the sprite and footer from", items = copyUnitItems, update = copyFieldChanged)
    copy_initialized: BoolProperty(default = False, options = {'HIDDEN'})
    iwte_task_template: StringProperty(name = "IWTE Task Template", description = "Task template used for this rig's GLB to .mesh conversion. Blank = the last used / Paths template, adopted on the first conversion. Use the browse button to pick it, starting in the IWTE tasks folder", update = iwteTemplateChanged)
    iwte_task_sample: EnumProperty(name = "Sample Task File", description = "Which of the addon's bundled sample task files this rig converts with. Auto picks the one for the skeleton the rig is parented to", items = taskSampleItems, update = taskSampleChanged)
    install_on_conflict: EnumProperty(
        name = "If the entry exists",
        description = "What to do when battle_models.modeldb already has an entry with this name and different content",
        items = [(bmdb_install.CONFLICT_RENAME, 'Rename', "Add the new entry under a free name (name_2, name_3, ...) and leave the old one alone"),
                 (bmdb_install.CONFLICT_OVERWRITE, 'Overwrite', "Replace the existing entry. Anything it had that this one does not - extra LODs, extra faction skins - is lost"),
                 (bmdb_install.CONFLICT_SKIP, 'Skip', "Install nothing and report the clash")],
        default = bmdb_install.CONFLICT_RENAME)
    install_new_name: StringProperty(name = "New Entry Name", description = "Name to add the entry under when renaming. Blank picks the first free name_2 / name_3 / ...")
    install_asset_conflict: EnumProperty(
        name = "If a file exists",
        description = "What to do with a mesh or texture that is already in the mod with different content",
        items = [(bmdb_install.ASSET_KEEP, 'Keep Existing', "Leave the mod's file alone - the unit uses the mod's version"),
                 (bmdb_install.ASSET_OVERWRITE, 'Overwrite', "Replace the mod's file with the exported one, which also re-skins any other model sharing it")],
        default = bmdb_install.ASSET_KEEP)
    install_backup: BoolProperty(name = "Back up modeldb", description = "Before the entry is written, copy battle_models.modeldb as a timestamped .bak - once next to itself in the mod, and once into the export folder beside the mesh and textures this install came from. Either copy puts the file back exactly as it was", default = True)
    install_summary: StringProperty(default = "", options = {'HIDDEN'})


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

        # auto-detect main/attach materials by name, fill in the lone
        # remaining material once attach is known, and fold any extra
        # materials into main/attach
        export_data = exportSettings(context)
        results.extend(autoAssignMaterials(context))

        # rigs parented to a QOL skeleton before this addon version have no task
        # file yet, so pick theirs up here too
        skeleton = iwte_tasks.applySkeletonTask(activeExportArmature(context))
        if skeleton:
            results.append(('INFO', "Rigged to the %s skeleton: using its IWTE sample task file" % skeleton))

        # UV tile placement, right after the main/attach textures are known
        uv_results, wrong_uv = checkUVSpace(context)
        results.extend(uv_results)

        # errors first so the most severe findings are instantly visible
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0}
        for level, message in results:
            self.report({level}, message)
            counts[level] += 1
        showResultsPopup(context, "Cleanup: %d error(s), %d warning(s), %d note(s)" % (counts['ERROR'], counts['WARNING'], counts['INFO']), results)

        # optionally isolate the wrong-UV objects and drop into UV editing
        if export_data.select_wrong_uv and wrong_uv:
            deselectAll(context)
            for obj in wrong_uv:
                try:
                    obj.hide_set(False)
                    obj.select_set(True)
                except RuntimeError:
                    pass
            context.view_layer.objects.active = wrong_uv[0]
            try:
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
            except RuntimeError:
                pass
            uv_editing = bpy.data.workspaces.get("UV Editing")
            if uv_editing is not None and context.window is not None:
                context.window.workspace = uv_editing
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Force_Textures(bpy.types.Operator):
    bl_idname = "medieval2toolkit.force_textures"
    bl_label = "Force Textures"
    bl_description = ("Reassign every mesh slot that uses a .001/.002 numbered duplicate of the "
                      "selected main/attach material to that material itself, even if the duplicate "
                      "uses different textures. Only material.NNN names match; material1.001 is left alone.")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        results = forceTextures(context)
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0}
        for level, message in results:
            self.report({level}, message)
            counts[level] += 1
        showResultsPopup(context, "Force Textures: %d change note(s), %d error(s)" % (counts['INFO'], counts['ERROR']), results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Auto_Assign_UV(bpy.types.Operator):
    bl_idname = "medieval2toolkit.auto_assign_uv"
    bl_label = "Attempt to Auto-Assign UV"
    bl_description = ("Move whole UV islands onto the correct tile (main = u 0-1, attach = u 1-2) "
                      "when they fit inside a single grid cell. Islands spanning more than one tile "
                      "are left for manual fixing.")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        results = autoAssignUV(context)
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0}
        for level, message in results:
            self.report({level}, message)
            counts[level] += 1
        showResultsPopup(context, "Auto-Assign UV: %d note(s), %d warning(s)" % (counts['INFO'], counts['WARNING']), results)
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
        # alphabetical, like every other faction list; Mercs is appended after
        # the sort because it is not a descr_sm_factions faction at all
        for display_name, faction_id in sorted(factions.items(), key=lambda entry: entry[0].lower()):
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


class MED_2_TOOLKIT_OT_Copy_Mesh_Name(bpy.types.Operator):
    bl_idname = "medieval2toolkit.copy_mesh_name"
    bl_label = "Copy Mesh Name"
    bl_description = "Use the mesh name as the BMDB entry name."

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        export_data = exportSettings(context)
        if not export_data.export_glb_name:
            self.report({'ERROR'}, "Mesh name is empty")
            return {'CANCELLED'}
        export_data.bmdb_entry_name = export_data.export_glb_name
        self.report({'INFO'}, "BMDB entry name set to '%s'" % export_data.export_glb_name)
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


class MED_2_TOOLKIT_OT_BMDB_Load_Entry(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_load_entry"
    bl_label = "Load Entry From Mod"
    bl_description = ("Read the entry of this name out of the mod's battle_models.modeldb into the "
                      "fields above, so it can be edited and written back with Install to Mod.")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        armature = activeExportArmature(context)
        export_data = armature.med2_toolkit_unit_export
        name = (export_data.bmdb_entry_name or export_data.export_glb_name).strip()
        if not name:
            self.report({'ERROR'}, "Set an entry name (or a mesh name) first")
            return {'CANCELLED'}
        mod_folder = bpy.path.abspath(selectedModFolder(context))
        db, error = modeldb.loadModelDb(mod_folder)
        if db is None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        entry = db.get(name)
        if entry is None:
            self.report({'ERROR'}, "No entry '%s' in the mod's battle_models.modeldb" % name)
            return {'CANCELLED'}

        results = []
        export_data.generate_bmdb = True
        export_data.bmdb_entry_name = entry.name
        mesh = entry.mesh_files()[0] if entry.mesh_files() else ""
        relative = "/".join(mesh.split("/")[:-1])
        if relative:
            export_data.bmdb_unit_path = os.path.join(mod_folder, *relative.split("/"))
            results.append(('INFO', "Mesh path -> %s" % relative))
        main = entry.main_textures[0] if entry.main_textures else None
        attach = entry.attach_textures[0] if entry.attach_textures else None
        for record, diffuse_prop, normal_prop in ((main, 'out_main', 'out_main_norm'),
                                                  (attach, 'out_attach', 'out_attach_norm')):
            if record is None:
                continue
            for path, prop in ((record.texture, diffuse_prop), (record.normal, normal_prop)):
                if not path or path == "0":
                    continue
                setattr(export_data, prop, os.path.splitext(os.path.basename(path))[0])
                results.append(('INFO', "%s -> %s" % (prop, getattr(export_data, prop))))
        if main is not None and main.sprite and main.sprite != "0":
            export_data.bmdb_sprite = main.sprite
            results.append(('INFO', "Sprite -> %s" % main.sprite))
        export_data.bmdb_footer = entry.footer().replace("\n", "\\n")
        results.append(('INFO', "Footer -> %d mount block(s), skeletons: %s"
                        % (len(entry.animations), ", ".join(sorted(set(entry.skeletons()))) or "none")))

        wanted = set(entry.factions())
        factions = armature.med2_toolkit_export_factions
        if not factions:
            results.append(('WARNING', "Faction list is empty - press refresh under Ownership, then load again"))
        else:
            for item in factions:
                item.enabled = item.faction_id in wanted
            unknown = wanted - {item.faction_id for item in factions}
            results.append(('INFO', "Ownership -> %d faction(s) ticked" % len(wanted - unknown)))
            if unknown:
                results.append(('WARNING', "Entry has skins for %s, which are not in the faction list - "
                                "run Read Mod Data on this mod" % ", ".join(sorted(unknown))))

        if len(entry.lods) > 1:
            results.append(('WARNING', "Entry has %d LODs - the toolkit writes a single LOD, so "
                            "installing it back drops the other %d" % (len(entry.lods), len(entry.lods) - 1)))
        mesh_name = os.path.splitext(os.path.basename(mesh))[0]
        if mesh_name and mesh_name.lower() != export_data.export_glb_name.lower():
            results.append(('WARNING', "Entry points at %s.mesh but this rig exports %s.mesh - installing "
                            "repoints it at the exported mesh" % (mesh_name, export_data.export_glb_name)))

        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        for level, message in results:
            self.report({level}, message)
        showResultsPopup(context, "Loaded entry '%s'" % entry.name, results)
        return {'FINISHED'}


def buildInstallPlan(context, for_install=True):
    """Plan an install of the active rig's BMDB entry. Returns (plan, error).

    `for_install=False` is the probe: planning writes nothing, so it is allowed
    in Text File mode too - "would this entry clash with the mod?" is worth
    answering whether or not the toolkit is the one pasting it in.
    """
    export_data = exportSettings(context)
    if export_data is None:
        return None, "Select an Armature"
    if not export_data.generate_bmdb:
        return None, "Turn on Generate BMDB Entry first - there is no entry to install"
    if for_install and export_data.bmdb_mode not in {'install', 'both'}:
        return None, "BMDB Entry is set to Text File - switch it to Install to Mod (or Both) first"
    entry_text, _entry_name, relative, error = bmdbEntryText(context)
    if error:
        return None, "No BMDB entry to install: %s" % error
    out_dir = export_data.last_export_dir
    if not out_dir:
        base_out = bpy.path.abspath(context.scene.med2_toolkit_reader.directory_unit_export.strip('"').strip("'"))
        out_dir = os.path.join(base_out, export_data.export_glb_name)
    plan = bmdb_install.planInstall(
        mod_folder=bpy.path.abspath(selectedModFolder(context)),
        out_dir=out_dir,
        entry_text=entry_text,
        relative=relative,
        on_conflict=export_data.install_on_conflict,
        new_name=export_data.install_new_name,
        asset_conflict=export_data.install_asset_conflict,
        backup=export_data.install_backup,
        unit_dictionary=readJsonCached(script_folder/'text'/'unit_dictionary.json'),
    )
    return plan, ""


def planSummary(plan):
    copying = len([f for f in plan.files if f.willCopy(plan.asset_conflict)])
    return "%s '%s', %d/%d file(s) to copy, %d error(s), %d warning(s)" % (
        plan.entry_action, plan.final_name, copying, len(plan.files),
        len(plan.errors), len(plan.warnings))


class MED_2_TOOLKIT_OT_BMDB_Check_Install(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_check_install"
    bl_label = "Probe BMDB"
    bl_description = ("Read the mod's battle_models.modeldb and report what this entry would do to it - "
                      "whether the name clashes and what Rename / Overwrite / Skip would then do, which "
                      "files are already in the mod and which models share them. Nothing is written, in "
                      "any mode.")

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        export_data = exportSettings(context)
        plan, error = buildInstallPlan(context, for_install=False)
        if plan is None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        export_data.install_summary = planSummary(plan)
        results = plan.results() + fileResults(plan)
        if export_data.bmdb_mode == 'txt':
            results.append(('INFO', "Text File mode: this is what an install WOULD do. Switch to "
                            "Install to Mod, or Both, to actually write it"))
        for level, message in results:
            self.report({level}, message)
        showResultsPopup(context, "BMDB probe: %s" % planSummary(plan), results)
        return {'FINISHED'}


def fileResults(plan):
    """One line per file, saying what the install would do with it."""
    verbs = {
        bmdb_install.STATE_NEW: "copy",
        bmdb_install.STATE_IDENTICAL: "already there, unchanged",
        bmdb_install.STATE_IN_PLACE: "already the same file",
        bmdb_install.STATE_ONLY_DEST: "not re-exported, kept",
        bmdb_install.STATE_MISSING: "MISSING",
    }
    out = []
    for action in plan.files:
        if action.state == bmdb_install.STATE_DIFFERS:
            verb = ("overwrite" if plan.asset_conflict == bmdb_install.ASSET_OVERWRITE
                    else "keep the mod's version")
            level = 'WARNING'
        else:
            verb = verbs.get(action.state, action.state)
            level = 'ERROR' if action.state == bmdb_install.STATE_MISSING else 'INFO'
        out.append((level, "%s: %s -> %s" % (verb, os.path.basename(action.rel), action.rel)))
    return out


class MED_2_TOOLKIT_OT_BMDB_Install(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_install"
    bl_label = "Install to Mod"
    bl_description = ("Write the entry into the mod's battle_models.modeldb and copy the exported "
                      "mesh and textures into the mod. Shows everything it will do first.")
    bl_options = {"REGISTER"}

    _plan = None

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def invoke(self, context, event):
        plan, error = buildInstallPlan(context)
        if plan is None:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self._plan = plan
        exportSettings(context).install_summary = planSummary(plan)
        return context.window_manager.invoke_props_dialog(self, width=560)

    def draw(self, context):
        layout = self.layout
        plan = self._plan
        if plan is None:
            layout.label(text="Nothing planned", icon='INFO')
            return
        layout.label(text="Mod: %s" % plan.mod_folder, icon='FILE_FOLDER')
        for level, message in plan.results() + fileResults(plan):
            layout.label(text=message, icon=SEVERITY_ICONS.get(level, 'INFO'))
        if plan.blocked():
            layout.label(text="Nothing will be written until these are fixed", icon='CANCEL')
        elif plan.backup:
            layout.label(text="battle_models.modeldb is backed up first", icon='CHECKMARK')

    def execute(self, context):
        plan = self._plan
        if plan is None:                       # run from a script, no dialog
            plan, error = buildInstallPlan(context)
            if plan is None:
                self.report({'ERROR'}, error)
                return {'CANCELLED'}
        self._plan = None
        if plan.blocked():
            for message in plan.errors:
                self.report({'ERROR'}, message)
            showResultsPopup(context, "Install cancelled", plan.results())
            return {'CANCELLED'}
        results = bmdb_install.applyInstall(plan)
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        for level, message in results:
            self.report({level}, message)
        failed = [r for r in results if r[0] == 'ERROR']
        exportSettings(context).install_summary = ("failed" if failed else "installed as '%s'" % plan.final_name)
        if not failed:
            results.append(('INFO', "Run Read Mod Data to see '%s' in the BMDB list" % plan.final_name))
        showResultsPopup(context, "Install: %s" % planSummary(plan), results)
        return {'CANCELLED'} if failed else {'FINISHED'}


class MED_2_TOOLKIT_OT_BMDB_Suggest_Name(bpy.types.Operator):
    bl_idname = "medieval2toolkit.bmdb_suggest_name"
    bl_label = "Suggest Free Name"
    bl_description = "Fill in the first entry name this mod's battle_models.modeldb does not already use."

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        export_data = exportSettings(context)
        base = (export_data.bmdb_entry_name or export_data.export_glb_name).strip().lower()
        if not base:
            self.report({'ERROR'}, "Set an entry name (or a mesh name) first")
            return {'CANCELLED'}
        taken = bmdbEntryNames(bpy.path.abspath(selectedModFolder(context)))
        if taken is None:
            self.report({'ERROR'}, "No battle_models.modeldb found in the selected mod")
            return {'CANCELLED'}
        export_data.install_new_name = modeldb.uniqueName(base, taken)
        self.report({'INFO'}, "New entry name set to '%s'" % export_data.install_new_name)
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
# a progress bar. The watching itself lives in tasks/iwte_run.py, which the
# strat export uses as well.
_iwte_job = None


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
            return self.finish(context, waitForIWTEJob(result))
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
        if iwteOutputReady(job):
            return self.stop(context, True)
        if job['process'].poll() is None:
            return {'RUNNING_MODAL'}
        # process gone: keep watching the folder, IWTE writes the mesh late
        if job.get('exit_time') is None:
            job['exit_time'] = time.time()
        if time.time() - job['exit_time'] < IWTE_OUTPUT_TIMEOUT:
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


class MED_2_TOOLKIT_OT_Browse_Task_Template(bpy.types.Operator):
    bl_idname = "medieval2toolkit.browse_task_template"
    bl_label = "Browse Task Template"
    bl_description = ("Pick this rig's IWTE task file. The browser opens inside the IWTE "
                      "tasks folder (the IWTE path's iwte_tasks subfolder) when it exists")
    bl_options = {'REGISTER', 'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default="*.txt", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return exportSettings(context) is not None

    def invoke(self, context, event):
        export_data = exportSettings(context)
        current = export_data.iwte_task_template.strip('"').strip("'") if export_data.iwte_task_template else ""
        if current and not iwte_tasks.isSampleTask(current):
            # already picked one of their own: reopen where that file lives
            self.filepath = current
        else:
            reader = context.scene.med2_toolkit_reader
            iwte_root = bpy.path.abspath(reader.directory_iwte) if reader.directory_iwte else ""
            tasks_dir = os.path.join(iwte_root, "iwte_tasks") if iwte_root else ""
            if not os.path.isdir(tasks_dir):
                # no IWTE tasks folder: start in the bundled samples instead
                tasks_dir = str(iwte_tasks.sampleTasksFolder())
            if os.path.isdir(tasks_dir):
                # trailing separator makes Blender open inside the folder
                self.filepath = os.path.join(tasks_dir, "")
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        export_data = exportSettings(context)
        if export_data is not None and self.filepath:
            # keep the sample dropdown in step: browsing to one of the bundled
            # files pins that sample, anything else is a custom file
            if iwte_tasks.isSampleTask(self.filepath):
                export_data.iwte_task_sample = os.path.basename(self.filepath)
            else:
                export_data.iwte_task_sample = 'custom'
            export_data.iwte_task_template = self.filepath
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Open_Sample_Tasks(bpy.types.Operator):
    bl_idname = "medieval2toolkit.open_sample_tasks"
    bl_label = "Open Sample Task Folder"
    bl_description = ("Open the addon's iwte_tasks folder, holding the sample task file for each "
                      "skeleton. Copy one out to edit it - the folder is replaced on addon update")
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        open_folder(str(iwte_tasks.sampleTasksFolder()))
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
        col.prop(export_data, "export_glb_name")

        layout.operator("medieval2toolkit.select_cleanup", icon='CHECKMARK')
        layout.prop(export_data, "select_wrong_uv")
        layout.operator("medieval2toolkit.auto_assign_uv", icon='UV')

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
        main_mat = bpy.data.materials.get(export_data.material_main) if export_data.material_main != 'none' else None
        if main_mat:
            col.prop(main_mat, "name", text="Rename", icon='MATERIAL')
        else:
            col.label(text="No main material - run Check Model for Export or pick one", icon='ERROR')
        col.separator()
        col.prop(export_data, "material_attach", text="Attach")
        attach_mat = bpy.data.materials.get(export_data.material_attach) if export_data.material_attach != 'none' else None
        if attach_mat:
            col.prop(attach_mat, "name", text="Rename", icon='MATERIAL')

        main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
        attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

        # offer Force Textures when a .NNN numbered duplicate of a selected
        # material is present in the export set
        keeper_bases = {baseName(m.name) for m in (main_mat, attach_mat) if m}
        numbered_dupes = sorted({
            m.name for m in materials
            if "." in m.name and m.name.split(".")[-1].isdigit()
            and m.name.rsplit(".", 1)[0] in keeper_bases
            and m not in (main_mat, attach_mat)
        })
        if numbered_dupes:
            box = layout.box()
            box.label(text="Duplicate materials: %s" % ", ".join(numbered_dupes), icon='ERROR')
            box.operator("medieval2toolkit.force_textures", icon='MATERIAL', text="Force Textures")

        layout.separator()
        layout.label(text="Output Names:")
        grid = layout.column(align=True)

        header = grid.row(align=True)
        header_split = header.split(factor=0.45, align=True)
        header_split.label(text="Current output names")
        header_split.label(text="New output names (blank = current)")

        def image_row(label, image, prop_name, current=None, icon=None):
            row = grid.row(align=True)
            split = row.split(factor=0.45, align=True)
            current = current or (image.name if image else "missing")
            split.label(text="%s: %s" % (label, current),
                        icon=icon or ('IMAGE_DATA' if image else 'X'))
            split.prop(export_data, prop_name, text="")

        def normal_row(label, material, image, prop_name, file_prop):
            """The normal map row, plus a file picker when the material has no
            normal map of its own - pointing at one made in an image editor is
            the alternative to the blank normal map below."""
            picked = "" if image else normalFileName(getattr(export_data, file_prop))
            image_row(label, image, prop_name,
                      current=picked or None,
                      icon='FILE_IMAGE' if picked else None)
            if material and image is None:
                grid.prop(export_data, file_prop, text="%s File" % label)

        image_row("Main", main_diff, "out_main")
        normal_row("Main Normal", main_mat, main_norm, "out_main_norm", "norm_main_file")
        if attach_mat:
            image_row("Attach", attach_diff, "out_attach")
            normal_row("Attach Normal", attach_mat, attach_norm, "out_attach_norm", "norm_attach_file")

        layout.prop(export_data, "ignore_diffuse_alpha")

        # only offered for a slot with neither a normal map in the material nor
        # a file pointed at - a browsed file is used instead of a blank one
        if ((main_mat and not main_norm and not export_data.norm_main_file)
                or (attach_mat and not attach_norm and not export_data.norm_attach_file)):
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

        layout.prop(export_data, "bmdb_mode", expand=True)
        mesh_name = export_data.export_glb_name or "<mesh name>"
        if export_data.bmdb_mode != 'install':
            layout.label(text="Export writes %s_bmdb.txt to paste in by hand" % mesh_name, icon='FILE_TEXT')
        if export_data.bmdb_mode != 'txt':
            layout.label(text="Written into the mod from the Install to Mod panel", icon='EXPORT')

        row = layout.row(align=True)
        row.prop(export_data, "bmdb_entry_name", text="Entry Name")
        row.operator("medieval2toolkit.copy_mesh_name", text="Copy Mesh Name")
        # entry name falls back to the mesh name, same as the BMDB writer
        entry_name = export_data.bmdb_entry_name or export_data.export_glb_name
        if entry_name:
            existing = bmdbEntryNames(bpy.path.abspath(selectedModFolder(context)))
            if existing is not None and entry_name.lower() in existing:
                layout.label(text="BMDB entry '%s' already exists in this mod" % entry_name, icon='ERROR')

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

        layout.separator()
        # works in every mode - planning writes nothing, and "does this clash
        # with the mod?" is worth asking before pasting an entry in by hand too
        layout.operator("medieval2toolkit.bmdb_check_install", icon='VIEWZOOM')

        if export_data.bmdb_mode != 'txt':
            drawInstallSection(layout, context, export_data)


def drawInstallSection(layout, context, export_data):
    """The write-into-the-mod half of the BMDB Entry panel: what the mod already
    has under this name, how a clash is handled, and the probe/install buttons.

    This used to be a panel of its own at the bottom of the export section, which
    meant the mode switch said "Install to Mod" in one place and everything it
    controlled lived in another.
    """
    layout.separator()
    box = layout.box()
    # writing into a mod is an object-mode job, same rule the Export panel uses
    box.enabled = context.mode == 'OBJECT'
    box.label(text="Install to Mod", icon='EXPORT')
    mod_folder = bpy.path.abspath(selectedModFolder(context))
    box.label(text="Mod: %s" % os.path.basename(os.path.dirname(mod_folder.rstrip("\\/")) or mod_folder),
              icon='FILE_FOLDER')
    relative = parseRelativeUnitPath(export_data.bmdb_unit_path) if export_data.bmdb_unit_path else ""
    if not relative:
        box.label(text="Set a Mesh Path above first", icon='ERROR')
        return
    box.label(text="Files go to data/%s" % relative, icon='FILE_FOLDER')

    entry_name = export_data.bmdb_entry_name or export_data.export_glb_name
    # cached by file mtime, so this stays cheap on every redraw - the full parse
    # only ever happens inside the probe and install operators
    existing = bmdbEntryNames(mod_folder)
    if existing is None:
        box.label(text="No battle_models.modeldb in this mod", icon='CANCEL')
        return
    clash = entry_name and entry_name.lower() in existing

    col = box.column(align=True)
    if clash:
        col.label(text="Entry '%s' already exists in this mod" % entry_name, icon='ERROR')
        col.prop(export_data, "install_on_conflict", text="If it exists")
        if export_data.install_on_conflict == bmdb_install.CONFLICT_RENAME:
            row = col.row(align=True)
            row.prop(export_data, "install_new_name", text="Add as")
            row.operator("medieval2toolkit.bmdb_suggest_name", icon='FILE_REFRESH', text="")
    else:
        col.label(text="Entry '%s' is new to this mod" % entry_name, icon='CHECKMARK')

    col = box.column(align=True)
    col.prop(export_data, "install_asset_conflict", text="If a file exists")
    col.prop(export_data, "install_backup")
    if export_data.install_backup:
        col.label(text="A .bak of the modeldb is kept in the mod", icon='FILE_BACKUP')
        col.label(text="and with the exported files, to revert to")

    # no second Probe button here: it is right above this box, in every mode
    box.operator("medieval2toolkit.bmdb_install", icon='EXPORT')
    if export_data.install_summary:
        box.label(text="Last probe: %s" % export_data.install_summary, icon='INFO')


def drawSampleTasks(layout, context, export_data):
    """The bundled sample task files: one per QOL skeleton, auto-picked for a
    rig that was parented to one of them."""
    box = layout.box()
    box.label(text="Sample Task Files", icon='PRESET')
    samples = iwte_tasks.sampleTaskFiles()
    if not samples:
        box.label(text="No sample task files in the addon's iwte_tasks folder", icon='ERROR')
        return
    box.prop(export_data, "iwte_task_sample", text="Sample")

    choice = export_data.iwte_task_sample
    template = export_data.iwte_task_template
    if choice == 'auto':
        auto_path, skeleton = iwte_tasks.autoSampleTask(activeExportArmature(context))
        if template and not iwte_tasks.isSampleTask(template):
            box.label(text="Own task file in use - pick a sample to replace it", icon='FILE_TEXT')
        elif auto_path:
            box.label(text="Rigged to %s: %s" % (skeleton, os.path.basename(auto_path)), icon='ARMATURE_DATA')
        elif skeleton:
            box.label(text="No sample task file for the %s skeleton" % skeleton, icon='ERROR')
        else:
            box.label(text="Not on a QOL skeleton - pick a sample or browse", icon='INFO')
    elif choice == 'custom':
        if template:
            box.label(text="Using %s" % os.path.basename(template.strip('"').strip("'")), icon='FILE_TEXT')
        else:
            box.label(text="Browse to a task file above", icon='INFO')
    else:
        box.label(text="Using the %s sample" % iwte_tasks.sampleTaskLabel(choice), icon='FILE_TEXT')
    box.operator("medieval2toolkit.open_sample_tasks", icon='FILE_FOLDER')


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
        if export_data.generate_bmdb and export_data.bmdb_mode in {'txt', 'both'}:
            layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT', text="Export GLB + Convert Textures + BMDB")
        else:
            layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT')
        if export_data.last_export_dir:
            layout.operator("medieval2toolkit.open_export_folder", icon='FILE_FOLDER')
        layout.separator()
        layout.label(text="IWTE")
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(export_data, "iwte_task_template", text="Task Template")
        row.operator("medieval2toolkit.browse_task_template", icon='FILEBROWSER', text="")
        if export_data.iwte_task_template:
            file_name = os.path.basename(export_data.iwte_task_template.strip('"').strip("'"))
            col.label(text="IWTE task file selected: %s" % file_name, icon='FILE_TEXT')
        else:
            fallback = defaultTaskTemplate(context.scene.med2_toolkit_reader)
            if fallback:
                file_name = os.path.basename(fallback.strip('"').strip("'"))
                col.label(text="If blank, uses recent task file: %s" % file_name, icon='FILE_TEXT')
        drawSampleTasks(layout, context, export_data)
        if _iwte_job is not None:
            elapsed = time.time() - _iwte_job['start']
            verb = "Converting" if _iwte_job['process'].returncode is None else "Waiting for"
            layout.progress(factor=iwteProgress(elapsed), type='BAR',
                            text="%s %s... %ds" % (verb, _iwte_job['output_name'], int(elapsed)))
        else:
            layout.operator("medieval2toolkit.export_unit_iwte_mesh", icon='MOD_ARMATURE')
        if context.mode != 'OBJECT':
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Export_Faction,
    MED_2_TOOLKIT_Unit_Export_Data,
    MED_2_TOOLKIT_OT_Select_Cleanup,
    MED_2_TOOLKIT_OT_Force_Textures,
    MED_2_TOOLKIT_OT_Auto_Assign_UV,
    MED_2_TOOLKIT_OT_Export_Factions_Refresh,
    MED_2_TOOLKIT_OT_Export_Factions_Set,
    MED_2_TOOLKIT_OT_Export_Faction_Toggle,
    MED_2_TOOLKIT_OT_Copy_Mesh_Name,
    MED_2_TOOLKIT_OT_Copy_Sprite_Footer,
    MED_2_TOOLKIT_OT_BMDB_Load_Entry,
    MED_2_TOOLKIT_OT_BMDB_Check_Install,
    MED_2_TOOLKIT_OT_BMDB_Install,
    MED_2_TOOLKIT_OT_BMDB_Suggest_Name,
    MED_2_TOOLKIT_OT_Export_Unit_GLB,
    MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh,
    MED_2_TOOLKIT_OT_Open_Export_Folder,
    MED_2_TOOLKIT_OT_Browse_Task_Template,
    MED_2_TOOLKIT_OT_Open_Sample_Tasks,
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
