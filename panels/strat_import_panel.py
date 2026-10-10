"""Browse descr_model_strat entries and import their faction/LOD variants."""
from dataclasses import asdict
from pathlib import Path
import struct
import time
import zlib

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty

from ..m2formats.cas import CasError
from ..tasks.strat_reader import loadStratModels, resolveStratPath, selectStratTexture
from ..tasks.strat_importer import importStratCAS
from ..tasks.strat_iwte import (cleanupStratExtract, importStratExtract,
                                startStratExtract, waitStratExtract)
from ..tasks.unit_exporter import selectedModFolder
from ..tasks.iwte_run import (IWTE_OUTPUT_TIMEOUT, abortIWTEJob, finishIWTEJob,
                              iwteOutputReady, iwteProgress, iwteStalled,
                              redrawView3D)
from .unit_export_panel import askAboutStall, showResultsPopup

_enum_strings = {}
_import_job = None


def dataRoot(context):
    value = selectedModFolder(context).strip().strip('"')
    return Path(bpy.path.abspath(value)).resolve() if value else None


def selectedEntry(context):
    if context is None or not hasattr(context.scene, 'med2_toolkit_strat_browser'):
        return None
    settings = context.scene.med2_toolkit_strat_browser
    try:
        root = dataRoot(context)
        if root is None or str(root) != settings.data_root:
            return None
        if not 0 <= settings.active_index < len(settings.models):
            return None
        return loadStratModels(root).by_name().get(settings.models[settings.active_index].model_type.casefold())
    except (OSError, ValueError):
        return None


def factionItems(self, context):
    entry = selectedEntry(context)
    names = sorted(entry.textures, key=str.casefold) if entry else []
    # The explicit numeric values survive reordering in a descriptor or .blend.
    items = [(name, name, entry.textures[name], (zlib.crc32(name.encode()) & 0x3fffffff) + 1)
             for name in names]
    items = items or [('none', 'No faction texture', '', 0)]
    _enum_strings['factions'] = items
    return items


def lods(entry):
    return list(entry.models) + list(entry.shadows) if entry else []


def lodItems(self, context):
    items = []
    for index, lod in enumerate(lods(selectedEntry(context))):
        label = '%s: %s' % (lod.kind, Path(lod.path.replace('\\', '/')).name)
        if lod.distance:
            label += ' (%s)' % lod.distance
        items.append((str(index), label, lod.path, index))
    _enum_strings['lods'] = items or [('none', 'No model file', '', 0)]
    return _enum_strings['lods']


def selectionChanged(self, context):
    self.faction = factionItems(self, context)[0][0]
    self.lod = lodItems(self, context)[0][0]


class MED_2_TOOLKIT_Strat_Browser_Item(bpy.types.PropertyGroup):
    model_type: StringProperty()
    skeleton: StringProperty()


class MED_2_TOOLKIT_Strat_Browser(bpy.types.PropertyGroup):
    models: CollectionProperty(type=MED_2_TOOLKIT_Strat_Browser_Item)
    active_index: IntProperty(default=0, update=selectionChanged)
    data_root: StringProperty()
    search: StringProperty(name='Search', description='Filter by model type or skeleton')
    faction: EnumProperty(name='Faction', items=factionItems)
    lod: EnumProperty(name='LOD', items=lodItems)


class MED_2_TOOLKIT_UL_Strat_Models(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.model_type, icon='OUTLINER_OB_ARMATURE')

    def filter_items(self, context, data, propname):
        terms = data.search.casefold().split()
        flags = [self.bitflag_filter_item if all(term in (item.model_type + ' ' + item.skeleton).casefold()
                                                for term in terms) else 0
                 for item in getattr(data, propname)]
        return flags, []


class MED_2_TOOLKIT_OT_Strat_Load_Models(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.strat_load_models'
    bl_label = 'Load Strat Models'
    bl_description = "Read the selected mod's descr_model_strat.txt"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            root = dataRoot(context)
            if root is None:
                raise ValueError('Select a mod data folder in Paths first')
            document = loadStratModels(root)
        except (OSError, ValueError) as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        settings = context.scene.med2_toolkit_strat_browser
        settings.models.clear()
        settings.data_root = str(root)
        for entry in sorted(document.by_name().values(), key=lambda entry: entry.type.casefold()):
            item = settings.models.add()
            item.model_type = entry.type
            item.skeleton = entry.skeleton
        settings.active_index = 0
        selectionChanged(settings, context)
        report = [('WARNING', message) for message in document.diagnostics]
        report.append(('INFO', 'Loaded %d strat model types' % len(settings.models)))
        showResultsPopup(context, 'Strat models', report)
        self.report({'INFO'}, report[-1][1])
        return {'FINISHED'}


def selectedImport(context):
    entry = selectedEntry(context)
    if entry is None:
        raise ValueError('Load Strat Models for the selected mod and choose a type first')
    settings = context.scene.med2_toolkit_strat_browser
    if entry.textures and settings.faction.casefold() not in {name.casefold() for name in entry.textures}:
        raise ValueError('Choose an available faction texture first')
    models = lods(entry)
    try:
        index = int(settings.lod)
        if not 0 <= index < len(models):
            raise ValueError()
        model = models[index]
    except (ValueError, IndexError):
        raise ValueError('Choose an available model LOD first') from None
    reader = context.scene.med2_toolkit_reader
    vanilla = Path(bpy.path.abspath(reader.directory_med2)) / 'data'
    root = dataRoot(context)
    path = resolveStratPath(root, model.path, vanilla_data_root=vanilla)
    if path is None:
        raise ValueError('Model file not found in mod or vanilla data: %s' % model.path)
    texture_name = selectStratTexture(entry, settings.faction)
    texture = resolveStratPath(root, texture_name, vanilla_data_root=vanilla, texture=True) if texture_name else None
    metadata = {'type': entry.type, 'skeleton': entry.skeleton, 'scale': entry.scale,
                'faction': settings.faction, 'lod': asdict(model), 'source_entry': asdict(entry),
                'data_root': str(root)}
    notes = []
    if texture_name and texture is None:
        notes.append(('WARNING', 'Texture not found: %s' % texture_name))
    # An explicit empty override prevents an unavailable faction texture from
    # silently falling back to an unrelated material embedded in the CAS.
    return path, texture if texture is not None else ('' if texture_name else None), metadata, notes


class MED_2_TOOLKIT_OT_Strat_Import(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.strat_import'
    bl_label = 'Import Strat Model'
    bl_description = 'Import the selected faction and LOD as an editable model; older CAS files can use IWTE'
    bl_options = {'REGISTER', 'UNDO'}
    _timer = None

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and _import_job is None and selectedEntry(context) is not None

    def execute(self, context):
        global _import_job
        try:
            path, texture, metadata, notes = selectedImport(context)
            reader = context.scene.med2_toolkit_reader
            if reader.backend_strat_import == 'BUILTIN':
                try:
                    report, rig = importStratCAS(context, path, metadata=metadata, texture_path=texture)
                    return self.reportImport(context, notes + report, rig)
                except CasError as error:
                    with open(path, 'rb') as source:
                        header = source.read(4)
                    version = struct.unpack('<f', header)[0] if len(header) == 4 else 0
                    if not 2.0 <= version < 3.0:
                        raise ValueError(str(error)) from error
                    notes.append(('WARNING', 'CAS %.2f is unsupported by the built-in reader; using IWTE' % version))
            job = startStratExtract(path, bpy.path.abspath(reader.directory_iwte))
            job.update(cas_path=path, texture_path=texture, metadata=metadata, notes=notes,
                       scene=context.scene)
            _import_job = job
        except (OSError, ValueError, RuntimeError) as error:
            showResultsPopup(context, 'Strat import', [('ERROR', str(error))])
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        if bpy.app.background or context.window is None:
            return self.finish(context, waitStratExtract(job))
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        job.update(timer=self._timer, window_manager=wm)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if _import_job is None:
            return {'CANCELLED'}
        if event.type == 'ESC':
            abortIWTEJob(_import_job)
            return self.stop(context, False)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        job = _import_job
        context.window_manager.progress_update(int(iwteProgress(time.time() - job['start']) * 100))
        redrawView3D(context)
        if iwteOutputReady(job):
            return self.stop(context, True)
        if job.get('aborted'):
            return self.stop(context, False)
        if job['process'].poll() is None:
            if iwteStalled(job):
                askAboutStall(context, job, 'The strat import')
        else:
            job.setdefault('exit_time', time.time())
            if time.time() - job['exit_time'] >= IWTE_OUTPUT_TIMEOUT:
                return self.stop(context, False)
        return {'RUNNING_MODAL'}

    def stop(self, context, success):
        if self._timer is not None:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        context.window_manager.progress_end()
        result = self.finish(context, success)
        redrawView3D(context)
        return result

    def cancel(self, context):
        _cancelImportJob()
        self._timer = None

    def finish(self, context, success):
        global _import_job
        job, _import_job = _import_job, None
        if job is None:
            return {'CANCELLED'}
        rig = None
        report = job['notes'] + job.get('version_warnings', [])
        try:
            report.append(finishIWTEJob(job, success))
            if success:
                if context.scene != job['scene'] or context.mode != 'OBJECT':
                    report.append(('ERROR', 'The scene or mode changed during extraction; return to Object Mode and import again'))
                else:
                    imported, rig = importStratExtract(context, job['output_path'], job['cas_path'],
                                                       job['metadata'], job['texture_path'])
                    report.extend(imported)
        except (OSError, ValueError, RuntimeError) as error:
            report.append(('ERROR', 'Strat import failed: %s' % error))
        finally:
            cleanupStratExtract(job)
        return self.reportImport(context, report, rig)

    def reportImport(self, context, report, rig):
        report.sort(key=lambda row: {'ERROR': 0, 'WARNING': 1, 'INFO': 2}.get(row[0], 2))
        showResultsPopup(context, 'Strat import', report)
        if rig is None:
            self.report({'ERROR'}, next((message for level, message in report if level == 'ERROR'), 'Strat import failed'))
            return {'CANCELLED'}
        self.report({'INFO'}, 'Imported strat model: %s' % rig.name)
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Strat_Import(bpy.types.Panel):
    bl_idname = 'MED_2_TOOLKIT_PT_Strat_Import'
    bl_parent_id = 'MED_2_TOOLKIT_PT_Main_Panel'
    bl_label = 'Strat Models'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Medieval 2 Toolkit'

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'strat'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_strat_browser
        layout.operator('medieval2toolkit.strat_load_models', icon='FILE_REFRESH')
        if not settings.models:
            layout.label(text='Load the selected mod\'s strat model list', icon='INFO')
            return
        layout.prop(settings, 'search', text='', icon='VIEWZOOM')
        layout.template_list('MED_2_TOOLKIT_UL_Strat_Models', '', settings, 'models', settings, 'active_index', rows=6)
        entry = selectedEntry(context)
        if entry is None:
            layout.label(text='Reload models for the selected mod', icon='INFO')
            return
        layout.label(text='Skeleton: %s' % (entry.skeleton or '(static)'))
        layout.label(text='Campaign scale: %g' % entry.scale)
        layout.prop(settings, 'faction')
        layout.prop(settings, 'lod')
        if _import_job is not None:
            layout.progress(factor=iwteProgress(time.time() - _import_job['start']), type='BAR', text='Extracting with IWTE... (Esc to cancel)')
        else:
            row = layout.row()
            row.enabled = context.mode == 'OBJECT'
            row.operator('medieval2toolkit.strat_import', icon='IMPORT')


classes = [MED_2_TOOLKIT_Strat_Browser_Item, MED_2_TOOLKIT_Strat_Browser,
           MED_2_TOOLKIT_UL_Strat_Models, MED_2_TOOLKIT_OT_Strat_Load_Models,
           MED_2_TOOLKIT_OT_Strat_Import]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.med2_toolkit_strat_browser = PointerProperty(type=MED_2_TOOLKIT_Strat_Browser)


def unregister():
    _cancelImportJob()
    del bpy.types.Scene.med2_toolkit_strat_browser
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


def _cancelImportJob():
    global _import_job
    job, _import_job = _import_job, None
    if job is None:
        return
    abortIWTEJob(job)
    wm, timer = job.get('window_manager'), job.get('timer')
    if wm is not None:
        if timer is not None:
            wm.event_timer_remove(timer)
        wm.progress_end()
    cleanupStratExtract(job)
