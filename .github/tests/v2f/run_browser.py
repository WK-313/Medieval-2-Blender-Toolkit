"""Headless browser operators, cache invalidation, pose-library and real-rig checks."""
from array import array
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types

import bpy
from mathutils import Matrix

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent/'Medieval-2-Toolkit-main', parent) if (candidate/'m2formats').is_dir())
work = tempfile.TemporaryDirectory(prefix='v2f_browser_')
root = Path(work.name)
copy = root/'browser_addon'
shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns('__pycache__', '.git', '.github', 'text', 'images'))
sys.path.insert(0,str(root))
addon=importlib.import_module('browser_addon'); addon.register()
panel=importlib.import_module('browser_addon.panels.animation_panel')
browser=panel.browser; engine=panel.engine; ca=engine.casanim
poses=importlib.import_module('browser_addon.tasks.pose_library')
panel.showResultsPopup=lambda *args: None
scene=bpy.context.scene; settings=scene.med2_toolkit_animations
reader=scene.med2_toolkit_reader
reader.mods_filtered='custom'

def select(rig):
    bpy.ops.object.select_all(action='DESELECT')
    rig.select_set(True); bpy.context.view_layer.objects.active=rig

def play(index):
    settings.active_index=index
    assert bpy.ops.medieval2toolkit.animation_play()=={'FINISHED'}
    return bpy.context.object.animation_data.action

def load(data,skeleton):
    reader.directory_mod_data=str(data)
    assert bpy.ops.medieval2toolkit.animation_refresh()=={'FINISHED'}
    settings.skeleton=skeleton
    assert bpy.ops.medieval2toolkit.animation_load()=={'FINISHED'}

def rejected(call):
    try: result=call()
    except RuntimeError: return
    assert result=={'CANCELLED'}, result

try:
    data=root/'data'; (data/'animations').mkdir(parents=True)
    def loose(marker):
        return ca.write_anim(ca.Animation(source='a.cas',length=.1,key_times=array('f',[0,.1]),tracks=[
            ca.Track('Scene Root',-1,(0,0,0)),
            ca.Track('bone_pelvis',0,(0,0,0),pos=array('f',[0,marker,0,0,marker+1,0]))]))
    (data/'animations/a.cas').write_bytes(loose(0))
    (data/'animations/b.cas').write_bytes(loose(2))
    (data/'descr_skeleton.txt').write_text('type Test\nanim stand_a_idle data/animations/a.cas\nanim walk data/animations/b.cas\nanim broken data/animations/missing.cas\n')
    arm=bpy.data.armatures.new('Test'); rig=bpy.data.objects.new('Test',arm); scene.collection.objects.link(rig); select(rig)
    bpy.ops.object.mode_set(mode='EDIT'); bone=arm.edit_bones.new('bone_pelvis'); bone.head=(0,0,0); bone.tail=(0,0,1); bpy.ops.object.mode_set(mode='OBJECT')
    load(data,'Test')
    assert len(settings.actions)==3
    assert [item.family for item in settings.actions]==['stand','move','other']
    assert settings.actions[0].frames==2 and abs(settings.actions[0].duration-.1)<1e-6
    assert settings.actions[2].error
    a=play(0); b=play(1); assert a!=b and play(0)==a
    assert len([x for x in bpy.data.actions if x.get('med2_animation_cache')])==2
    assert scene.use_preview_range and scene.frame_preview_start==1 and scene.frame_preview_end==4
    print('PASS catalogue groups, counts, duration, missing rows, operators and Action reuse',flush=True)
    before=set(bpy.data.actions); settings.active_index=2
    rejected(lambda:bpy.ops.medieval2toolkit.animation_play())
    assert set(bpy.data.actions)==before and rig.animation_data.action==a
    constraint=rig.pose.bones[0].constraints.new('COPY_LOCATION')
    settings.active_index=1
    rejected(lambda:bpy.ops.medieval2toolkit.animation_play())
    assert rig.animation_data.action==a
    rig.pose.bones[0].constraints.remove(constraint)
    reader.directory_mod_data=str(root/'other'); assert panel.selectedAction(bpy.context) is None
    reader.directory_mod_data=str(data); settings.skeleton='Other'; assert panel.selectedAction(bpy.context) is None
    settings.skeleton='Test'
    rig.animation_data.action_influence=.5
    rejected(lambda:bpy.ops.medieval2toolkit.animation_play())
    assert rig.animation_data.action==a
    rig.animation_data.action_influence=1
    print('PASS errors leave current Action intact; stale mod and skeleton selections rejected',flush=True)
    (data/'animations/a.cas').write_bytes(loose(4)); changed=play(0); assert changed!=a
    curve=next(poses.actionFCurves(changed)); curve.keyframe_points[0].co[1]+=2
    edited=play(0); assert edited!=changed
    scene.render.fps=30; fps_action=play(0); assert fps_action!=edited
    print('PASS source, edited curves and scene FPS invalidate cached Actions',flush=True)
    assert poses.animationSummary(rig)
    poses.clearAnimation(rig)
    assert not list(poses.actionFCurves(fps_action))
    rebuilt=play(0); assert rebuilt!=fps_action and poses.animationSummary(rig)
    poses.clearAnimation(rig)
    pose=bpy.data.actions.new('Pose'); slot=pose.slots.new('OBJECT',rig.name)
    bag=pose.layers.new('Pose').strips.new(type='KEYFRAME').channelbags.new(slot)
    f=bag.fcurves.new(rig.pose.bones[0].path_from_id('location'),index=0); f.keyframe_points.insert(1,3)
    poses.applyPoseAction(rig,pose)
    assert abs(rig.pose.bones[0].location.x-3)<1e-6
    scene.render.fps=24
    assert play(1)==b
    print('PASS pose-library clear/apply then animation switching; cleared cache rebuilt',flush=True)
    # Both layouts register/draw the browser; all data-bound properties must exist.
    class Layout:
        def __getattr__(self,name):
            if name in ('prop','prop_search'): return lambda obj,prop,*a,**kw:getattr(obj,prop)
            if name=='template_list': return lambda _id,_list,obj,prop,*a,**kw:getattr(obj,prop)
            if name=='operator': return lambda *a,**kw:types.SimpleNamespace()
            return lambda *a,**kw:self
    panel.MED_2_TOOLKIT_PT_Animations.draw(types.SimpleNamespace(layout=Layout()),bpy.context)
    multi=importlib.import_module('browser_addon.panels.multi_panel')
    multi.applyPanelLayout(True); assert panel.MED_2_TOOLKIT_PT_Animations in multi._registered_panels
    multi.applyPanelLayout(False)
    print('PASS browser draw and classic/strip registration',flush=True)
    game=os.environ.get('MED2_ANIMATION_DATA')
    if game:
        bpy.ops.import_scene.gltf(filepath=str(copy/'armatures/Sword.glb'))
        battle=next(o for o in bpy.context.selected_objects if o.type=='ARMATURE'); select(battle)
        load(Path(game),'MTW2_Mace')
        valid=[i for i,item in enumerate(settings.actions) if not item.error and item.family in {'stand','move'}]
        assert len(valid)>1
        first=play(valid[0]); second=play(valid[1]); assert first!=second and play(valid[0])==first
        settings.skeleton='MTW2_Fast_Bowman'; bpy.ops.medieval2toolkit.animation_load(); play(next(i for i,x in enumerate(settings.actions) if not x.error))
        strat=importlib.import_module('browser_addon.tasks.strat_model')
        strat_rig=strat.buildStratArmature(bpy.context,bpy.context.collection,'Strat',False,Matrix.Identity(4)); select(strat_rig)
        strat_rig['med2_strat_import_metadata']=json.dumps({'skeleton':'strat_diplomat'})
        bpy.ops.medieval2toolkit.animation_refresh(); assert settings.skeleton=='strat_diplomat'
        bpy.ops.medieval2toolkit.animation_load()
        valid=[i for i,x in enumerate(settings.actions) if not x.error]; assert len(valid)>1
        first=play(valid[0]); second=play(valid[1]); assert first!=second and play(valid[0])==first
        print('PASS real battle/strat action switching, skeleton switching, strat metadata selection',flush=True)
    # Persisted lists and Action metadata are usable after reload.
    saved=bpy.context.object.name
    selected=settings.active_index
    expected=bpy.context.object.animation_data.action.name
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'browser.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'browser.blend'))
    scene=bpy.context.scene; settings=scene.med2_toolkit_animations; reader=scene.med2_toolkit_reader
    select(bpy.data.objects[saved]); assert play(selected).name==expected
    print('PASS cached Action reuse after blend save/reload',flush=True)
finally:
    addon.unregister()
    work.cleanup()
print('PASS v2f animation browser',flush=True)
