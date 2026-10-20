"""Small new-model regression without game assets or donor dependencies."""
import copy
import importlib
import json
import os
from array import array
from pathlib import Path
import sys
import types

SOURCE=Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
package=types.ModuleType('native');package.__path__=[str(SOURCE/'m2formats')];sys.modules['native']=package
mesh=importlib.import_module('native.mesh')
new=mesh.MeshFile(source='new.mesh',format='mesh')
new.positions=array('f',[0,0,0,1,0,0,0,1,0]);new.normals=array('f',[0,0,1]*3)
new.uvs=array('f',[0,0,1,0,0,1]);new.weights=array('f',[1,0]*3);new.bone_ids=bytes(12)
new.bones=['bone_pelvis'];new.bone_links=[0];new.groups=[mesh.MeshGroup('Body','triangle',array('H',[0,1,2]),0)]
back=mesh.read_mesh_bytes(mesh.write_mesh(new),'fresh.mesh',layout=True)
plain=mesh.read_mesh_bytes(mesh.write_mesh(new),'fresh-default.mesh')
assert list(plain.normals)==list(back.normals) and plain.bones==back.bones
assert plain.layout is None
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

for field in ('positions','normals','uvs','weights','bone_ids','bone_links'):
 bad=copy.deepcopy(new)
 values=getattr(bad,field)
 setattr(bad,field,values+values[:1])
 try:mesh.write_mesh(bad)
 except mesh.MeshError:pass
 else:raise AssertionError('Accepted malformed '+field)
bad=copy.deepcopy(new);bad.groups[0].indices.pop()
try:mesh.write_mesh(bad)
except mesh.MeshError:pass
else:raise AssertionError('Accepted incomplete triangle')
print('PASS malformed attribute lengths, bone links and incomplete triangles refused',flush=True)

# Class/object IDs must be derived again when the number of groups changes.
for count in (1, 2, 7):
 changed=copy.deepcopy(new)
 changed.groups=[mesh.MeshGroup('Body',f'part{i}',array('H',[0,1,2]),i%2) for i in range(count)]
 decoded=mesh.read_mesh_bytes(mesh.write_mesh(changed),'groups.mesh',layout=True)
 assert [(g.texture_group,g.flag) for g in decoded.groups]==[(g.texture_group,g.flag) for g in changed.groups]
 assert mesh.write_mesh(decoded)==mesh.write_mesh(changed)
print('PASS new models with 1, 2 and 7 groups preserve flags and archive object IDs',flush=True)
