"""Native infantry import through the real single/full-unit operators."""
import importlib,json,sys,shutil,tempfile,os
from pathlib import Path
import bpy
SOURCE=Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
game=Path(os.environ.get('MED2_GAME_ROOT','C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War'));data=Path(os.environ.get('MED2_ANIMATION_DATA',str(game/'mods/Heirs_of_Elendil/data')))
with tempfile.TemporaryDirectory(prefix='v2g_ops_') as temporary:
 temp=Path(temporary);source=temp/'test_addon';shutil.copytree(SOURCE,source,ignore=shutil.ignore_patterns('__pycache__','.git','.github','text','images'))
 sys.path.insert(0,str(temp));addon=importlib.import_module('test_addon');addon.register()
 try:
  imp=importlib.import_module('test_addon.tasks.importer');bridge=imp.battle_import
  edu=importlib.import_module('test_addon.panels.edu_panel');edu.showResultsPopup=lambda *a:None
  reader=bpy.context.scene.med2_toolkit_reader;reader.mods_filtered='custom';reader.directory_mod_data=str(data);reader.directory_med2=str(game);reader.directory_models=str(temp/'output');reader.directory_iwte=str(temp/'NO_IWTE');reader.backend_battle_import='BUILTIN'
  units=bpy.context.scene.med2_toolkit_units;units.hide_toggle=False;units.frame_toggle=False;units.textured_toggle=False;units.primary_secondary='primary';units.import_filter='ownership'
  unit={'ID':'Native test','Type':'Native test','Model':['dunedain_infantry','dunedain_infantry'],'Attachment':'unused','Officers':['dunedain_infantry'],'Owners':{'ownership':['england']}}
  files={'available_factions.json':{'England':'england'},'unit_dictionary.json':{'Native test':unit},'attachment_dictionary.json':{},'model_dictionary.json':{'dunedain_infantry':{'Mesh':'du_kn_lod0.glb','Folder':'unused','Textures':{'england':['unused.dds','unused.dds']}}}}
  for name,contents in files.items():(source/'text'/name).write_text(json.dumps(contents),encoding='utf-8')
  units.import_faction='england';units.import_unit=json.dumps(unit);units.single_import_upgrades=(True,True,False,False)
  assert bpy.ops.medieval2toolkit.unit_importer()=={'FINISHED'}
  rigs=[o for o in bpy.data.objects if o.get('med2_battle_import_backend')=='BUILTIN'];assert len(rigs)==2,len(rigs)
  assert rigs[0].location!=rigs[1].location
  for rig in rigs:
   assert len([o for o in rig.children_recursive if o.type=='MESH'])==26
   assert all(node.image and Path(bpy.path.abspath(node.image.filepath)).is_file() for o in rig.children_recursive if o.type=='MESH' for mat in o.data.materials for node in mat.node_tree.nodes if node.type=='TEX_IMAGE')
  print('PASS Import Unit: two upgrades, separated rigs, 26 parts each, textures loaded, no IWTE',flush=True)
  assert bpy.ops.medieval2toolkit.full_unit_importer()=={'FINISHED'}
  assert len([o for o in bpy.data.objects if o.get('med2_battle_import_backend')=='BUILTIN'])==5
  print('PASS Import Full Unit: both upgrades plus officer, no IWTE',flush=True)
  # Cache collision: a corrupt old IWTE GLB must never be read by Built-in.
  (temp/'output/du_kn_lod0.glb').write_bytes(b'not a glb')
  assert imp.modelImporter(str(temp/'output'),'Fresh','england',{},'dunedain_infantry')[0]==2
  print('PASS Built-in bypasses stale flat IWTE cache',flush=True)
  before=set(bpy.data.objects)
  old=imp.materialWorkflow
  imp.materialWorkflow=lambda *args:(_ for _ in ()).throw(ValueError('injected material failure'))
  try:
   imp.modelImporter(str(temp/'output'),'Rollback','england',{},'dunedain_infantry')
   raise AssertionError('did not fail')
  except ValueError:pass
  finally:imp.materialWorkflow=old
  assert set(bpy.data.objects)==before
  print('PASS failed native material setup rolls back imported objects',flush=True)
  # Existing glTF export preserves native skin for IWTE's unchanged export path.
  rig=next(o for o in bpy.data.objects if o.get('med2_battle_import_backend')=='BUILTIN')
  bpy.ops.object.select_all(action='DESELECT');rig.select_set(True)
  for o in rig.children_recursive:o.select_set(True)
  export=temp/'roundtrip.glb'
  bpy.ops.export_scene.gltf(filepath=str(export),export_format='GLB',use_selection=True,export_animations=False)
  doc,_=bridge.modelexport.read_glb(export.read_bytes());assert doc.get('skins') and len(doc['meshes'])==26
  print('PASS native rig exports GLB with skin and all 26 parts',flush=True)
  assert not Path(reader.directory_iwte).exists()
  if os.environ.get('MED2_IWTE_DIR'):
   import subprocess,time
   exporter=importlib.import_module('test_addon.tasks.unit_exporter')
   checks=importlib.import_module('test_addon.tasks.export_checks')
   rig=rigs[0];bpy.context.view_layer.objects.active=rig;rig.location=(0,0,0)
   rig.data.pose_position='REST';checks.autoAssignMaterials(bpy.context)
   reader.directory_unit_export=str(temp/'export')
   export_settings=rig.med2_toolkit_unit_export
   export_settings.export_glb_name='native_roundtrip'
   export_settings.export_visible_only=False;export_settings.export_animations=False
   result=exporter.exportArmatureGLB(bpy.context)
   assert Path(export_settings.last_exported_glb).is_file(),result
   reader.directory_iwte=os.environ['MED2_IWTE_DIR']
   export_settings.iwte_task_template=str(source/'iwte_tasks/iwte_extract_to_mesh_sword_task.txt')
   job=exporter.exportToMeshIWTE(bpy.context)
   assert isinstance(job,dict),job
   try:code=job['process'].wait(timeout=120)
   except subprocess.TimeoutExpired:
    subprocess.run(['taskkill','/PID',str(job['process'].pid),'/T','/F'],capture_output=True);raise
   output=Path(export_settings.last_exported_glb).with_suffix('.mesh')
   assert code==0 and output.is_file(),(code,str(output))
   written=bridge.mesh.read_mesh(output)
   original=bridge.mesh.read_mesh(bridge.sources(bpy.context,'dunedain_infantry')[3])
   assert len(written.groups)==len(original.groups)==26
   assert written.triangles==4303,written.triangles
   assert max(abs(a-b) for u,v in zip(written.bounds(),original.bounds()) for a,b in zip(u,v))<2e-4
   assert written.weights and written.bones
   print('PASS existing GLB/texture export -> IWTE -> readable mesh: 26 parts, 4303 triangles, bounds/skin retained',flush=True)
 finally:addon.unregister()
print('PASS v2g native operators',flush=True)
