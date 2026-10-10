"""Headless browser, IWTE failure rollback, and process-lifecycle regressions."""
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time

import bpy

def addon_source():
    override = os.environ.get('MED2_ADDON_SOURCE')
    if override:
        return Path(override).resolve()
    for ancestor in Path(__file__).resolve().parents:
        for candidate in (ancestor / 'Medieval-2-Toolkit-main', ancestor):
            if (candidate / 'm2formats').is_dir() and (candidate / '__init__.py').is_file():
                return candidate
    raise FileNotFoundError('Set MED2_ADDON_SOURCE to the addon source directory')


SOURCE = addon_source()


def check(value, message):
    if not value:
        raise AssertionError(message)


def snapshot():
    return {kind: set(getattr(bpy.data, kind)) for kind in
            ('objects', 'meshes', 'armatures', 'materials', 'images', 'collections', 'actions')}


def sleeper():
    return subprocess.Popen([shutil.which('python'), '-c', 'import time; time.sleep(30)'],
                            creationflags=0x08000000 if sys.platform == 'win32' else 0)


def await_removed(path):
    deadline = time.monotonic() + 5
    while Path(path).exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    check(not Path(path).exists(), 'scratch directory was not cleaned')


with tempfile.TemporaryDirectory(prefix='v2b_ui_review_') as tmp:
    root = Path(tmp)
    dest = root / 'review_addon'
    shutil.copytree(SOURCE, dest,
                    ignore=shutil.ignore_patterns('__pycache__', '.git'))
    spec = importlib.util.spec_from_file_location('review_addon', dest / '__init__.py',
                                                  submodule_search_locations=[str(dest)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    ui = importlib.import_module('review_addon.panels.strat_import_panel')
    iwte = importlib.import_module('review_addon.tasks.strat_iwte')
    ui.showResultsPopup = lambda *args: None
    data = root / 'data'
    data.mkdir()
    (data / 'hero.cas').write_bytes(b'test')
    descriptor = data / 'descr_model_strat.txt'
    descriptor.write_text('type hero\nskeleton hero\ntexture england, missing.tga\nmodel_flexi hero.cas, max\n')
    reader = bpy.context.scene.med2_toolkit_reader
    reader.mods_filtered = 'custom'
    reader.directory_mod_data = str(data)
    check(bpy.ops.medieval2toolkit.strat_load_models() == {'FINISHED'}, 'load operator')
    browser = bpy.context.scene.med2_toolkit_strat_browser
    check(len(browser.models) == 1 and browser.faction == 'england' and browser.lod == '0', 'browser defaults')
    path, texture, metadata, notes = ui.selectedImport(bpy.context)
    check(texture == '' and notes and metadata['faction'] == 'england', 'missing texture must suppress CAS fallback')
    original_import = ui.importStratCAS
    received = []
    ui.importStratCAS = lambda context, path, **kwargs: (received.append(kwargs) or [], bpy.context.object)
    reader.backend_strat_import = 'BUILTIN'
    check(bpy.ops.medieval2toolkit.strat_import() == {'FINISHED'}, 'native operator')
    check(received[0]['texture_path'] == '', 'operator lost texture override')
    ui.importStratCAS = original_import
    descriptor.write_text('type hero\nskeleton hero\ntexture france, other_missing.tga\nmodel_flexi hero.cas, max\n')
    try:
        ui.selectedImport(bpy.context)
    except ValueError as error:
        check('faction' in str(error), str(error))
    else:
        raise AssertionError('stale faction accepted')
    check(bpy.ops.medieval2toolkit.strat_load_models() == {'FINISHED'}, 'reload operator')
    check(browser.faction == 'france', 'reload did not reset faction')
    browser['lod'] = 99
    try:
        ui.selectedImport(bpy.context)
    except ValueError as error:
        check('LOD' in str(error), str(error))
    else:
        raise AssertionError('stale LOD accepted')
    browser.lod = '0'
    original_root = ui.dataRoot
    def malformed(context):
        raise ValueError('malformed path')
    ui.dataRoot = malformed
    check(ui.selectedEntry(bpy.context) is None, 'malformed root escaped browser')
    check(not ui.MED_2_TOOLKIT_OT_Strat_Import.poll(bpy.context), 'malformed root remained importable')
    ui.dataRoot = original_root
    descriptor.write_text('type hero\nskeleton hero\nmodel_flexi hero.cas, max\n')
    check(bpy.ops.medieval2toolkit.strat_load_models() == {'FINISHED'}, 'textureless reload')
    check(ui.selectedImport(bpy.context)[1] is None, 'no descriptor texture must allow embedded fallback')
    print('PASS registration/browser/operator missing texture, stale faction, malformed root', flush=True)

    # Drive the registered operator, but isolate IWTE launch/wait/import. The
    # version gate must distinguish supported legacy fallback from corrupt CAS.
    mocked_names = ('importStratCAS', 'startStratExtract', 'waitStratExtract',
                    'finishIWTEJob', 'importStratExtract', 'showResultsPopup')
    originals = {name: getattr(ui, name) for name in mocked_names}
    launches, popups = [], []
    def reject_cas(*args, **kwargs):
        raise ui.CasError('synthetic CAS rejection')
    def fake_start(path, folder):
        launches.append(path)
        return {'output_path': 'mock-extract.glb'}
    ui.importStratCAS = reject_cas
    ui.startStratExtract = fake_start
    ui.waitStratExtract = lambda job: True
    ui.finishIWTEJob = lambda job, success: ('INFO', 'mock extraction completed')
    ui.importStratExtract = lambda *args: ([], bpy.context.object)
    ui.showResultsPopup = lambda context, title, report: popups.extend(report)
    try:
        (data / 'hero.cas').write_bytes(struct.pack('<f', 2.22))
        check(bpy.ops.medieval2toolkit.strat_import() == {'FINISHED'}, '2.x fallback operator')
        check(len(launches) == 1 and any('using IWTE' in text for level, text in popups),
              'legacy CAS did not dispatch explicit IWTE fallback')
        check(ui._import_job is None, 'completed fallback left active job')
        for corrupt in (struct.pack('<f', 3.22), b'\x00\x00'):
            (data / 'hero.cas').write_bytes(corrupt)
            try:
                result = bpy.ops.medieval2toolkit.strat_import()
            except RuntimeError as error:
                check('synthetic CAS rejection' in str(error), str(error))
            else:
                check(result == {'CANCELLED'}, 'corrupt CAS was accepted')
            check(len(launches) == 1 and ui._import_job is None,
                  'corrupt 3.x/truncated CAS dispatched IWTE')
    finally:
        for name, function in originals.items():
            setattr(ui, name, function)
        (data / 'hero.cas').write_bytes(b'test')
    print('PASS operator falls back for 2.x only; malformed 3.x/truncated CAS does not launch IWTE', flush=True)

    extract = root / 'fixture.glb'
    fixture = bpy.context.object
    fixture_material = bpy.data.materials.new('Embedded fixture')
    fixture_material.use_nodes = True
    fixture_shader = fixture_material.node_tree.nodes.get('Principled BSDF')
    fixture_image = bpy.data.images.new('Embedded image', 2, 2)
    fixture_node = fixture_material.node_tree.nodes.new('ShaderNodeTexImage')
    fixture_node.image = fixture_image
    fixture_material.node_tree.links.new(fixture_node.outputs['Color'], fixture_shader.inputs['Base Color'])
    fixture_material.node_tree.links.new(fixture_node.outputs['Alpha'], fixture_shader.inputs['Alpha'])
    fixture.data.materials.clear()
    fixture.data.materials.append(fixture_material)
    check(bpy.ops.export_scene.gltf(filepath=str(extract), use_selection=True, export_format='GLB') == {'FINISHED'}, 'GLB fixture')
    for override in (None, ''):
        report, imported_rig = iwte.importStratExtract(bpy.context, extract, data / 'hero.cas', {}, override)
        check(imported_rig is not None, str(report))
        imported_mesh = next(obj for obj in imported_rig.children_recursive if obj.type == 'MESH')
        shader = imported_mesh.data.materials[0].node_tree.nodes.get('Principled BSDF')
        check(bool(shader.inputs['Base Color'].links) == (override is None), 'IWTE embedded texture override semantics')
    # Explicitly share the existing material to ensure finalization isolates it.
    imported_mesh.data.materials[0] = fixture_material
    iwte.finalizeStratImport(bpy.context, imported_rig, {}, data / 'hero.cas', '', 'IWTE')
    neutral = imported_mesh.data.materials[0]
    check(neutral != fixture_material and not neutral.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].links,
          'missing faction texture did not isolate and neutralize material')
    check(fixture_shader.inputs['Base Color'].links and fixture_shader.inputs['Alpha'].links,
          'shared original material changed')
    check(fixture_node.image == fixture_image, 'shared original image changed')
    print('PASS IWTE None preserves embedded texture; empty override neutralizes isolated materials', flush=True)
    before = snapshot()
    selected = set(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    settings = bpy.context.scene.med2_toolkit_strat
    fields = ('model_name', 'texture_name', 'skeleton_scale', 'last_build_dir',
              'last_texture', 'last_exported_glb', 'last_cas')
    previous = {name: getattr(settings, name) for name in fields}
    original_finalize = iwte.finalizeStratImport
    def fail_after_finalize(*args, **kwargs):
        original_finalize(*args, **kwargs)
        raise RuntimeError('injected after finalizer')
    iwte.finalizeStratImport = fail_after_finalize
    report, rig = iwte.importStratExtract(bpy.context, extract, data / 'hero.cas', {}, '')
    iwte.finalizeStratImport = original_finalize
    check(rig is None and 'injected after finalizer' in str(report), 'failure injection missed')
    check(snapshot() == before, 'IWTE rollback leaked datablocks')
    check(set(bpy.context.selected_objects) == selected and bpy.context.view_layer.objects.active == active, 'IWTE rollback selection')
    check({name: getattr(settings, name) for name in fields} == previous, 'IWTE rollback export settings')
    print('PASS IWTE rollback restores datablocks, selection, and export settings', flush=True)

    # A real skinned GLB makes Blender create its Icosphere bone display mesh.
    # That helper must not become CAS geometry or receive the faction material.
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    bone_data = bpy.data.armatures.new('Skinned fixture')
    bone_rig = bpy.data.objects.new('Skinned fixture', bone_data)
    bpy.context.scene.collection.objects.link(bone_rig)
    bone_rig.select_set(True)
    bpy.context.view_layer.objects.active = bone_rig
    bpy.ops.object.mode_set(mode='EDIT')
    bone = bone_data.edit_bones.new('Root')
    bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    fixture.parent = bone_rig
    modifier = fixture.modifiers.new('Armature', 'ARMATURE')
    modifier.object = bone_rig
    fixture.vertex_groups.new(name='Root').add(list(range(len(fixture.data.vertices))), 1.0, 'REPLACE')
    fixture.select_set(True)
    skinned_extract = root / 'skinned.glb'
    check(bpy.ops.export_scene.gltf(filepath=str(skinned_extract), use_selection=True, export_format='GLB') == {'FINISHED'},
          'skinned GLB fixture')
    report, skinned_rig = iwte.importStratExtract(bpy.context, skinned_extract, data / 'hero.cas', {}, '')
    check(skinned_rig is not None, str(report))
    shapes = {bone.custom_shape for bone in skinned_rig.pose.bones if bone.custom_shape is not None}
    check(shapes, 'skinned GLB did not exercise custom bone shapes')
    check(all(shape.parent is None and shape not in skinned_rig.children_recursive for shape in shapes),
          'custom bone shape reparented into model')
    check(all(not shape.data.materials for shape in shapes), 'custom shape received faction material override')
    model_meshes = [obj for obj in skinned_rig.children_recursive if obj.type == 'MESH']
    check(len(model_meshes) == 1 and sum(len(poly.vertices) - 2 for poly in model_meshes[0].data.polygons) == 12,
          'helper geometry polluted imported model')
    print('PASS skinned GLB custom bone display shapes remain outside model and texture override', flush=True)

    scratch = tempfile.TemporaryDirectory(prefix='v2b_cleanup_')
    scratch_path = scratch.name
    process = sleeper()
    job = {'process': process, 'temporary': scratch}
    iwte.cleanupStratExtract(job)
    del scratch  # Only the cleanup worker now retains the directory owner.
    check(Path(scratch_path).exists(), 'scratch removed while converter alive')
    process.kill()
    process.wait(timeout=5)
    await_removed(scratch_path)
    process = sleeper()
    job = {'process': process, 'notes': []}
    start = time.monotonic()
    check(not iwte.waitStratExtract(job, timeout=0.05), 'headless timeout ignored')
    process.wait(timeout=5)
    check(time.monotonic() - start < 5 and 'timed out' in str(job['notes']), 'headless wait was not bounded')
    print('PASS deferred scratch cleanup and bounded background timeout', flush=True)

    scratch = tempfile.TemporaryDirectory(prefix='v2b_unregister_')
    scratch_path = scratch.name
    process = sleeper()
    ui._import_job = {'process': process, 'temporary': scratch}
    addon.unregister()
    process.wait(timeout=5)
    await_removed(scratch_path)
    check(ui._import_job is None and not hasattr(bpy.types.Scene, 'med2_toolkit_strat_browser'), 'unregister did not clear job/properties')
    print('PASS unregister aborts active converter and cleans scratch', flush=True)
print('PASS all v2b UI review regressions', flush=True)
