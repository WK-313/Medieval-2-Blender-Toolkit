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
  for module,method in [('edu_reader','eduReader'),('bmdb_reader','bmdbReader')]:
   result=getattr(importlib.import_module('test_addon.tasks.'+module),method)(str(data))
   assert result=='Finished',result
  units.import_faction='england';units.faction_import_officers=True
  results=[]
  edu.showResultsPopup=lambda context,title,rows:results.extend(rows)
  try:bpy.ops.medieval2toolkit.faction_importer()
  except RuntimeError as exc:print('FACTION REPORT',exc,flush=True)
  assert not Path(reader.directory_iwte).exists()
  assert edu._import_job is None
  errors=[message for level,message in results if level=='ERROR']
  print('REAL FACTION',len([o for o in bpy.data.objects if o.type=='ARMATURE']),'rigs;',len(errors),'errors',flush=True)
  for error in errors:print('UNSUPPORTED',error,flush=True)
  print('PASS native faction queue completes and reports failures without IWTE',flush=True)
 finally:addon.unregister()
