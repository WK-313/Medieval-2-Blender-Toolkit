# Mesh writer round trips

Run from the workspace root (or set `MED2_ADDON_SOURCE` to the addon directory):

```powershell
python tests/v2i/check_new.py
python tests/v2i/roundtrip_corpus.py
```

`check_new.py` needs only Python. It checks a three-vertex skinned model with
packed normals, default and layout reads, changing group counts and optional
flags, and rejection of malformed attribute lengths, indices and bone links.

`roundtrip_corpus.py` needs the installed Medieval II corpus and the Unit Transfer
pack reader. Set `MED2_GAME_ROOT` and `MED2_DONOR` for other installations. The
donor is used only to access packed test inputs, not by the addon. Set
`MED2_MESH_REPORT` to select the JSON report path. Inputs are read-only. Unsupported
multi-model archives are listed with their parser error; any other failure fails
the test. The report is saved before edited/new-model assertions run.

The corpus test requires identical bytes for every supported input, then changes
a vertex and verifies geometry, UVs, influences, bone links and LOD trailer.
Game assets and generated reports are not distributed with these tests.

Blender regression commands (Blender 5.1.2):

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/v2h/run_mounted.py
$env:MED2_MODEL='dunedain_infantry'
$env:MED2_IWTE_GLB='tests/v2g/iwte/du_kn_lod0.glb'
blender --background --factory-startup --python-exit-code 1 --python tests/v2h/compare_sheets.py
```

IWTE reference files are local test inputs and are not included. Also run the
existing v2a package check with an isolated `BLENDER_USER_RESOURCES` after building
the ZIP. These checks do not establish in-game rendering or animation behavior.

Validated 2026-10-20: 8,388 installed loose/packed sources, 8,378 byte-exact
round trips, 10 explicitly refused multi-model sky/lightning archives, zero
unexplained failures. New/edited models and all small-model checks passed.
Blender mounted/full-unit/engine/rollback regressions, IWTE infantry/elephant-crew/
catapult comparisons, and the 91-file ZIP fresh install/enable check passed.
