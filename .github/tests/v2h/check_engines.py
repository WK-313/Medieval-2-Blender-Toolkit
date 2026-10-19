"""Read-only v2g parser parity check against the shared donor."""
import importlib
import json
import os
from pathlib import Path
import sys
import types

source=Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(candidate for parent in Path(__file__).resolve().parents for candidate in (parent/'Medieval-2-Toolkit-main',parent) if (candidate/'m2formats').is_dir())
donor=Path(os.environ.get('MED2_DONOR','D:/College/Coding 2/Unit Transfer/main/unittransfer'))
root=Path(os.environ.get('MED2_ANIMATION_DATA','C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War/mods/Heirs_of_Elendil/data'))
for name,path in [('native',source/'m2formats'),('donor',donor)]:
 p=types.ModuleType(name);p.__path__=[str(path)];sys.modules[name]=p
sys.modules['donor.i18n']=importlib.import_module('native.i18n')
local=importlib.import_module('native.engines');reference=importlib.import_module('donor.engines')
for filename,method in [('descr_engines.txt','parse_file'),('descr_engine_skeleton.txt','parse_skeleton_file')]:
 path=root/filename
 a,b=getattr(local,method)(path),getattr(reference,method)(path)
 assert a.to_text()==b.to_text()==path.read_bytes().decode('latin-1')
 left=a.engines if hasattr(a,'engines') else a.skeletons
 right=b.engines if hasattr(b,'engines') else b.skeletons
 assert len(left)==len(right)
 assert all(x.content_key()==y.content_key() for x,y in zip(left,right))
 print('PASS engine parser parity and byte-exact serialization:',filename,len(left))
