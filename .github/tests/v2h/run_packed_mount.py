"""Built-in import of a model whose mesh exists only in the base game's
packs/*.pack (DaC mount_heavy_horse, mount_camel). Failed before with
'Unpacked mesh not found'; the importer now reads it out of the pack."""
import importlib, os, shutil, sys, tempfile
from pathlib import Path
import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    c for p in Path(__file__).resolve().parents for c in (p / 'Medieval-2-Toolkit-main', p) if (c / 'm2formats').is_dir())
game = Path(os.environ.get('MED2_GAME_ROOT', 'C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War'))
data = Path(os.environ.get('MED2_MOD_DATA', str(game / 'mods/Divide_and_Conquer_EUR/data')))
failures = []
with tempfile.TemporaryDirectory(prefix='packed_mount_') as temporary:
    temp = Path(temporary)
    shutil.copytree(SOURCE, temp / 'test_addon', ignore=shutil.ignore_patterns('__pycache__', '.git', '.github', 'text', 'images', 'graphify-out'))
    sys.path.insert(0, str(temp))
    addon = importlib.import_module('test_addon')
    addon.register()
    try:
        bridge = importlib.import_module('test_addon.tasks.battle_import')
        reader = bpy.context.scene.med2_toolkit_reader
        reader.mods_filtered = 'custom'; reader.directory_mod_data = str(data); reader.directory_med2 = str(game)
        reader.directory_models = str(temp / 'output'); reader.backend_battle_import = 'BUILTIN'
        (temp / 'output').mkdir()
        for model_id in ('mount_heavy_horse', 'mount_camel'):
            root, vanilla, entry, path = bridge.sources(bpy.context, model_id, 'england')
            loose = any((r / entry.lods[0][0]).is_file() for r in (data, game / 'data'))
            if loose:
                failures.append('%s: mesh is loose, test does not exercise packs' % model_id); continue
            before = set(bpy.data.objects)
            bridge.importModel(bpy.context, model_id, model_id, 'england', str(temp / 'output'))
            new = [o for o in bpy.data.objects if o not in before]
            meshes = [o for o in new if o.type == 'MESH']; rigs = [o for o in new if o.type == 'ARMATURE']
            ok = len(rigs) == 1 and meshes and all(len(m.data.vertices) for m in meshes)
            print('%s %s: from %s, %d rig, %d mesh parts' % ('PASS' if ok else 'FAIL', model_id, path, len(rigs), len(meshes)), flush=True)
            if not ok:
                failures.append(model_id)
    except Exception as error:
        failures.append('%s: %s' % (type(error).__name__, error))
    finally:
        addon.unregister()
if failures:
    print('FAIL', failures); sys.exit(1)
print('PASS all')
