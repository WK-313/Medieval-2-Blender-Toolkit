"""Compare shared native bridge with an independently converted IWTE GLB."""
import importlib,json,sys,types,tempfile,os
from pathlib import Path
from collections import Counter
import bpy
root=Path(__file__).resolve().parents[2]
source=Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
p=types.ModuleType('probe');p.__path__=[str(source)];sys.modules['probe']=p
bridge=importlib.import_module('probe.tasks.battle_import')
data=Path(os.environ.get('MED2_ANIMATION_DATA','C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War/mods/Heirs_of_Elendil/data'))
e=bridge.modeldb.parse_file(data/'unit_models/battle_models.modeldb').get(os.environ.get('MED2_MODEL','mount_light_wolf'))
m=bridge.mesh.read_mesh(data/e.lods[0][0]);skel,_=bridge.restSkeleton(data,e)
def snapshot(file):
 before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(file),disable_bone_shape=True)
 objs=set(bpy.data.objects)-before;rig=next(o for o in objs if o.type=='ARMATURE')
 bones={b.name:(b.parent.name if b.parent else '',tuple(b.head_local)) for b in rig.data.bones}
 parts={}; normals={}
 for o in objs:
  if o.type!='MESH':continue
  rows=[]
  for poly in o.data.polygons:
   tri=[]
   for li in poly.loop_indices:
    v=o.data.vertices[o.data.loops[li].vertex_index]
    uv=o.data.uv_layers.active.data[li].uv
    weights=tuple(sorted((o.vertex_groups[g.group].name,round(g.weight,5)) for g in v.groups if g.weight>1e-6))
    tri.append((tuple(round(x,5) for x in v.co),tuple(round(x,5) for x in uv),weights))
    normals[(o.name,tri[-1])] = tuple(o.data.corner_normals[li].vector)
   rows.append(min(tuple(tri[i:]+tri[:i]) for i in range(len(tri))))
  parts[o.name]=Counter(rows)
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
 return bones,parts,normals
ref=snapshot(Path(os.environ['MED2_IWTE_GLB']) if os.environ.get('MED2_IWTE_GLB') else root/'tests/v2g/iwte/du_kn_lod0.glb')
with tempfile.TemporaryDirectory() as temp:
 path=Path(temp)/'native.glb';path.write_bytes(bridge.nativeGLB(m,skel,single_sheet=not e.attach_textures));actual=snapshot(path)
print('BONES extra reference',set(ref[0])-set(actual[0]),'extra native',set(actual[0])-set(ref[0]))
for name,(parent,pos) in actual[0].items():
 assert name in ref[0],name
 assert parent==ref[0][name][0],(name,parent,ref[0][name][0])
 assert max(abs(a-b) for a,b in zip(pos,ref[0][name][1]))<2e-6,(name,pos,ref[0][name][1])
print('PASS shared body/weapon rest pivots and parent mapping')
assert set(ref[1])==set(actual[1]),(set(ref[1])-set(actual[1]),set(actual[1])-set(ref[1]))
for name,triangles in actual[1].items():
 missing=triangles-ref[1][name]
 if missing:
  print('MISMATCH',name,'native',sum(triangles.values()),'IWTE',sum(ref[1][name].values()),'different',sum(missing.values()))
  print('NATIVE',next(iter(missing)));print('IWTE',next(iter(ref[1][name]-triangles),None))
assert actual[1]==ref[1], 'Native/IWTE corner geometry or skin differs'
assert max(abs(a-b) for key,n in actual[2].items() for a,b in zip(n,ref[2][key])) < 2e-4
print('PASS native/IWTE parts, oriented triangle corners, UVs, skin weights and normals')
