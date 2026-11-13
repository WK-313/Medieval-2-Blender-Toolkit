"""Unit Export GLB: a part that uses two materials must stay ONE primitive.
IWTE turns every glTF primitive into its own mesh part, so a hood with a hood
and a helmet material came out of the game split in two."""
import importlib, os, shutil, sys, tempfile
from pathlib import Path
import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    c for p in Path(__file__).resolve().parents for c in (p / 'Medieval-2-Toolkit-main', p) if (c / 'm2formats').is_dir())

with tempfile.TemporaryDirectory(prefix='multimat_') as temporary:
    temp = Path(temporary)
    shutil.copytree(SOURCE, temp / 'test_addon', ignore=shutil.ignore_patterns('__pycache__', '.git', 'graphify-out'))
    sys.path.insert(0, str(temp))
    addon = importlib.import_module('test_addon')
    addon.register()
    try:
        exporter = importlib.import_module('test_addon.tasks.unit_exporter')
        modelexport = importlib.import_module('test_addon.m2formats.modelexport')
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj)
        arm_data = bpy.data.armatures.new('rig')
        rig = bpy.data.objects.new('rig', arm_data)
        bpy.context.scene.collection.objects.link(rig)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')
        bone = arm_data.edit_bones.new('bone_head'); bone.head = (0, 0, 0); bone.tail = (0, 0, 1)
        bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.mesh.primitive_cube_add()
        hood = bpy.context.active_object
        hood.name = 'hood__crown_half'
        hood.parent = rig
        hood.vertex_groups.new(name='bone_head').add(range(len(hood.data.vertices)), 1.0, 'REPLACE')
        hood.modifiers.new('Armature', 'ARMATURE').object = rig
        for name in ('hood_mat', 'helmet_mat'):
            hood.data.materials.append(bpy.data.materials.new(name))
        for poly in hood.data.polygons:
            poly.material_index = 1 if poly.index < 4 else 0   # 4 helmet faces, 2 hood faces
        before = [p.material_index for p in hood.data.polygons]

        bpy.context.scene.med2_toolkit_reader.directory_unit_export = str(temp / 'out')
        settings = rig.med2_toolkit_unit_export
        settings.export_glb_name = 'multimat'
        settings.export_visible_only = False
        settings.export_animations = False
        bpy.context.view_layer.objects.active = rig
        result = exporter.exportArmatureGLB(bpy.context)
        glb = Path(settings.last_exported_glb)
        assert glb.is_file(), result
        doc, _ = modelexport.read_glb(glb.read_bytes())
        node = next(n for n in doc['nodes'] if n.get('name') == 'hood__crown_half')
        prims = doc['meshes'][node['mesh']]['primitives']
        assert len(prims) == 1, 'hood split into %d primitives' % len(prims)
        print('PASS two-material part exports as one primitive', flush=True)
        assert doc['materials'][prims[0]['material']]['name'] == 'helmet_mat', doc['materials']
        print('PASS it keeps the material with the most faces', flush=True)
        assert [p.material_index for p in hood.data.polygons] == before
        assert len(hood.data.materials) == 2
        print('PASS face materials restored after export', flush=True)
    finally:
        addon.unregister()
