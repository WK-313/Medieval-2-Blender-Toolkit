"""Base game and Kingdoms DLC as import sources.

Both keep their EDU, modeldb, meshes and textures in packs, so Read Mod Data
and the built-in importer have to read them out of packs/*.pack. Checks: the
Mod dropdown lists 'Base game' and 'DLC: Kingdoms - Crusades', Read Mod Data
fills the unit list from each, and one foot unit and one mounted unit of each
import with textures into their own unit folder.
"""
import importlib, json, os, shutil, sys, tempfile
from pathlib import Path
import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent) if (candidate / 'm2formats').is_dir())
game = Path(os.environ.get('MED2_GAME_ROOT', 'C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War'))

with tempfile.TemporaryDirectory(prefix='base_dlc_') as temporary:
    temp = Path(temporary)
    source = temp / 'test_addon'
    shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '.git', '.github', 'images'))
    sys.path.insert(0, str(temp))
    addon = importlib.import_module('test_addon')
    addon.register()
    try:
        edu = importlib.import_module('test_addon.panels.edu_panel')
        edu.showResultsPopup = lambda *a: None
        mod_data = importlib.import_module('test_addon.panels.mod_data')
        reader = bpy.context.scene.med2_toolkit_reader
        reader.directory_med2 = str(game)
        output = temp / 'output'
        reader.directory_models = str(output); reader.directory_iwte = str(temp / 'NO_IWTE')
        reader.backend_battle_import = 'BUILTIN'
        units = bpy.context.scene.med2_toolkit_units
        units.hide_toggle = False; units.frame_toggle = False; units.textured_toggle = False
        units.primary_secondary = 'primary'

        assert bpy.ops.medieval2toolkit.refresh_mods() == {'FINISHED'}
        labels = {identifier: label for identifier, label, _ in mod_data.modList(None, bpy.context)}
        print('  dropdown:', sorted(labels.values()), flush=True)
        base = next(k for k, v in labels.items() if v == 'Base game')
        crusades = next(k for k, v in labels.items() if v == 'DLC: Kingdoms - Crusades')
        print('PASS Mod dropdown lists Base game and the Crusades DLC', flush=True)

        for name, folder in (('Base game', base), ('Crusades', crusades)):
            reader.mods_filtered = folder
            try:
                bpy.ops.medieval2toolkit.reader()
            except RuntimeError as error:   # settlement PKGs are not part of this
                print('  reader reported:', str(error).splitlines()[0], flush=True)
            dictionary = json.loads((source / 'text/unit_dictionary.json').read_text(encoding='utf-8'))
            models = json.loads((source / 'text/model_dictionary.json').read_text(encoding='utf-8'))
            assert len(dictionary) > 50 and len(models) > 50, (name, len(dictionary), len(models))
            print('PASS %s Read Mod Data: %d units, %d models' % (name, len(dictionary), len(models)), flush=True)
            picks = {}
            for kind in ('foot', 'mounted'):
                for unit in dictionary.values():
                    mounted = unit['Attachment'] != 'unused' and unit['Attachment'][0] == 'mount'
                    if (kind == 'mounted') != mounted or not unit['Model'] or unit['Attachment'] != 'unused' and not mounted:
                        continue
                    owners = unit['Owners'].get('ownership', [])
                    if not owners:
                        continue
                    try:
                        units.import_faction = owners[0]
                        units.import_unit = json.dumps(unit)
                    except TypeError:          # a culture, not a faction; or a ship
                        continue
                    units.single_import_upgrades = (True, False, False, False)
                    before = set(bpy.data.objects)
                    try:
                        bpy.ops.medieval2toolkit.unit_importer()
                    except RuntimeError as error:
                        print('  skip %s: %s' % (unit['ID'], str(error).splitlines()[0]), flush=True)
                        continue
                    rigs = [o for o in set(bpy.data.objects) - before if o.type == 'ARMATURE']
                    if len(rigs) != (2 if mounted else 1):
                        print('  skip %s: %d rigs' % (unit['ID'], len(rigs)), flush=True)
                        continue
                    picks[kind] = unit['ID']
                    break
                assert kind in picks, '%s: no %s unit imported' % (name, kind)
                folder_out = edu.unitFolder(str(output), picks[kind])
                glbs = list(Path(folder_out).glob('*.glb'))
                dds = list((Path(folder_out) / 'textures').glob('*.dds'))
                assert glbs and dds, (folder_out, glbs, dds)
                print('PASS %s %s unit %s: %d glb, %d textures in its folder'
                      % (name, kind, picks[kind], len(glbs), len(dds)), flush=True)
    finally:
        addon.unregister()
