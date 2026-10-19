# Native infantry import checks

Requires Blender 5.1 and unpacked Heirs of Elendil assets containing `dunedain_infantry`. Game assets and converted reference files are not included.

Set `MED2_ADDON_SOURCE` to the addon source directory if it is outside the test ancestors. Optional overrides: `MED2_ANIMATION_DATA` (mod data), `MED2_GAME_ROOT` (game installation), `MED2_DONOR` (Unit Transfer package), `MED2_IWTE_GLB` (independent IWTE conversion of dunedain_infantry), and `MED2_IWTE_DIR` (IWTE directory, enabling the final exporter round trip).

Run from the workspace (use `.github/tests` instead of `tests` in the repository):

```powershell
python tests/v2g/check_modeldb.py
blender --background --factory-startup --python-exit-code 1 --python tests/v2g/compare_bridge.py
blender --background --factory-startup --python-exit-code 1 --python tests/v2g/run_operators.py
```

Validated with Blender 5.1.2 and IWTE v26_05_A:

- PASS parser parity with donor and byte-exact serialization of 1,447 model entries.
- PASS native/IWTE part names, oriented triangle corners, UVs, skin weights, normals, body/weapon parent mappings and rest pivots.
- PASS Import Unit (two upgrades), Import Full Unit (upgrades and officer), loaded textures and bypass of stale IWTE GLB files with no IWTE installation configured.
- PASS rollback after injected material failure.
- PASS existing GLB/texture exporter through IWTE back to a readable mesh: 26 parts, 4,303 triangles, bounds and skin retained.

IWTE generates two unweighted helper bones (`bone_weapon_group02/04`) which the native bridge does not synthesize. Both Blender imports remove the same 12 duplicate indexed triangles from the 4,315-triangle input. Native import timing is printed by each operator; the independent IWTE conversion took 11.114 seconds on the development machine.

Mounted units, engines, faction batches and parts spanning both texture sheets require IWTE. Campaign/battle gameplay and interactive viewport appearance are not covered by these headless checks. Backend defaults remain IWTE.
