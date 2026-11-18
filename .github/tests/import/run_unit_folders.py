"""Per-unit output folders: <Unit Output>/<unit id>/<mesh>.glb + textures/.

Built-in: Import Unit writes the mesh and its textures into the unit's own
folder, nothing goes to .med2-native, and two units never share a texture
folder. IWTE: a batch writes one task per unit, each with <directory_out> set
to that unit's folder and listing only that unit's models.
"""
import importlib, json, os, shutil, sys, tempfile
from pathlib import Path
import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent) if (candidate / 'm2formats').is_dir())
game = Path(os.environ.get('MED2_GAME_ROOT', 'C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War'))
data = Path(os.environ.get('MED2_ANIMATION_DATA', str(game / 'mods/Divide_and_Conquer_EUR/data')))

with tempfile.TemporaryDirectory(prefix='unit_folders_') as temporary:
    temp = Path(temporary)
    source = temp / 'test_addon'
    shutil.copytree(SOURCE, source, ignore=shutil.ignore_patterns('__pycache__', '.git', '.github', 'text', 'images'))
    sys.path.insert(0, str(temp))
    addon = importlib.import_module('test_addon')
    addon.register()
    try:
        imp = importlib.import_module('test_addon.tasks.importer')
        edu = importlib.import_module('test_addon.panels.edu_panel')
        edu.showResultsPopup = lambda *a: None
        output = temp / 'output'
        reader = bpy.context.scene.med2_toolkit_reader
        reader.mods_filtered = 'custom'; reader.directory_mod_data = str(data); reader.directory_med2 = str(game)
        reader.directory_models = str(output); reader.directory_iwte = str(temp / 'iwte')
        reader.backend_battle_import = 'BUILTIN'
        units = bpy.context.scene.med2_toolkit_units
        units.hide_toggle = False; units.frame_toggle = False; units.textured_toggle = False
        units.primary_secondary = 'primary'; units.import_filter = 'ownership'

        assert imp.unitFolder('C:\\out', 'a:b/c?') == 'C:\\out\\a_b_c_\\'
        assert imp.unitFolder('C:/out/', 'Dunedain Rangers') == 'C:/out/Dunedain Rangers/'
        print('PASS unitFolder: separator style kept, illegal characters replaced', flush=True)

        unit = {'ID': 'Native test', 'Type': 'Native test', 'Model': ['citadel_guard2'], 'Attachment': 'unused',
                'Officers': [], 'Owners': {'ownership': ['sicily']}}
        other = dict(unit, ID='Other unit', Type='Other unit')
        files = {'available_factions.json': {'Sicily': 'sicily'},
                 'unit_dictionary.json': {'Native test': unit, 'Other unit': other},
                 'attachment_dictionary.json': {},
                 'model_dictionary.json': {'citadel_guard2': {'Mesh': 'citadel_guard2_lod0.glb', 'Folder': 'unused',
                                                                 'Textures': {'sicily': ['unused.dds', 'unused.dds']}}}}
        for name, contents in files.items():
            (source / 'text' / name).write_text(json.dumps(contents), encoding='utf-8')
        units.import_faction = 'sicily'; units.single_import_upgrades = (True, False, False, False)
        for info in (unit, other):
            units.import_unit = json.dumps(info)
            assert bpy.ops.medieval2toolkit.unit_importer() == {'FINISHED'}
        for info in (unit, other):
            folder = output / info['ID']
            glbs = [p.name for p in folder.glob('*.glb')]
            dds = sorted(p.name for p in (folder / 'textures').glob('*.dds'))
            assert glbs == ['citadel_guard2_lod0.glb'], glbs
            assert dds, 'no textures in %s' % folder
            assert not any(p.is_dir() for p in (folder / 'textures').iterdir()), 'hash folders left'
            print('  %s: %s + textures/%s' % (info['ID'], glbs[0], dds), flush=True)
        assert not (output / '.med2-native').exists()
        assert sorted(p.name for p in output.iterdir()) == ['Native test', 'Other unit']
        rigs = [o for o in bpy.data.objects if o.get('med2_battle_import_backend') == 'BUILTIN']
        assert len(rigs) == 2
        paths = {Path(bpy.path.abspath(node.image.filepath)).resolve()
                 for rig in rigs for o in rig.children_recursive if o.type == 'MESH'
                 for mat in o.data.materials for node in mat.node_tree.nodes if node.type == 'TEX_IMAGE' and node.image}
        assert paths and all(p.is_file() and p.parent.name == 'textures' and p.parent.parent.parent == output.resolve()
                             for p in paths), paths
        print('PASS built-in: each unit has its own mesh .glb + textures/, materials load from there, no .med2-native', flush=True)

        shutil.rmtree(output)
        units.faction_import_officers = False
        assert bpy.ops.medieval2toolkit.faction_importer() == {'FINISHED'}
        assert edu._import_job is None
        assert sorted(p.name for p in output.iterdir()) == ['Native test', 'Other unit'], list(output.iterdir())
        assert all((output / name / 'citadel_guard2_lod0.glb').is_file() for name in ('Native test', 'Other unit'))
        print('PASS built-in faction batch: one folder per unit', flush=True)

        # IWTE batch: one task per unit, directory_out = that unit's folder
        reader.backend_battle_import = 'IWTE'
        (temp / 'iwte' / 'iwte_tasks').mkdir(parents=True)
        conversions = edu.prepareConversions(str(output) + os.sep, [dict(unit, ID='Iwte A'), dict(unit, ID='Iwte B')], False)
        assert [c['folder'] for c in conversions] == [imp.unitFolder(str(output), 'Iwte A'), imp.unitFolder(str(output), 'Iwte B')], conversions
        for conversion in conversions:
            edu.writeConversionTask(conversion)
            task = (temp / 'iwte' / 'iwte_tasks' / 'toolkit_bmdb_task.txt').read_text()
            line = next(l for l in task.splitlines() if l.startswith('<directory_out>'))
            assert conversion['folder'].rstrip('\\/') in line, line
            assert task.rstrip().endswith('<modeldb_type_name_list>\ncitadel_guard2'), task
            assert Path(conversion['folder']).is_dir()
            assert conversion['expected'] == [Path(conversion['folder'] + 'citadel_guard2_lod0.glb')]
        print('PASS IWTE: one task per unit, directory_out is the unit folder, only its own models listed', flush=True)
    finally:
        addon.unregister()
