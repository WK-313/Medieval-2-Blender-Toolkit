"""Compare native Blender import with independent IWTE GLB geometry and rig."""
import importlib, importlib.util, json, os, pathlib, shutil, sys, tempfile, collections
import bpy
from mathutils.kdtree import KDTree
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[1]
ADDON=pathlib.Path(os.environ['MED2_ADDON_SOURCE']) if 'MED2_ADDON_SOURCE' in os.environ else next(p for parent in HERE.parents for p in (parent/'Medieval-2-Toolkit-main',parent) if (p/'tasks'/'strat_importer.py').exists())
DATA=pathlib.Path(os.environ.get('MED2_MOD_DATA',r'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods\Divide_and_Conquer_EUR\data'))
REF=pathlib.Path(tempfile.gettempdir())/'med2-v2b-iwte'
def triangles(objects):
    records=[]
    for obj in objects:
        if obj.type!='MESH':continue
        mesh=obj.data;mesh.calc_loop_triangles()
        for tri in mesh.loop_triangles:
            records.append([(obj.matrix_world@mesh.vertices[mesh.loops[l].vertex_index].co,tuple(mesh.uv_layers.active.data[l].uv)) for l in tri.loops])
    return records
def cycle(t):return min(tuple(t[i:]+t[:i]) for i in range(3))
results=[]
with tempfile.TemporaryDirectory(prefix='v2b_compare_') as temp:
    dest=pathlib.Path(temp)/'v2b_addon';shutil.copytree(ADDON,dest,ignore=shutil.ignore_patterns('__pycache__','.git'))
    spec=importlib.util.spec_from_file_location('v2b_addon',dest/'__init__.py',submodule_search_locations=[str(dest)])
    addon=importlib.util.module_from_spec(spec);sys.modules[spec.name]=addon;spec.loader.exec_module(addon);addon.register()
    bridge=importlib.import_module('v2b_addon.tasks.strat_importer')
    for kind in ('assassin','diplomat','spy','general'):
        report,rig=bridge.importStratCAS(bpy.context,DATA/'models_strat'/('dunedain_'+kind+'.cas'))
        assert rig,report
        native=triangles(rig.children)
        before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(REF/(kind+'.glb')))
        reference=set(bpy.data.objects)-before
        other=triangles(o for o in reference if o.type=='MESH' and o.parent is not None)
        points={tuple(p):i for i,p in enumerate(dict.fromkeys(tuple(p) for t in native for p,uv in t))}
        kd=KDTree(len(points))
        for p,i in points.items():kd.insert(p,i)
        kd.balance()
        def keyed(tris):
            distance=0;keys=[]
            for t in tris:
                corners=[]
                for p,uv in t:
                    _,i,d=kd.find(p);distance=max(distance,d);corners.append((i,tuple(round(v,4) for v in uv)))
                keys.append(cycle(corners))
            return collections.Counter(keys),distance
        expected,_=keyed(native);observed,error=keyed(other)
        extras=expected-observed
        degenerate=collections.Counter()
        for t in native:
            if (t[1][0]-t[0][0]).cross(t[2][0]-t[0][0]).length < 1e-10:
                k,_=keyed([t]);degenerate.update(k)
        duplicate=collections.Counter({k:v-1 for k,v in expected.items() if v>1})
        opposite=collections.Counter({k:v for k,v in extras.items() if cycle(list(reversed(k))) in observed})
        reference_rig=next(o for o in reference if o.type=='ARMATURE')
        nb={b.name.lower():rig.matrix_world@b.head_local for b in rig.data.bones}
        rb={b.name.lower():reference_rig.matrix_world@b.head_local for b in reference_rig.data.bones}
        common=set(nb)&set(rb)
        bone_error=max((nb[n]-rb[n]).length for n in common)
        n_bones={b.name.lower():b for b in rig.data.bones}
        r_bones={b.name.lower():b for b in reference_rig.data.bones}
        basis_error=max(abs(n_bones[n].matrix_local[i][j]-r_bones[n].matrix_local[i][j]) for n in common for i in range(3) for j in range(3))
        hierarchy={b.name.lower():(b.parent.name.lower() if b.parent else '') for b in rig.data.bones}
        ref_hierarchy={b.name.lower():(b.parent.name.lower() if b.parent else '') for b in reference_rig.data.bones}
        row={'kind':kind,'native_triangles':len(native),'iwte_triangles':len(other),'vertex_max_error':error,'triangle_uv_winding_matches':sum((expected&observed).values()),'native_bones':len(nb),'iwte_bones':len(rb),'common_bones':len(common),'bone_head_max_error':bone_error,'hierarchy_equal':hierarchy==ref_hierarchy}
        results.append(row)
        row.update(bone_basis_max_error=basis_error,extra_native_triangles=sum(extras.values()),extra_degenerate=sum((extras&degenerate).values()),extra_duplicates=sum((extras&duplicate).values()),extra_opposite_faces=sum(opposite.values()))
        print(json.dumps(row),flush=True)
    (HERE/'comparison-results.json').write_text(json.dumps(results,indent=2))
    for row in results:
        assert row['iwte_triangles']==row['triangle_uv_winding_matches'],row
        assert row['native_triangles']-row['iwte_triangles']==row['extra_native_triangles']==row['extra_opposite_faces'],row
        assert row['vertex_max_error']<1e-5 and row['bone_head_max_error']<1e-5,row
        assert row['bone_basis_max_error']<1e-5,row
        assert row['native_bones']==row['common_bones'] and row['hierarchy_equal'],row
    print('PASS four models match IWTE positions, winding, UVs, bone bases and hierarchy; native preserves opposite faces IWTE removes',flush=True)
    addon.unregister()
