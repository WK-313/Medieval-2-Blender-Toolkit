"""Headless Action/skin checks against Unit Transfer's actual viewer arithmetic."""
from array import array
import copy
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types

import bpy
from mathutils import Matrix, Vector

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent)
    if (candidate / 'm2formats').is_dir())
package = types.ModuleType('animation_test')
package.__path__ = [str(SOURCE)]
sys.modules[package.__name__] = package
engine = importlib.import_module(package.__name__ + '.tasks.animation_engine')
casanim = engine.casanim


def viewer(animation, times):
    path = Path(os.environ['MED2_VIEWER_JS'])
    node = shutil.which('node')
    assert node, 'node is required for the independent viewer oracle'
    script = path.read_text(encoding='utf-8').split('/* --- the picker')[0]
    payload = {'anim': {'length': animation.length, 'times': list(animation.key_times), 'bones': [
        {'name': t.name, 'parent': t.parent, 'pivot': list(t.pivot),
         'rot': [list(t.rot[i:i+4]) for i in range(0, len(t.rot), 4)],
         'pos': [list(t.pos[i:i+3]) for i in range(0, len(t.pos), 3)]} for t in animation.tracks]},
        'times': [min(t, max(0, animation.key_times[-1] - 1e-9)) if animation.key_times else t for t in times]}
    script += '\nconst a=JSON.parse(require("fs").readFileSync(0,"utf8"));'
    script += '\nconsole.log(JSON.stringify({bind:v3aBind(a.anim),poses:a.times.map(t=>v3aPose(a.anim,t))}));'
    result = subprocess.run([node, '-e', script], input=json.dumps(payload), text=True,
                            capture_output=True, check=True, timeout=30)
    return json.loads(result.stdout)


def matricesNear(first, second, tolerance=8e-5):
    return max(abs(first[r][c]-second[r][c]) for r in range(4) for c in range(4)) < tolerance


def rigState(rig):
    return (rig.animation_data.action if rig.animation_data else None,
            engine.rigSignature(rig), [(p.name, p.rotation_mode, tuple(p.location),
                tuple(p.rotation_quaternion), tuple(p.scale)) for p in rig.pose.bones],
            bpy.context.scene.frame_current, list(bpy.context.selected_objects),
            bpy.context.view_layer.objects.active, tuple(v for row in rig.matrix_world for v in row))


def exercise(rig, animation, label, mesh=None):
    old = bpy.data.actions.new(label + ' existing')
    rig.animation_data_create().action = old
    rig.pose.bones[0].rotation_mode = 'XYZ'
    state = rigState(rig)
    report, action = engine.buildAnimationAction(rig, animation, fps=24, start_frame=7)
    assert action.use_fake_user
    assert rigState(rig) == state, 'Building an Action changed the existing rig/action/selection/frame'
    assert old in set(bpy.data.actions), 'Existing Action was deleted'
    end = float(animation.key_times[-1]) if animation.key_times else 0
    times = sorted(set([0, end, *[float(animation.key_times[i]) for i in
                       range(0, len(animation.key_times), max(1, len(animation.key_times)//4))],
                       *[i/24 for i in (1, 3, 7) if i/24 <= end]]))
    reference = viewer(animation, times)
    names = {engine._nameKey(t.name): i for i, t in enumerate(animation.tracks)}
    hub = next((i for i, t in enumerate(animation.tracks) if t.parent == 0), 0)
    boneMap = {b.name: names.get(engine._nameKey(b.get('med2_cas_node_name', b.name)), hub) for b in rig.data.bones}
    engine.activateAnimationAction(rig, action)
    for t, poses in zip(times, reference['poses']):
        frame = 7 + t*24
        bpy.context.scene.frame_set(int(math.floor(frame)), subframe=frame-math.floor(frame))
        bpy.context.view_layer.update()
        expected = {}
        for bone in rig.data.bones:
            index = boneMap[bone.name]
            ref = poses[index]
            world = Matrix([ref['m'][r*3:r*3+3] + [ref['p'][r]] for r in range(3)] + [[0,0,0,1]])
            deform = engine.CAS_TO_BLENDER @ world @ Matrix.Translation(-Vector(reference['bind'][index])) @ engine.CAS_TO_BLENDER
            expected[bone.name] = deform
            assert matricesNear(rig.pose.bones[bone.name].matrix, deform @ bone.matrix_local), (label, t, bone.name)
        if mesh:
            evaluated = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
            snapshot = evaluated.to_mesh()
            try:
                for v, result in zip(mesh.data.vertices, snapshot.vertices):
                    point = Vector((0,0,0))
                    for group in v.groups:
                        point += group.weight * (expected[mesh.vertex_groups[group.group].name] @ v.co)
                    assert (result.co-point).length < 8e-5, (label, t, v.index, result.co, point)
            finally:
                evaluated.to_mesh_clear()
    print('PASS', label, ': Blender bone matrices' + (' and two-weight mesh skin' if mesh else ''),
          'match actual v3aPose/v3aBind at', len(times), 'source/frame/endpoint samples')
    return action, report


# Arbitrary rolls, a missing track, animated root/pelvis and quaternion sign flip.
data = bpy.data.armatures.new('Test bones')
rig = bpy.data.objects.new('Test rig', data)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
for name, parent, head, tail in [('bone_pelvis', '', (0,0,0), (0,1,0)),
        ('bone_head','bone_pelvis',(0.1,0.2,0.7),(0.3,0.5,1.0)),
        ('unmapped_prop','bone_head',(0.7,0.1,0.5),(1.0,0.3,0.9))]:
    bone = data.edit_bones.new(name)
    bone.head, bone.tail = head, tail
    bone.roll = 0.35
    if parent:
        bone.parent = data.edit_bones[parent]
bpy.ops.object.mode_set(mode='OBJECT')
rig.matrix_world = Matrix.Translation((2,3,4)) @ Matrix.Rotation(.3,4,'Z')
rig.data.bones['bone_head'].use_inherit_rotation = False
rig.data.bones['bone_head'].use_local_location = False
animation = casanim.Animation(source='synthetic.cas', length=1, key_times=array('f',[0,.5,1]), tracks=[
    casanim.Track('Scene Root',-1,(.1,.2,.3),rot=array('f',[0,0,math.sin(.1),math.cos(.1)])),
    casanim.Track('bone_pelvis',0,(0,0,0),rot=array('f',[0,0,0,1, 0,math.sin(.4),0,math.cos(.4), 0,0,0,-1]),
                  pos=array('f',[0,.9,0, .1,1,.3, .2,.9,.6])),
    casanim.Track('bone_head',1,(.1,.7,.2),rot=array('f',[0,0,0,1, math.sin(.3),0,0,math.cos(.3), 0,0,0,1]))])
mesh_data = bpy.data.meshes.new('Skin')
mesh_data.from_pydata([(0,.2,.4),(.2,.3,.7),(.4,.1,.8)],[],[(0,1,2)])
mesh = bpy.data.objects.new('Skin', mesh_data)
bpy.context.collection.objects.link(mesh)
mesh.parent = rig
modifier = mesh.modifiers.new('Rig','ARMATURE')
modifier.object = rig
mesh.vertex_groups.new(name='bone_pelvis').add([0,1,2],.35,'REPLACE')
mesh.vertex_groups.new(name='bone_head').add([0,1,2],.65,'REPLACE')
action, report = exercise(rig, animation, 'synthetic arbitrary bone rolls', mesh)
assert any('unmapped_prop -> bone_pelvis' in line for _, line in report)
print('PASS missing tracks report each pelvis fallback; existing Actions and pose library are preserved')
short = copy.deepcopy(animation)
short.length = .1
short.key_times = array('f',[0,.05,.1])
_, short_action = engine.buildAnimationAction(rig,short,fps=20)
bag = short_action.layers[0].strips[0].channelbags[0]
for curve in bag.fcurves:
    coordinates = [p.co.x for p in curve.keyframe_points]
    assert coordinates == [1,2,3], coordinates
print('PASS float32 source/scene time collisions produce one key per frame')

# Failures precede Action creation or activation; no replacement/partial asset.
for change in ('zero quaternion','cyclic parents','nonfinite','bad counts','bad times'):
    bad = copy.deepcopy(animation)
    if change == 'zero quaternion': bad.tracks[1].rot[:4] = array('f',[0]*4)
    elif change == 'cyclic parents': bad.tracks[1].parent = 1
    elif change == 'nonfinite': bad.tracks[1].pos[0] = float('nan')
    elif change == 'bad counts': bad.tracks[1].pos.extend([0,0,0])
    else: bad.key_times[1] = -1
    before = set(bpy.data.actions)
    try:
        engine.buildAnimationAction(rig, bad)
        raise AssertionError('Accepted ' + change)
    except ValueError:
        pass
    assert before == set(bpy.data.actions)
constraint = rig.pose.bones[0].constraints.new('COPY_TRANSFORMS')
try:
    engine.activateAnimationAction(rig, action)
    raise AssertionError('Active constraint accepted')
except ValueError:
    pass
rig.pose.bones[0].constraints.remove(constraint)
bone = rig.data.bones[0]
original = bone.use_local_location
bone.use_local_location = not original
try:
    engine.activateAnimationAction(rig, action)
    raise AssertionError('Changed rest signature accepted')
except ValueError:
    pass
bone.use_local_location = original
driver = rig.pose.bones['bone_head'].driver_add('location',0)
try:
    engine.activateAnimationAction(rig,action)
    raise AssertionError('Active bone driver accepted')
except ValueError:
    pass
driver.mute = True
engine.activateAnimationAction(rig,action)
rig.pose.bones['bone_head'].driver_remove('location',0)
track = rig.animation_data.nla_tracks.new()
track.strips.new('Old pose',1,short_action)
try:
    engine.activateAnimationAction(rig,action)
    raise AssertionError('Active NLA strip accepted')
except ValueError:
    pass
rig.animation_data.use_nla = False
engine.activateAnimationAction(rig,action)
rig.animation_data.nla_tracks.remove(track)
rig.animation_data.use_nla = True
print('PASS invalid keys/time/hierarchy do not create Actions; constraints and changed rest rigs refuse activation')
print('PASS active bone drivers/NLA refuse activation; muted drivers and disabled NLA allow it')

if os.environ.get('MED2_ANIMATION_DATA'):
    root = Path(os.environ['MED2_ANIMATION_DATA'])
    imported = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(SOURCE/'armatures/Sword.glb'))
    battle = next(o for o in set(bpy.data.objects)-imported if o.type=='ARMATURE')
    battle_anim = engine.loadAnimation(root,'MTW2_Mace',slot=0)
    bind = []
    for track in battle_anim.tracks:
        bind.append((bind[track.parent] if track.parent >= 0 else Vector((0,0,0))) + Vector(track.pivot))
    for name in ('bone_pelvis','bone_head','bone_RThigh'):
        index = next(i for i, t in enumerate(battle_anim.tracks) if t.name == name)
        x,y,z = bind[index]
        assert (battle.data.bones[name].head_local-Vector((x,z,y))).length < 5e-5
    print('PASS independent CAS bind positions confirm bundled rig Y/Z reflection')
    exercise(battle, battle_anim, 'real battle MTW2_Mace on bundled Sword')
    strat = importlib.import_module(package.__name__+'.tasks.strat_model')
    strat_rig = strat.buildStratArmature(bpy.context,bpy.context.collection,'Strat animation test',False,Matrix.Identity(4))
    strat_anim = engine.loadAnimation(root,'strat_diplomat',slot=0)
    exercise(strat_rig, strat_anim, 'real strat diplomat on bundled strat rig')
    # Two skeletons/actions on the same rig; the first Action remains intact.
    previous_action = battle.animation_data.action
    exercise(battle,engine.loadAnimation(root,'MTW2_Mace',slot=11),'real battle walk/root motion')
    exercise(battle,engine.loadAnimation(root,'MTW2_Fast_Bowman',slot=0),'real archer skeleton on existing Sword rig')
    assert previous_action in set(bpy.data.actions)
    print('PASS pack actions switch on an existing rig without reimport or overwriting old Actions')
else:
    print('SKIP real mod actions: set MED2_ANIMATION_DATA')
saved_names = [a.name for a in bpy.data.actions if a.get('med2_animation')]
with tempfile.TemporaryDirectory(prefix='v2e_persistence_') as folder:
    filename = str(Path(folder)/'actions.blend')
    bpy.ops.wm.save_as_mainfile(filepath=filename)
    bpy.ops.wm.open_mainfile(filepath=filename)
    assert all(name in bpy.data.actions and bpy.data.actions[name].use_fake_user for name in saved_names)
    print('PASS assigned and cached unassigned Actions survive actual blend save/reload:',len(saved_names))
print('PASS v2e animation engine')
