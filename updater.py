"""Release controls shared by the sidebar and addon preferences."""
from pathlib import Path
import queue
import tempfile
import threading
import bpy
from . import update_core

_results = queue.Queue()
_busy = False
_active = False
_release = None
_restart = False
_message = 'Check GitHub for a newer version'
_error = False
_generation = 0


def current_version():
    from . import bl_info
    return tuple(bl_info['version'])


def online():
    return getattr(bpy.app, 'online_access', True)


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def start(install=False):
    global _busy, _message, _error
    if _busy or _restart or not _active:
        return
    if not online():
        _message = 'Enable Online Access in Blender Preferences > System'
        _error = True
        return
    _busy, _error = True, False
    _message = 'Downloading update...' if install else 'Checking GitHub...'
    generation = _generation
    release = _release
    blender_version = tuple(bpy.app.version)

    def worker():
        try:
            if install:
                # All network/extraction work stays off Blender's main thread.
                work = tempfile.TemporaryDirectory(prefix='med2-update-', dir=Path(__file__).parent.parent)
                try:
                    archive = Path(work.name) / 'release.zip'
                    update_core.download_release(release, archive)
                    staged = update_core.stage_archive(archive, Path(work.name) / 'stage',
                                                       release['version'], blender_version)
                    _results.put((generation, 'install', (work, staged)))
                except Exception:
                    work.cleanup()
                    raise
            else:
                _results.put((generation, 'check', update_core.latest_release()))
        except Exception as exc:
            _results.put((generation, 'error', str(exc)))

    threading.Thread(target=worker, daemon=True).start()
    redraw()


def poll_results():
    global _busy, _message, _release, _restart, _error
    while True:
        try:
            generation, kind, value = _results.get_nowait()
        except queue.Empty:
            break
        if not _active or generation != _generation:
            if generation == _generation:
                _busy = False
            if kind == 'install':
                value[0].cleanup()
            continue
        _busy = False
        if kind == 'error':
            _message, _error = 'Update failed: ' + value, True
        elif kind == 'check':
            _release = value
            latest = '.'.join(map(str, value['version']))
            _message = ('New version: ' + latest if value['version'] > current_version()
                        else 'Up to date' if value['version'] == current_version()
                        else 'Installed version is newer than the latest release')
        else:
            work, staged = value
            try:
                backup = update_core.install_staged(staged, Path(__file__).parent)
                _restart = True
                _message = 'Update installed. Save your work and restart Blender.'
                print('Toolkit update backup:', backup)
            except Exception as exc:
                _message, _error = 'Update failed: ' + str(exc), True
            finally:
                work.cleanup()
        redraw()
    return 0.25 if _active or _busy else None


def draw(layout):
    box = layout.box()
    box.label(text='Toolkit v' + '.'.join(map(str, current_version())))
    message = _message if online() else 'Enable Online Access in Preferences > System'
    # Sidebar widths vary; keep status/error messages readable in narrow panels.
    import textwrap
    for line in textwrap.wrap(message, width=38):
        box.label(text=line, icon='ERROR' if _error else 'INFO')
    row = box.row(align=True)
    row.enabled = not _busy and not _restart and online()
    row.operator('medieval2toolkit.check_update', icon='FILE_REFRESH')
    if _release and _release['version'] > current_version():
        row.operator('medieval2toolkit.install_update', icon='IMPORT')


class MED2_OT_Check_Update(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.check_update'
    bl_label = 'Check for Updates'
    bl_description = 'Check the latest published stable toolkit release on GitHub'

    def execute(self, context):
        start()
        return {'FINISHED'}


class MED2_OT_Install_Update(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.install_update'
    bl_label = 'Update Toolkit'
    bl_description = 'Download and install the latest release, keeping settings and saved poses; restart Blender afterwards'

    @classmethod
    def poll(cls, context):
        return (not _busy and not _restart and online() and _release is not None
                and _release['version'] > current_version())

    def execute(self, context):
        start(install=True)
        return {'FINISHED'}


classes = (MED2_OT_Check_Update, MED2_OT_Install_Update)


def register():
    global _active, _generation, _busy
    _active = True
    _generation += 1
    _busy = False
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.timers.is_registered(poll_results):
        bpy.app.timers.register(poll_results, first_interval=0.25, persistent=True)


def unregister():
    global _active
    _active = False
    # Keep draining a pending worker so staged temporary files are cleaned up.
    if not _busy and bpy.app.timers.is_registered(poll_results):
        bpy.app.timers.unregister(poll_results)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
