"""Read-only installed mesh corpus and isolated edited/new-model round trips."""
import copy
import importlib
import json
import os
from array import array
from pathlib import Path
import sys
import types

SOURCE=Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
DONOR=Path(os.environ.get('MED2_DONOR','D:/College/Coding 2/Unit Transfer/main/unittransfer'))
GAME=Path(os.environ.get('MED2_GAME_ROOT','C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War'))
for name,path in [('native',SOURCE/'m2formats'),('donor',DONOR)]:
 package=types.ModuleType(name);package.__path__=[str(path)];sys.modules[name]=package
sys.modules['donor.i18n']=importlib.import_module('native.i18n')
mesh=importlib.import_module('native.mesh')
gamepack=importlib.import_module('donor.gamepack')
assert GAME.is_dir(),GAME
sources=[(str(p),p.read_bytes) for root in (GAME/'data',GAME/'mods') for p in root.rglob('*.mesh')]
for pack in gamepack.packs(GAME):
 sources.extend((str(pack.path)+':'+name,lambda p=pack,n=name:p.read(n)) for name in pack.entries if name.casefold().endswith('.mesh'))
report={'sources':len(sources),'exact':0,'unsupported':[],'failures':[]}
first=None
for index,(name,read) in enumerate(sources,1):
 try:
  raw=read();model=mesh.read_mesh_bytes(raw,name,layout=True)
  assert model.layout is not None,model.notes
  encoded=mesh.write_mesh(model)
  assert encoded==raw,'written bytes differ'
  report['exact']+=1
  if first is None and model.weights and len(model.groups)>1:first=model
 except mesh.MeshError as error:
  if 'more than one model' in str(error):report['unsupported'].append({'source':name,'reason':str(error)})
  else:
   report['failures'].append({'source':name,'reason':str(error)})
   print('FAIL',name,str(error),flush=True)
 except Exception as error:report['failures'].append({'source':name,'reason':str(error)})
 if index%500==0:print('PROGRESS',index,len(sources),report['exact'],len(report['failures']),flush=True)
output=Path(os.environ.get('MED2_MESH_REPORT',str(Path(__file__).with_name('roundtrip.json'))))
output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print('CORPUS REPORT', output, flush=True)
for failure in report['failures']:print('FAIL', failure, flush=True)
assert first is not None,'No skinned multi-part reference'
edited=copy.deepcopy(first);edited.positions[0]+=.125
back=mesh.read_mesh_bytes(mesh.write_mesh(edited),'edited.mesh',layout=True)
assert list(back.positions)==list(edited.positions)
assert back.layout.lod_body==first.layout.lod_body
assert list(back.uvs)==list(first.uvs) and back.bone_ids==first.bone_ids
assert back.bone_links==first.bone_links
print('PASS edited geometry round trip preserves UVs, influences, bone links and LOD trailer',flush=True)
new=mesh.MeshFile(source='new.mesh',format='mesh')
new.positions=array('f',[0,0,0,1,0,0,0,1,0]);new.normals=array('f',[0,0,1]*3)
new.uvs=array('f',[0,0,1,0,0,1]);new.weights=array('f',[1,0]*3);new.bone_ids=bytes(12)
new.bones=['bone_pelvis'];new.bone_links=[0];new.groups=[mesh.MeshGroup('Body','triangle',array('H',[0,1,2]),0)]
back=mesh.read_mesh_bytes(mesh.write_mesh(new),'fresh.mesh',layout=True)
assert list(back.positions)==list(new.positions) and list(back.uvs)==list(new.uvs)
assert back.bone_ids==new.bone_ids and list(back.weights)==list(new.weights)
assert list(back.groups[0].indices)==[0,1,2]
assert len(back.normals)==len(new.normals), (back.notes, back.layout, back.extra_streams)
assert max(abs(a-b) for a,b in zip(back.normals,new.normals))<=1/127
print('PASS new skinned model writes and reads with geometry, UVs and weights intact',flush=True)
for label,bad in [('indices',copy.deepcopy(new)),('vertex limit',copy.deepcopy(new))]:
 if label=='indices':bad.groups[0].indices[0]=3
 else:bad.positions=array('f',bytes(12*65537))
 try:mesh.write_mesh(bad)
 except mesh.MeshError:pass
 else:raise AssertionError('Accepted invalid '+label)
print('PASS invalid indices and vertex overflow refused',flush=True)
output=Path(os.environ.get('MED2_MESH_REPORT',str(Path(__file__).with_name('roundtrip.json'))))
output.write_text(json.dumps(report,indent=2),encoding='utf-8')
print('CORPUS',report['sources'],'sources;',report['exact'],'exact;',len(report['unsupported']),'explained multi-model;',len(report['failures']),'failures',flush=True)
assert report['exact'] and not report['failures'],report['failures'][:5]
print('PASS installed mesh corpus byte-exact round trip',flush=True)
