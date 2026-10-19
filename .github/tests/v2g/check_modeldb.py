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
local=importlib.import_module('native.modeldb');reference=importlib.import_module('donor.modeldb')
path=root/'unit_models/battle_models.modeldb'
a,b=local.parse_file(path),reference.parse_file(path)
assert len(a.entries)==len(b.entries)
assert a.to_text()==b.to_text()==path.read_bytes().decode('latin-1')
for left,right in zip(a.entries,b.entries):
 assert left.name==right.name and left.content_key()==right.content_key()
print('PASS shared parser parity and byte-exact serialization:',len(a.entries),'entries')
entry=a.get('dunedain_infantry')
assert entry and entry.animations and entry.animations[0].pri_weapons
print('PASS body and weapon skeleton metadata:',entry.skeletons(),entry.weapon_skeletons())
