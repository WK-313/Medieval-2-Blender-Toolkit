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
  panel=importlib.import_module('test_addon.panels.unit_export_panel');panel.showResultsPopup=lambda *args:None
  bpy.context.view_layer.objects.active=rig
  rig.med2_toolkit_unit_export.last_exported_glb=str(export)
  rig.med2_toolkit_unit_export.iwte_task_template=str(source/'iwte_tasks/iwte_extract_to_mesh_sword_task.txt')
  exporter=importlib.import_module('test_addon.tasks.unit_exporter')
  old_iwte=exporter.exportToMeshIWTE;sentinel=object()
  try:
   exporter.exportToMeshIWTE=lambda context:sentinel
   reader.backend_battle_export='IWTE'
   assert exporter.exportToMesh(bpy.context) is sentinel
  finally:exporter.exportToMeshIWTE=old_iwte
  print('PASS IWTE selection retains the existing conversion path',flush=True)
  class DrawLayout:
   def __init__(self):self.calls=[]
   def __getattr__(self,name):
    def call(*args,**kwargs):
     if name=='prop':assert hasattr(args[0],args[1]),args[1]
     self.calls.append((name,args,kwargs));return self
    return call
  from types import SimpleNamespace
  for backend in ('IWTE','BUILTIN'):
   reader.backend_battle_export=backend;layout=DrawLayout()
   panel.MED_2_TOOLKIT_PT_Export_Run.draw(SimpleNamespace(layout=layout),bpy.context)
   label='Convert to Mesh (Built-in)' if backend=='BUILTIN' else 'Convert to Mesh (IWTE)'
   assert any(name=='operator' and kw.get('text')==label for name,args,kw in layout.calls)
  print('PASS export panel draws with valid properties and matching backend actions',flush=True)
  reader.backend_battle_export='BUILTIN'
  assert bpy.ops.medieval2toolkit.export_unit_iwte_mesh()=={'FINISHED'}
  output=export.with_suffix('.mesh');written=bridge.mesh.read_mesh(output,layout=True)
  assert written.triangles==4303 and len(written.groups)==26
  assert not Path(reader.directory_iwte).exists()
  print('PASS real Convert to Mesh operator: Built-in writes 26 parts/4303 triangles without IWTE',flush=True)
  if os.environ.get('MED2_GATE_OUTPUT'):
   target=Path(os.environ['MED2_GATE_OUTPUT']);target.parent.mkdir(parents=True,exist_ok=True)
   shutil.copy2(output,target)
   print('PASS saved native export game-check candidate:',target,flush=True)
  previous=output.read_bytes();export.write_bytes(b'broken GLB')
  try:result=bpy.ops.medieval2toolkit.export_unit_iwte_mesh()
  except RuntimeError as error:assert 'GLB' in str(error)
  else:assert result=={'CANCELLED'}
  assert output.read_bytes()==previous
  print('PASS failed real conversion leaves previous mesh intact',flush=True)
 finally:addon.unregister()
