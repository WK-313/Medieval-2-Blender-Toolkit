"""Headless native strat export checks; synthetic assets, isolated addon copy."""
from array import array
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import bpy
from mathutils import Vector

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent)
    if (candidate / 'm2formats').is_dir())

with tempfile.TemporaryDirectory(prefix='v2d_export_') as temporary:
    tmp = Path(temporary)
    dest = tmp / 'test_addon'
    shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns('__pycache__', '.git', '.github'))
    spec = importlib.util.spec_from_file_location('test_addon', dest / '__init__.py', submodule_search_locations=[str(dest)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    cas = importlib.import_module('test_addon.m2formats.cas')
    importer = importlib.import_module('test_addon.tasks.strat_importer')
    model = importlib.import_module('test_addon.tasks.strat_model')
    bridge = importlib.import_module('test_addon.tasks.strat_cas_export')
    panel = importlib.import_module('test_addon.panels.strat_panel')
    fixture = cas.CasScene(source='fixture.cas', version=3.2,
        nodes=['Scene Root', 'bone_pelvis', 'bone_head'], parents=[-1, 0, 1],
        pivots=array('f', [0, 0, 0, 0, 0, 0, 0.25, 0.5, 0.75]), key_times=array('f', [0]),
        materials=[cas.CasMaterial(texture='textures/fixture.tga')])
    fixture.objects = [cas.CasObject(name='body', skinned=True, material=0,
        positions=array('f', [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]),
        normals=array('f', [0, 0, 1] * 4), uvs=array('f', [0, 0, 1, 0, 1, 1, 0, 1]),
        bones=array('I', [2] * 4), indices=array('H', [0, 1, 2, 0, 2, 3]))]
    path = tmp / 'fixture.cas'
    path.write_bytes(cas.write_cas(fixture))
    image = bpy.data.images.new('diffuse', 16, 16)
    image.pixels[:] = [0.6, 0.2, 0.1, 1.0] * 256
    image.filepath_raw = str(tmp / 'diffuse.png')
    image.file_format = 'PNG'
    image.save()
    report, rig = importer.importStratCAS(bpy.context, path, texture_path=image.filepath)
    obj = next(o for o in rig.children if o.type == 'MESH')
    out = tmp / 'export'
    model.stratOutputFolder = lambda context, name: str(out)
    settings = bpy.context.scene.med2_toolkit_strat
    reader = bpy.context.scene.med2_toolkit_reader
    reader.backend_strat_export = 'BUILTIN'
    reader.directory_iwte = str(tmp / 'absent_iwte')
    settings.model_name = 'native'
    settings.texture_name = 'chosen'
    # A shared vertex has two distinct UVs and corner normals.
    obj.data.uv_layers.active.data[4].uv = (0.2, 0.3)
    obj.data.normals_split_custom_set([(0, 1, 0)] * 3 + [(0, 0.70710678, 0.70710678)] * 3)
    rig.location = (2, 3, 4)
    obj.scale = (-1, 2, 1)
    rig.pose.bones['bone_head'].location = (5, 6, 7)
    bpy.context.view_layer.update()
    selection = (list(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    counts = {key: len(getattr(bpy.data, key)) for key in ('materials', 'meshes', 'images')}
    old_mesh = obj.data
    old_pose = rig.data.pose_position
    expected = [obj.matrix_world @ v.co for v in obj.data.vertices]
    scene = bridge.stratCasScene(bpy.context, rig, 'textures\\chosen.tga')
    decoded = cas.posed_positions(scene.objects[0], cas.bind_world(scene))
    points = [Vector((decoded[i], decoded[i + 2], decoded[i + 1])) for i in range(0, len(decoded), 3)]
    assert scene.nodes == ['Scene Root', 'bone_pelvis', 'bone_head'], scene.nodes
    assert scene.parents == [-1, 0, 1]
    assert scene.objects[0].vertices == 6, 'UV or custom normal seam was merged'
    assert all(min((p - v).length for p in points) < 1e-5 for v in expected)
    assert rig.data.pose_position == old_pose and obj.data == old_mesh
    assert all(b == 2 for b in scene.objects[0].bones)
    # Normals and winding must agree after axis reflection and negative scale.
    chunk = scene.objects[0]
    for i in range(0, len(chunk.indices), 3):
        a, b, c = (Vector(chunk.positions[3*j:3*j+3]) for j in chunk.indices[i:i+3])
        n = Vector(chunk.normals[3*chunk.indices[i]:3*chunk.indices[i]+3])
        assert (b-a).cross(c-a).dot(n) > 0
    print('PASS rest geometry, translated pivots, mirrored scale, winding, UV seams and bone indices')
    modifier = obj.modifiers[0]
    modifier.show_viewport = False
    try:
        static = bridge.stratCasScene(bpy.context, rig, 'textures\\chosen.tga')
        assert set(static.objects[0].bones) == {0}
    finally:
        modifier.show_viewport = True
    modifier.vertex_group = 'bone_head'
    try:
        bridge.stratCasScene(bpy.context, rig, 'textures\\chosen.tga')
        raise AssertionError('Masked armature modifier accepted')
    except ValueError as error:
        assert 'vertex groups only' in str(error)
    finally:
        modifier.vertex_group = ''
    rig.data.bones['bone_head'].use_deform = False
    try:
        bridge.stratCasScene(bpy.context, rig, 'textures\\chosen.tga')
        raise AssertionError('Non-deforming skin bone accepted')
    except ValueError as error:
        assert 'non-deforming' in str(error)
    finally:
        rig.data.bones['bone_head'].use_deform = True
    order = rig['med2_strat_bone_order']
    rig['med2_strat_bone_order'] = '["missing"]'
    try:
        bridge.stratCasScene(bpy.context, rig, 'textures\\chosen.tga')
        raise AssertionError('Invalid bone order accepted')
    except ValueError as error:
        assert 'bone order' in str(error)
    finally:
        rig['med2_strat_bone_order'] = order
    print('PASS static geometry binds to Scene Root and stale bone order is refused')
    model.startIWTETask = lambda *args: (_ for _ in ()).throw(AssertionError('IWTE must not run'))
    result = model.exportStratCAS(bpy.context)
    assert isinstance(result, dict) and result.get('builtin'), result
    output = Path(settings.last_cas)
    reread = cas.read_cas(output)
    assert reread.triangles == 2 and reread.textures() == ['textures\\chosen.tga']
    assert (out / 'textures/chosen.tga.dds').is_file()
    assert all(level != 'ERROR' for level, _ in model.checkCASTexture(bpy.context))
    assert counts == {key: len(getattr(bpy.data, key)) for key in counts}
    assert selection == (list(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    assert old_mesh == obj.data and rig.data.pose_position == old_pose
    print('PASS built-in CAS export with missing IWTE, matching texture, clean scene and restored pose/selection')
    saved = output.read_bytes()
    pelvis_group = obj.vertex_groups.new(name='bone_pelvis')
    pelvis_group.add([0], 0.5, 'REPLACE')
    result = model.exportStratCAS(bpy.context)
    assert isinstance(result, str) and 'exactly one' in result, result
    assert output.read_bytes() == saved and rig.data.pose_position == old_pose
    obj.vertex_groups['bone_pelvis'].remove([0])
    print('PASS ambiguous skinning refused without overwriting prior CAS')
    settings.cas_format = 'rr'
    assert 'supports M2' in model.exportStratCAS(bpy.context)
    settings.cas_format = 'm2'
    settings.skeleton_scale = 2
    assert 'scale 1.0' in model.exportStratCAS(bpy.context)
    settings.skeleton_scale = 1
    settings.model_name = '../escape'
    assert 'without folders' in model.exportStratCAS(bpy.context)
    settings.model_name = 'native'
    print('PASS unsupported format, scale and unsafe output names refused')
    original_replace = model.os.replace
    def refuse_replace(*args):
        if Path(args[0]).name.startswith('.strat-'):
            raise OSError('injected replacement failure')
        return original_replace(*args)
    model.os.replace = refuse_replace
    try:
        assert 'injected replacement failure' in model.exportStratCAS(bpy.context)
        assert output.read_bytes() == saved
        assert not list(out.glob('.strat-*.cas'))
    finally:
        model.os.replace = original_replace
    print('PASS failed atomic replacement preserves previous CAS and removes temporary files')
    material = obj.data.materials[0]
    shader = model.principledNode(material)
    link = shader.inputs['Base Color'].links[0]
    source_socket = link.from_socket
    material.node_tree.links.remove(link)
    try:
        assert 'diffuse image' in model.exportStratCAS(bpy.context)
        assert output.read_bytes() == saved
    finally:
        material.node_tree.links.new(source_socket, shader.inputs['Base Color'])
    print('PASS missing diffuse refuses export instead of reusing stale texture state')
    # Native UI conversion does not require a previous GLB and starts no modal.
    settings.last_exported_glb = ''
    assert panel.MED_2_TOOLKIT_OT_Strat_Convert_CAS.poll(bpy.context)
    assert bpy.ops.medieval2toolkit.strat_convert_cas() == {'FINISHED'}
    assert panel._iwte_job is None
    assert bpy.ops.medieval2toolkit.strat_build_and_convert() == {'FINISHED'}
    print('PASS Convert and Build + Convert operators finish synchronously with Built-in')
    # Existing IWTE path remains available, including its executable validation.
    reader.backend_strat_export = 'IWTE'
    assert model.exportStratCAS(bpy.context) == 'Invalid IWTE folder'
    print('PASS IWTE routing retained')
    if os.environ.get('MED2_IWTE_EXE'):
        exe = Path(os.environ['MED2_IWTE_EXE'])
        diagnostics = Path(tempfile.mkdtemp(prefix='v2d_iwte_'))
        print('IWTE diagnostics:', diagnostics, flush=True)
        independent_cas = diagnostics / 'native.cas'
        independent_cas.write_bytes(output.read_bytes())
        task = diagnostics / 'verify_task.txt'
        task.write_text('\n'.join([
            '<task_id> cas_to_extract',
            '<cas_mesh_file_full_path_in> "%s"' % independent_cas.as_posix(),
            '<directory_out> "%s/"' % diagnostics.as_posix(),
            '<extract_file_name_out> "native.glb"',
            '<cas_animation_file_format> m2', '<extract_file_type> glb',
            '<create_text_file> yes', '<create_task_file_from_input> no']) + '\n')
        with (diagnostics / 'iwte.log').open('w') as log:
            process = subprocess.Popen([str(exe), '--uh', '--st', task.as_posix()], cwd=exe.parent,
                stdout=log, stderr=subprocess.STDOUT, creationflags=0x08000000)
            try:
                assert process.wait(timeout=90) == 0
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                process.wait(timeout=10)
                raise
        independent = diagnostics / 'native.glb'
        assert independent.is_file(), (diagnostics / 'iwte.log').read_text(errors='replace')
        before = set(bpy.data.objects)
        assert bpy.ops.import_scene.gltf(filepath=str(independent)) == {'FINISHED'}
        imported = set(bpy.data.objects) - before
        shapes = {b.custom_shape for o in imported if o.type == 'ARMATURE' for b in o.pose.bones if b.custom_shape}
        native_meshes = [o for o in imported if o.type == 'MESH' and o not in shapes]
        actual = [o.matrix_world @ v.co for o in native_meshes for v in o.data.vertices]
        assert sum(len(o.data.polygons) for o in native_meshes) == 2
        assert all(min((p - v).length for p in actual) < 1e-4 for v in expected), (actual, expected)
        assert all(min((p - v).length for v in expected) < 1e-4 for p in actual)
        print('PASS independent IWTE reader matches native Blender export geometry, rest pivots and triangle count')
        shutil.rmtree(diagnostics)
    # Optional independent decoder: retain native output for the IWTE harness.
    if os.environ.get('MED2_V2D_OUTPUT'):
        shutil.copytree(out, os.environ['MED2_V2D_OUTPUT'], dirs_exist_ok=True)
    # Exercise the full build on a battle-style source with no strat tag.
    for selected in bpy.context.selected_objects:
        selected.select_set(False)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    del rig[model.STRAT_TAG]
    rig.pose.bones['bone_head'].location = (0, 0, 0)
    rig.location = (0, 0, 0)
    obj.scale = (1, 1, 1)
    settings.model_name = 'built'
    settings.texture_name = 'atlas'
    settings.atlas_size = '1024'
    reader.backend_strat_export = 'BUILTIN'
    assert bpy.ops.medieval2toolkit.strat_build_and_convert() == {'FINISHED'}
    built = cas.read_cas(settings.last_cas)
    assert len(built.nodes) == 21 and built.triangles == 2
    assert built.textures() == ['textures\\atlas.tga']
    assert (out / 'textures/atlas.tga.dds').is_file()
    print('PASS complete battle-style Build + Convert creates canonical strat skeleton, atlas and CAS without IWTE')
    if os.environ.get('MED2_GAME_GATE_CAS'):
        source_cas = Path(os.environ['MED2_GAME_GATE_CAS'])
        decoded_source = cas.read_cas(source_cas)
        material = next(m for m in decoded_source.materials if m.texture)
        texture_path = cas.texture_path(source_cas, material.texture)
        assert texture_path is not None and texture_path.is_file(), material.texture
        report, game_rig = importer.importStratCAS(bpy.context, source_cas, texture_path=texture_path)
        assert game_rig is not None, report
        gate = Path(os.environ['MED2_GAME_GATE_OUTPUT'])
        model.stratOutputFolder = lambda context, name: str(gate)
        settings.model_name = source_cas.stem
        result = model.exportStratCAS(bpy.context)
        assert isinstance(result, dict) and result.get('builtin'), result
        assert cas.read_cas(settings.last_cas).triangles == sum(len(o.data.polygons) for o in game_rig.children if o.type == 'MESH')
        print('PASS real mod CAS exported for campaign-map gate:', settings.last_cas)
    addon.unregister()
