# Built-in strat export validation

Run from the workspace root:

```powershell
& 'D:/Blender-5.1.2/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/v2d/run_export.py
```

The test uses synthetic assets in an isolated addon copy. It checks rest geometry,
bind pivots, negative scale, winding, UV seams, weights, texture staging, atomic CAS
replacement, both conversion operators, a full build and the retained IWTE path.
Set `MED2_ADDON_SOURCE` to test another addon tree. Set `MED2_IWTE_EXE` to run the
independent CAS-to-GLB reader check as well; failed reader diagnostics are retained
in the printed temporary directory, and only the test's process tree is stopped
on timeout.

For a local campaign-map candidate, also set `MED2_GAME_GATE_CAS` to an existing
supported strat CAS with a resolvable diffuse image and `MED2_GAME_GATE_OUTPUT` to
a separate output directory. The test exports a fresh CAS and textures there;
it does not modify the mod. Keep these game assets out of Git and packages.

The remaining acceptance check is manual: back up the target mod's matching CAS
and texture, install the candidate under `data/models_strat`, retain the original
descriptor entry, then load a campaign where that agent appears. Check its bind
shape, texture and animation. Record the result before making Built-in the default
or declaring v2d complete. The existing IWTE preference remains the default.
