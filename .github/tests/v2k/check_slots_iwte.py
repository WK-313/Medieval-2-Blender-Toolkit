"""Compare game slot indices against IWTE using every QOL bone."""
import importlib,sys,types,subprocess,re,os,contextlib
from pathlib import Path
import bpy
source=next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
p=types.ModuleType('probe');p.__path__=[str(source)];sys.modules['probe']=p
bridge=importlib.import_module('probe.tasks.battle_export')
iwte=importlib.import_module('probe.tasks.iwte_run')
folder=Path(os.environ['MED2_IWTE_DIR'])
for skeleton in ('Sword','Crossbow'):
 bpy.ops.wm.read_factory_settings(use_empty=True)
 bpy.ops.import_scene.gltf(filepath=str(source/'armatures'/(skeleton+'.glb')))
 rig=next(o for o in bpy.data.objects if o.type=='ARMATURE');rig.data.pose_position='REST'
 for obj in list(bpy.data.objects):
  if obj is not rig:bpy.data.objects.remove(obj,do_unlink=True)
 names=[b.name for b in rig.data.bones]
 verts=[];faces=[]
 for i,name in enumerate(names):
  y=(i%3)*.11;z=(i%5)*.07
  verts.extend([(i*.1,y,z),(i*.1+.02,y,z),(i*.1,y,z+.02),(i*.1,y+.02,z)]);faces.extend(tuple(i*4+j for j in face) for face in ((0,2,1),(0,1,3),(0,3,2),(1,2,3)))
 geo=bpy.data.meshes.new('sentinels');geo.from_pydata(verts,[],faces);geo.update();uv=geo.uv_layers.new()
 for i,loop in enumerate(uv.data):loop.uv=((0,0),(1,0),(0,1))[i%3]
 obj=bpy.data.objects.new('Body__sentinels',geo);bpy.context.collection.objects.link(obj);obj.parent=rig
 for i,name in enumerate(names):obj.vertex_groups.new(name=name).add([i*4+j for j in range(4)],1,'REPLACE')
 mat=bpy.data.materials.new('characterlod0__main');mat.use_nodes=True;geo.materials.append(mat)
 image=bpy.data.images.new('sentinel_main',width=4,height=4);image.generated_color=(1,1,1,1)
 texture=mat.node_tree.nodes.new('ShaderNodeTexImage');texture.image=image
 mat.node_tree.links.new(texture.outputs['Color'],mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
 obj.modifiers.new('Armature','ARMATURE').object=rig
 bpy.ops.object.select_all(action='SELECT')
 debug=Path(__file__).resolve().parent/'iwte-debug'/os.environ.get('MED2_SLOT_CASE','named-task')/skeleton;debug.mkdir(parents=True,exist_ok=True)
 with contextlib.nullcontext(str(debug)) as temporary:
  temp=Path(temporary);glb=temp/'sentinels.glb'
  bpy.ops.export_scene.gltf(filepath=str(glb),export_format='GLB',use_selection=True,export_animations=False,export_apply=True)
  template=source/'iwte_tasks'/('iwte_extract_to_mesh_'+skeleton.lower()+'_task.txt')
  native=bridge.meshFromGLB(glb,bridge.taskBoneOrder(template))
  lines=[]
  values={'extract_file_full_path_in':str(glb),'directory_out':str(temp),'mesh_file_name_out':'iwte.mesh'}
  for line in template.read_text(encoding='utf-8').splitlines():
   match=re.match(r'\s*<([^>]+)>',line)
   lines.append('<'+match[1]+'> "'+values[match[1]]+'"' if match and match[1] in values else line)
  # IWTE's CLI requires its task filename convention; generic task.txt hangs.
  task=temp/'iwte_extract_to_mesh_sentinels_task.txt';task.write_text('\n'.join(lines)+'\n',encoding='utf-8')
  job=iwte.startIWTETask(iwte.findIWTEExe(str(folder)),str(folder),str(task),str(temp/'iwte.mesh'))
  try:code=job['process'].wait(timeout=120)
  except subprocess.TimeoutExpired:
   subprocess.run(['taskkill','/PID',str(job['process'].pid),'/T','/F'],capture_output=True)
   raise
  assert code==0 and (temp/'iwte.mesh').exists(),code
  reference=bridge.mesh.read_mesh(temp/'iwte.mesh',layout=True)
  def weights(m):
   return {tuple(round(v,5) for v in m.positions[i*3:i*3+3]):tuple(sorted((m.bone_ids[i*4+offset],round(m.weights[i*2+w],5)) for w,offset in ((0,2),(1,1)) if m.weights[i*2+w]>1e-6)) for i in range(m.vertices)}
  actual,expected=weights(native),weights(reference)
  assert actual==expected,(skeleton,[(point,actual.get(point),value) for point,value in expected.items() if actual.get(point)!=value])
  print('PASS',skeleton,'all',len(names),'bone weights use the same game slots as IWTE',flush=True)
