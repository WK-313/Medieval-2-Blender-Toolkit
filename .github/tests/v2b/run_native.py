"""Headless v2b native import validation against real CAS input."""
import importlib, importlib.util, json, os, pathlib, shutil, sys, tempfile
import bpy
ROOT=pathlib.Path(__file__).resolve().parents[2]
ADDON=pathlib.Path(os.environ['MED2_ADDON_SOURCE']) if 'MED2_ADDON_SOURCE' in os.environ else next(p for parent in pathlib.Path(__file__).resolve().parents for p in (parent/'Medieval-2-Toolkit-main',parent) if (p/'tasks'/'strat_importer.py').exists())
OUTPUT=pathlib.Path(__file__).resolve().parent
DATA=pathlib.Path(os.environ.get('MED2_MOD_DATA',r'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods\Divide_and_Conquer_EUR\data'))
def check(value, message):
    if not value: raise AssertionError(message)
def snapshot():
    return {n:set(getattr(bpy.data,n)) for n in ('objects','meshes','armatures','materials','images','collections')}
with tempfile.TemporaryDirectory(prefix='v2b_test_') as tmp:
    dest=pathlib.Path(tmp)/'v2b_addon'
    shutil.copytree(ADDON,dest,ignore=shutil.ignore_patterns('__pycache__','.git'))
    spec=importlib.util.spec_from_file_location('v2b_addon',dest/'__init__.py',submodule_search_locations=[str(dest)])
    addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon);addon.register()
    imp=importlib.import_module('v2b_addon.tasks.strat_importer')
    cas=importlib.import_module('v2b_addon.m2formats.cas')
    summary=[]
    for kind in ('assassin','diplomat','spy','general'):
        path=DATA/'models_strat'/('dunedain_'+kind+'.cas')
        source=cas.read_cas(path)
        report,rig=imp.importStratCAS(bpy.context,path,metadata={'scale':2.7,'lod':0,'faction':'saxons'})
        check(rig is not None,str(report))
        meshes=[o for o in rig.children if o.type=='MESH']
        check(len(meshes)==len(source.objects),'mesh count')
        check(tuple(rig.scale)==(1,1,1),'descriptor scale baked into rig')
        check(json.loads(rig['med2_strat_import_metadata'])['scale']==2.7,'metadata scale')
        check(sum(len(o.data.polygons) for o in meshes)==source.triangles,'triangle count')
        world=cas.bind_world(source)
        for obj,raw in zip(meshes,source.objects):
            check(tuple(obj.scale)==(1,1,1),'scale baked into mesh')
            posed=cas.posed_positions(raw,world)
            for v in obj.data.vertices:
                x,y,z=posed[3*v.index:3*v.index+3]
                check(max(abs(a-b) for a,b in zip(v.co,(x,z,y)))<1e-6,'CAS bind position')
                if raw.skinned: check(len(v.groups)==1 and abs(v.groups[0].weight-1)<1e-6,'weight')
            for poly in obj.data.polygons:
                check(tuple(poly.vertices)==tuple(reversed(raw.indices[3*poly.index:3*poly.index+3])),'reflected winding')
                for li in poly.loop_indices:
                    vi=obj.data.loops[li].vertex_index
                    uv=obj.data.uv_layers.active.data[li].uv
                    check(abs(uv.x-raw.uvs[2*vi])<1e-6 and abs(uv.y-(1-raw.uvs[2*vi+1]))<1e-6,'UV')
        check(bpy.context.view_layer.objects.active==rig,'active rig')
        print('PASS native',kind,len(meshes),source.triangles,len(rig.data.bones),flush=True)
        summary.append({'kind':kind,'meshes':len(meshes),'triangles':source.triangles,'bones':len(rig.data.bones)})
    before=snapshot(); active=bpy.context.view_layer.objects.active; selected=set(bpy.context.selected_objects)
    original=imp.finalizeStratImport
    def fail(*a,**kw): raise RuntimeError('injected finalization failure')
    imp.finalizeStratImport=fail
    report,rig=imp.importStratCAS(bpy.context,path)
    imp.finalizeStratImport=original
    check(rig is None and 'injected' in str(report),'injection did not trigger')
    check(before==snapshot(),'rollback leaked datablocks')
    check(active==bpy.context.view_layer.objects.active and selected==set(bpy.context.selected_objects),'rollback selection')
    print('PASS rollback restores datablocks and selection',flush=True)
    blend=pathlib.Path(tmp)/'persist.blend';bpy.ops.wm.save_as_mainfile(filepath=str(blend));bpy.ops.wm.open_mainfile(filepath=str(blend))
    rigs=[o for o in bpy.data.objects if o.type=='ARMATURE' and 'med2_strat_import_metadata' in o]
    check(len(rigs)==4,'saved rig count');check(all(json.loads(o['med2_strat_import_metadata'])['scale']==2.7 for o in rigs),'saved metadata')
    print('PASS blend reload preserves four model provenance records',flush=True)
    (OUTPUT/'native-results.json').write_text(json.dumps(summary,indent=2))
    addon.unregister()
