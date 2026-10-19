# Native mounts, engines and faction queues

These checks use unpacked Heirs of Elendil data and Blender 5.1.2. The source and asset path overrides from the v2g checks also apply. No game assets or converted GLBs are distributed.

```powershell
python tests/v2h/check_engines.py
blender --background --factory-startup --python-exit-code 1 --python tests/v2h/run_mounted.py
blender --background --factory-startup --python-exit-code 1 --python tests/v2h/run_faction_corpus.py
```

Use `.github/tests` instead of `tests` in the repository. `check_engines.py` compares the vendored parsers against the Unit Transfer donor. `run_mounted.py` checks actual operators for infantry upgrades, officers, a wolf mount/rider, a faction queue, a catapult with two crew, and rollback after a deliberately failed crew import. IWTE is not configured for these tests.

`compare_mount.py` compares against an independent IWTE GLB: set `MED2_MODEL` to `mount_light_wolf` or `mount_simple_horse` and `MED2_IWTE_GLB` to its conversion. Both comparisons passed for parts, oriented corners, UVs, normals, weights, bone parents and pivots. A local catapult comparison also passed after excluding the CAS container root, matching IWTE.

`run_faction_corpus.py` is a diagnostic for the real England faction. It reports unsupported/missing assets separately; successful queue completion does not imply every model imported. Full TATR faction and interactive/game validation remain outstanding.

Supported engine input currently requires one type definition, one normal model group, a default loose skeleton CAS and one embedded diffuse/normal texture pair (an optional overlay is ignored, as in the existing Blender material workflow). Culture/variant alternatives, dual-sheet-crossing parts and mismatched weighted bones remain explicit failures. Backend defaults remain IWTE.
