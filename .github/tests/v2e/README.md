# Animation engine (v2e)

Run headless Blender from the workspace root:

```powershell
$env:MED2_VIEWER_JS = 'D:/College/Coding 2/Unit Transfer/main/web/js/v3anim.js'
$env:MED2_ANIMATION_DATA = 'C:/Program Files (x86)/Steam/steamapps/common/Medieval II Total War/mods/Heirs_of_Elendil/data'
& 'D:/Blender-5.1.2/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/v2e/run_animation.py
& 'D:/Blender-5.1.2/blender.exe' --background --factory-startup --python-exit-code 1 --python tests/v2e/run_sources.py
```

`run_animation.py` requires Node on PATH and the actual donor viewer file for an
independent numerical reference. Without MED2_ANIMATION_DATA it runs the synthetic
rig/skin checks and explicitly skips real mod actions. Set MED2_ADDON_SOURCE to
test another addon checkout. Game assets are read only and never committed.

`run_sources.py` builds tiny independent binary fixtures in a temporary folder.
It covers descriptor actions, loose overrides, packed slots and unpacked entries,
exact/fallback scale selection, mod precedence, vanilla fallback and source errors.

## API (inside Blender)

```python
import bpy, importlib
engine = importlib.import_module('Medieval-2-Toolkit-main.tasks.animation_engine')
scene, rig = bpy.context.scene, bpy.context.object
data_dir = bpy.path.abspath(scene.med2_toolkit_reader.directory_mod_data)
animation = engine.loadAnimation(data_dir, 'MTW2_Mace', slot=0)
# Alternatively: action='stand' from descr_skeleton.txt, or path='...cas'.
report, action = engine.buildAnimationAction(rig, animation, fps=scene.render.fps / scene.render.fps_base)
engine.activateAnimationAction(rig, action)
```

The adapter targets the current bundled battle rigs and native/IWTE strat rigs.
It maps names (including imported original CAS labels), conjugates the viewer's
skin transforms through the CAS-to-Blender Y/Z reflection, and converts them to
each rig's local bone basis, including its bone rolls and inheritance settings.
Missing tracks explicitly report a pelvis fallback, matching the viewer's rule.

Building leaves the current Action, pose, selection, frame and rest rig untouched.
Actions have a fake user so switching away does not discard them on save/reload.
Activation is explicit and rejects a changed rest rig, active bone constraints,
NLA strips or drivers rather than silently overriding them.

Root motion is preserved. Viewer ground lifting and in-place cycle playback are
presentation choices for the future browser. Source key times and scene-frame
times are baked, with float32 frame collisions merged, quaternion sign continuity,
linear curves and an endpoint held at the last key. At other subframes Blender
interpolates these baked channels; it does not evaluate the viewer live.

No animation-browser UI is registered in v2e. The v2f browser will call this API.
The separate v2d campaign-map acceptance check remains open.
