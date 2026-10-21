"""Seams, weight reduction, invalid GLBs and atomic-output protection."""
import copy,importlib,sys,types,tempfile,struct
from pathlib import Path
source=next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
p=types.ModuleType('probe');p.__path__=[str(source)];sys.modules['probe']=p
b=importlib.import_module('probe.tasks.battle_export')
def fixture():
 doc={'asset':{'version':'2.0'},'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],'nodes':[{'name':'Body__seams__opt','mesh':0,'skin':0},{'name':'a'},{'name':'b'},{'name':'c'}],'skins':[{'joints':[1,2,3]}],'meshes':[],'scenes':[{'nodes':[0,1,2,3]}],'scene':0};binary=bytearray()
 def add(rows,fmt,component,kind):
  while len(binary)%4:binary.append(0)
  raw=b''.join(struct.pack('<'+fmt,*row) for row in rows);start=len(binary);binary.extend(raw)
  doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':len(raw)})
  doc['accessors'].append({'bufferView':len(doc['bufferViews'])-1,'componentType':component,'count':len(rows),'type':kind});return len(doc['accessors'])-1
 attrs={}
 attrs['POSITION']=add([(0,0,0),(1,0,0),(0,1,0)]*2,'3f',5126,'VEC3')
 attrs['NORMAL']=add([(0,0,1)]*4+[(0,1,0),(0,0,1)],'3f',5126,'VEC3')
 attrs['TEXCOORD_0']=add([(0,0),(1,0),(0,1),(1,1),(1,0),(0,1)],'2f',5126,'VEC2')
 attrs['JOINTS_0']=add([(0,1,2,0)]*6,'4B',5121,'VEC4')
 attrs['WEIGHTS_0']=add([(.2,.3,.5,0)]*5+[(1,0,0,0)],'4f',5126,'VEC4')
 indices=add([(i,) for i in range(6)],'H',5123,'SCALAR')
 doc['meshes']=[{'primitives':[{'attributes':attrs,'indices':indices}]}];doc['buffers'][0]['byteLength']=len(binary)
 return doc,bytes(binary)
with tempfile.TemporaryDirectory() as temporary:
 temp=Path(temporary);path=temp/'test.glb';doc,binary=fixture()
 def put(d=doc,raw=binary):path.write_bytes(b.modelexport._glb(d,raw))
 put();model=b.meshFromGLB(path,['a','b','c'])
 assert model.vertices==6 and model.triangles==2 and model.groups[0].optional
 assert abs(model.weights[0]-.625)<1e-6 and abs(model.weights[1]-.375)<1e-6
 assert model.bone_ids[2]==2 and model.bone_ids[1]==1
 assert len(model.notes)==1
 print('PASS distinct UV, normal and skin seams survive; strongest two weights normalized; optional flag retained',flush=True)
 for label,edit in [('negative accessor',lambda d:d['meshes'][0]['primitives'][0]['attributes'].update(POSITION=-1)),('non-scalar indices',lambda d:d['accessors'][-1].update(type='VEC2')),('bad joint',lambda d:d['skins'][0].update(joints=[-1,2,3])),('short view',lambda d:d['bufferViews'][0].update(byteLength=1)),('sparse',lambda d:d['accessors'][0].update(sparse={})),('unskinned',lambda d:d['nodes'][0].pop('skin'))]:
  bad=copy.deepcopy(doc);edit(bad);put(bad)
  try:b.meshFromGLB(path,['a','b','c'])
  except ValueError:pass
  else:raise AssertionError('Accepted '+label)
 put();raw=bytearray(path.read_bytes());raw[16:20]=b'BAD!';path.write_bytes(raw)
 try:b.meshFromGLB(path,['a','b','c'])
 except ValueError:pass
 else:raise AssertionError('Accepted bad chunk magic')
 print('PASS malformed accessors, indices, joints, views, skin and GLB chunks refused',flush=True)
 template=temp/'task.txt';template.write_text('<task_id> extract_to_mesh\n<mesh_type> unit\n<mesh_double_texture> yes\n<skeleton_scale> 1.0000\n<cas_skeleton_name_list>\na\nb\nc\n',encoding='utf-8')
 output=path.with_suffix('.mesh');output.write_bytes(b'keep previous output')
 try:b.exportGLBToMesh(path,template)
 except ValueError:pass
 else:raise AssertionError('Accepted invalid export')
 assert output.read_bytes()==b'keep previous output'
 put();target,model=b.exportGLBToMesh(path,template)
 assert target==output and b.mesh.read_mesh(output,layout=True).vertices==6
 assert not list(temp.glob('*.tmp'))
 print('PASS failed conversion preserves previous output; successful conversion replaces it with readable mesh',flush=True)
