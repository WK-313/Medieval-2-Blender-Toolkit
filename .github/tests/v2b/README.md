# Strat import validation

Run from the workspace root; portable scripts also work inside the addon repository under `.github/tests/v2b`. Set `MED2_ADDON_SOURCE` to override addon discovery. Use Blender 5.1 or newer for Blender checks.

```powershell
python tests/v2b/test_reader.py
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2b/bridge_review/test_bridge.py
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2b/ui_review/run_review.py
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2b/export_review/test_export.py
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2b/run_native.py
```

Reader tests use temporary descriptors and optionally inspect installed DaC/Reforged descriptors. Bridge tests cover mixed static/skinned geometry, native scale, faction texture isolation and transactional rollback. Browser tests cover stale selections, missing textures, extraction rollback and subprocess cleanup. Export tests run actual GLB export and texture conversion and check original scene data survives.

The real-model native harness requires DaC model assets. No mod assets are included in the tests or modified by them. IWTE comparisons require an installed IWTE executable and real model paths; reference outputs belong in temporary storage.

## IWTE comparison

Set `MED2_IWTE_EXE` to the IWTE executable and `MED2_MOD_DATA` to the DaC data folder, then run:

```powershell
python tests/v2b/extract_reference.py
& D:/Blender-5.1.2/blender.exe --background --factory-startup --python-exit-code 1 --python tests/v2b/compare_reference.py
```

The comparison excludes Blender custom bone display meshes and compares oriented triangle corners with UVs, world positions, bone heads, hierarchy and bone bases. Native import preserves all source faces; IWTE omits 212 opposite-facing coincident assassin triangles and three general triangles. Those differences are explicitly checked against reversed matching faces, not ignored. Coordinate and winding fixes were derived from these independent IWTE outputs.
