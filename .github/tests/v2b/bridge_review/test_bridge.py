"""Focused Blender regression checks for CAS construction and shared finalization."""
from array import array
import importlib
import os
from pathlib import Path
import sys
import types

import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent)
    if (candidate / 'm2formats/cas.py').is_file())
package = types.ModuleType('bridge_test')
package.__path__ = [str(SOURCE)]
sys.modules[package.__name__] = package
model = types.ModuleType('bridge_test.tasks.strat_model')
model.STRAT_TAG = 'med2_strat_model'
model.stratOutputFolder = lambda context, name: '/unused/' + name
sys.modules[model.__name__] = model
bridge = importlib.import_module('bridge_test.tasks.strat_importer')
cas = bridge.cas

scene = cas.CasScene(source='synthetic.cas', nodes=['Scene_Root', 'bone_pelvis', 'Particle View 01'],
                     parents=[-1, 0, 0], pivots=array('f', [0,0,0, 1,2,3, 0,0,0]))
positions = array('f', [0,0,0, 1,0,0, 0,1,0])
scene.objects = [cas.CasObject(name='skin', skinned=True, positions=positions,
                             bones=array('I', [1,1,1]), indices=array('H', [0,1,2])),
                 cas.CasObject(name='static', positions=positions, indices=array('H', [0,1,2]))]
bridge.cas.read_cas = lambda path: scene
report, rig = bridge.importStratCAS(bpy.context, 'synthetic.cas', texture_path='')
assert rig is not None, report
assert set(rig.data.bones.keys()) == {'bone_pelvis', 'Particle__View__01'}
skin = next(obj for obj in rig.children if obj.name == 'skin')
static = next(obj for obj in rig.children if obj.name == 'static')
assert tuple(skin.data.vertices[0].co) == (1,3,2)
assert tuple(static.data.vertices[0].co) == (0,0,0)
assert len(skin.modifiers) == 1 and len(static.modifiers) == 0
assert tuple(rig.scale) == (1,1,1)
print('PASS mixed static/skinned bind offsets, native scale, node aliases')

image_path = Path(__file__).with_name('faction.png')
image = bpy.data.images.new('fixture', 2, 2)
image.filepath_raw = str(image_path)
image.file_format = 'PNG'
image.save()
existing = bpy.data.materials.new('pre-existing')
existing.use_nodes = True
skin.data.materials.append(existing)
static.data.materials.append(existing)
nodes_before = len(existing.node_tree.nodes)
result = bridge.finalizeStratImport(bpy.context, rig, {'scale': 2}, 'synthetic.cas', str(image_path), 'IWTE')
assert result == []
assert skin.active_material != existing
assert skin.active_material == static.active_material
assert len(existing.node_tree.nodes) == nodes_before
assert any(node.type == 'TEX_IMAGE' and node.image.filepath == str(image_path)
           for node in skin.active_material.node_tree.nodes)
assert tuple(rig.scale) == (1,1,1)
print('PASS faction texture assigned to independent materials; shared originals untouched; report list')

scene.materials = [cas.CasMaterial(texture=str(image_path))]
scene.objects[0].material = 0
count = len(bpy.data.images)
report, second = bridge.importStratCAS(bpy.context, 'synthetic.cas', texture_path='')
assert second is not None, report
assert len(bpy.data.images) == count
assert not any(n.type == 'TEX_IMAGE' for o in second.children for m in o.data.materials
               for n in m.node_tree.nodes)
print('PASS explicit empty texture disables CAS fallback image loading')

before = {key: set(getattr(bpy.data, key)) for key in ('objects','meshes','armatures','materials','collections','images')}
class TestSettings(bpy.types.PropertyGroup):
    model_name: bpy.props.StringProperty(default='original')
    texture_name: bpy.props.StringProperty(default='original')
    skeleton_scale: bpy.props.FloatProperty(default=1)
    last_build_dir: bpy.props.StringProperty()
    last_texture: bpy.props.StringProperty()
    last_exported_glb: bpy.props.StringProperty()
    last_cas: bpy.props.StringProperty()
bpy.utils.register_class(TestSettings)
bpy.types.Scene.med2_toolkit_strat = bpy.props.PointerProperty(type=TestSettings)
selected = set(bpy.context.selected_objects)
active = bpy.context.view_layer.objects.active
original_finalizer = bridge.finalizeStratImport
def failing_finalizer(*args, **kwargs):
    original_finalizer(*args, **kwargs)
    raise RuntimeError('injected')
bridge.finalizeStratImport = failing_finalizer
report, failed = bridge.importStratCAS(bpy.context, 'synthetic.cas', texture_path='')
assert failed is None and 'injected' in report[0][1]
assert all(set(getattr(bpy.data, key)) == values for key, values in before.items())
assert set(bpy.context.selected_objects) == selected
assert bpy.context.view_layer.objects.active == active
assert bpy.context.scene.med2_toolkit_strat.model_name == 'original'
assert bpy.context.scene.med2_toolkit_strat.texture_name == 'original'
assert bpy.context.scene.med2_toolkit_strat.last_build_dir == ''
print('PASS failed import rolls back all created datablocks, selection and settings')
image_path.unlink()
