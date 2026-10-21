# Built-in battle export checks

Run with Blender 5.1.2, for example:

```
blender --background --factory-startup --python-exit-code 1 --python .github/tests/v2k/check_inputs.py
blender --background --factory-startup --python-exit-code 1 --python .github/tests/v2k/check_transforms.py
blender --background --factory-startup --python-exit-code 1 --python .github/tests/v2k/run_operators.py
```

Input and transform checks are self-contained. Operator checks use the local
Heirs of Elendil installation; MED2_GAME_ROOT and MED2_ANIMATION_DATA override
its location, and MED2_ADDON_SOURCE selects an alternate addon source.

Covered: seams, strongest-two influence reduction, malformed input rejection,
atomic replacement, real Blender transforms, actual conversion operator,
backend dispatch, panel property references, and preservation of prior output.
Unapplied negative scale preserves Blender GLB winding, which may oppose its
normals. Apply negative scale and inspect face orientation before exporting.

The converter handles static bind geometry in exported GLBs, double-textured
unit templates at skeleton scale 1, and explicit game bone ordering. Other
mesh types and single-texture templates currently require IWTE. In-game
appearance and animation require separate validation.

Optional independent comparison: set MED2_IWTE_DIR to an IWTE installation and
run check_slots_iwte.py. It verifies every Sword and Crossbow bone slot against
IWTE with per-bone sentinels and retains its GLB/task/mesh files in iwte-debug/.
