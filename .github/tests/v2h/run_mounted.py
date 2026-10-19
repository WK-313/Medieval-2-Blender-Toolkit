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
  mounts={'Test mount':{'Model':'mount_light_wolf','Crew':[[0,0,0]]}}
  mounted=dict(unit,ID='Mounted test',Type='Mounted test',Attachment=['mount','Test mount'],Model=['dunedain_infantry'],Officers=[])
  dictionary=files['model_dictionary.json'];dictionary['mount_light_wolf']={'Mesh':'mount.glb','Folder':'unused','Textures':{}}
  (source/'text/model_dictionary.json').write_text(json.dumps(dictionary),encoding='utf-8')
  (source/'text/attachment_dictionary.json').write_text(json.dumps(mounts),encoding='utf-8')
  (source/'text/unit_dictionary.json').write_text(json.dumps({'Native test':unit,'Mounted test':mounted}),encoding='utf-8')
  units.import_unit=json.dumps(mounted);units.single_import_upgrades=(True,False,False,False)
  existing=set(bpy.data.objects)
  assert bpy.ops.medieval2toolkit.unit_importer()=={'FINISHED'}
  imported=[o for o in set(bpy.data.objects)-existing if o.type=='ARMATURE']
  assert len(imported)==2,[(o.name,o.get('med2_battle_source')) for o in imported]
  assert any('mounts' in o.get('med2_battle_source','').lower() for o in imported)
  assert len({o.get('med2_battle_source') for o in imported})==2
  print('PASS native mounted unit: distinct mount and rider sources',flush=True)
  units.faction_import_officers=True
  before=set(bpy.data.objects)
  assert bpy.ops.medieval2toolkit.faction_importer()=={'FINISHED'}
  added=[o for o in set(bpy.data.objects)-before if o.type=='ARMATURE']
  assert len(added)==5,len(added)
  assert not Path(reader.directory_iwte).exists()
  assert edu._import_job is None
  print('PASS native faction batch: infantry upgrades, officer and mounted unit without IWTE',flush=True)
  engine=dict(unit,ID='Engine test',Type='Engine test',Attachment=['engine','eastern_catapult'],Model=['dunedain_infantry'],Officers=[])
  mounts['eastern_catapult']={'Crew':[[1,2,0],[-1,2,0]]}
  (source/'text/attachment_dictionary.json').write_text(json.dumps(mounts),encoding='utf-8')
  (source/'text/unit_dictionary.json').write_text(json.dumps({'Engine test':engine}),encoding='utf-8')
  units.import_unit=json.dumps(engine)
  before=set(bpy.data.objects)
  assert bpy.ops.medieval2toolkit.unit_importer()=={'FINISHED'}
  added=[o for o in set(bpy.data.objects)-before if o.type=='ARMATURE']
  assert len(added)==3,len(added)
  engine_rig=next(o for o in added if 'siege_engines' in o.get('med2_battle_source',''))
  assert len(engine_rig.data.bones)==8
  assert not Path(reader.directory_iwte).exists()
  print('PASS native catapult and two crew, no IWTE',flush=True)
  before={kind:set(getattr(bpy.data,kind)) for kind in ('objects','meshes','armatures','materials','images','collections')}
  original_import=bridge.importModel
  def fail_crew(*args,**kwargs):raise ValueError('injected crew failure')
  bridge.importModel=fail_crew
  coords=[8,0,0]
  try:
   imp.unitImporter(str(temp/'output'),engine,'england',coords,0)
   raise AssertionError('expected crew failure')
  except ValueError as error:assert 'injected crew' in str(error)
  finally:bridge.importModel=original_import
  assert coords==[8,0,0]
  assert all(set(getattr(bpy.data,kind))==previous for kind,previous in before.items())
  print('PASS failed crew import rolls back complete composite unit and placement',flush=True)
 finally:addon.unregister()
