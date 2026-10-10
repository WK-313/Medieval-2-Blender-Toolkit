"""Exercise the production IWTE task writer/launcher against one real CAS."""
import importlib, importlib.util, os, pathlib, sys
import bpy

here = pathlib.Path(__file__).resolve()
source = pathlib.Path(os.environ['MED2_ADDON_SOURCE']) if 'MED2_ADDON_SOURCE' in os.environ else next(p for parent in here.parents for p in (parent / 'Medieval-2-Toolkit-main', parent) if (p / 'tasks' / 'strat_iwte.py').exists())
spec = importlib.util.spec_from_file_location('iwte_test_addon', source / '__init__.py', submodule_search_locations=[str(source)])
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
module = importlib.import_module('iwte_test_addon.tasks.strat_iwte')
data = pathlib.Path(os.environ.get('MED2_MOD_DATA', r'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods\Divide_and_Conquer_EUR\data'))
job = module.startStratExtract(data / 'models_strat' / 'dunedain_diplomat.cas', str(pathlib.Path(os.environ['MED2_IWTE_EXE']).parent))
try:
    assert module.waitStratExtract(job, timeout=90), job.get('notes')
    print('PASS production IWTE task writer and launcher produce a fresh GLB', flush=True)
    output = pathlib.Path(job['temporary'].name) / 'model.glb'
    report, rig = module.importStratExtract(bpy.context, output, str(data / 'models_strat' / 'dunedain_diplomat.cas'), {}, '')
    assert rig is not None, report
    shapes = {bone.custom_shape for bone in rig.pose.bones if bone.custom_shape}
    model_meshes = [obj for obj in rig.children_recursive if obj.type == 'MESH']
    assert shapes and not (set(model_meshes) & shapes)
    assert sum(len(obj.data.polygons) for obj in model_meshes) == 2298
    print('PASS production IWTE import excludes custom bone display geometry', flush=True)
finally:
    module.cleanupStratExtract(job)
