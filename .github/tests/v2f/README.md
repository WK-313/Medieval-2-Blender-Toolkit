# v2f animation browser checks

Run from the workspace in PowerShell with Blender 5.1.2:

```powershell
$env:MED2_ANIMATION_DATA = '<mod>/data'
& 'D:/Blender-5.1.2/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/v2f/run_browser.py
```

The test uses a temporary addon copy and synthetic loose animations. It checks
catalogue grouping/counts/durations, errors, stale selections, real operators,
cache reuse and invalidation, constraint/blending rejection, pose-library
clear/apply followed by playback, both panel layouts, and save/reload reuse.
With MED2_ANIMATION_DATA it also checks MTW2_Mace / MTW2_Fast_Bowman on the
bundled Sword rig and strat_diplomat on the bundled strat rig. Game files are
read only. Omit that variable for portable synthetic-only checks.

Expected final line: `PASS v2f animation browser`, exit 0.

Interactive check: select a rig in Import/Export/Strat/QOL, expand Game Animations,
Refresh Skeletons, select a skeleton and Load Actions. Filter by family/search,
select a row, Build & Play, then Stop. Check timeline playback and viewport shape.
Headless tests validate Action assignment and frame evaluation, not actual UI
clicks or real-time playback. The separate v2d campaign-map gate remains pending.
