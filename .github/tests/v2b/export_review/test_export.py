import importlib, importlib.util, json, os, pathlib, shutil, sys, tempfile
import bpy
SOURCE = pathlib.Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in pathlib.Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent)
    if (candidate / 'm2formats').is_dir())
DATA = pathlib.Path(r'C:\Program Files (x86)\Steam\steamapps\common\Medieval II Total War\mods\Divide_and_Conquer_EUR\data')
with tempfile.TemporaryDirectory(prefix='v2b_export_') as tmp:
    dest = pathlib.Path(tmp) / 'test_addon'
    shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns('__pycache__', '.git', '.github'))
    spec = importlib.util.spec_from_file_location('test_addon', dest / '__init__.py', submodule_search_locations=[str(dest)])
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    imp = importlib.import_module('test_addon.tasks.strat_importer')
    model = importlib.import_module('test_addon.tasks.strat_model')
    image = bpy.data.images.new('selected', 64, 64)
    image.pixels[:] = [0.5, 0.3, 0.8, 1.0] * 4096
    image.filepath_raw = str(pathlib.Path(tmp) / 'selected.png')
    image.file_format = 'PNG'
    image.save()
    report, rig = imp.importStratCAS(bpy.context, DATA / 'models_strat/dunedain_diplomat.cas', texture_path=image.filepath)
    assert rig is not None, report
    out = pathlib.Path(tmp) / 'export'
    model.stratOutputFolder = lambda context, name: str(out)
    settings = bpy.context.scene.med2_toolkit_strat
    settings.texture_name = 'chosen'
    colliding_image = bpy.data.images.new('chosen', 1, 1)
    colliding_material = bpy.data.materials.new('chosen')
    # Force a distinct order so the assertion detects use of STRAT_BONES.
    order = list(reversed(json.loads(rig['med2_strat_bone_order'])))
    rig['med2_strat_bone_order'] = json.dumps(order)
    meshes = list(rig.children)
    original = [(obj, obj.data, tuple(obj.data.materials)) for obj in meshes]
    source_bytes = pathlib.Path(image.filepath).read_bytes()
    image_state = (image.filepath, image.file_format)
    counts = {key: len(getattr(bpy.data, key)) for key in ('materials', 'meshes', 'images')}
    error, path = model.exportStratGLB(bpy.context)
    assert not error, error
    payload = pathlib.Path(path).read_bytes()
    gltf = json.loads(payload[20:20 + int.from_bytes(payload[12:16], 'little')])
    assert [material['name'] for material in gltf['materials']] == ['chosen'], gltf['materials']
    assert [image['name'] for image in gltf['images']] == ['chosen'], gltf['images']
    assert colliding_image.name == 'chosen' and colliding_material.name == 'chosen'
    for skin in gltf['skins']:
        names = [gltf['nodes'][i]['name'] for i in skin['joints']]
        assert names == [name for name in order if name in names], names
    assert all(obj.data == mesh and tuple(obj.data.materials) == mats for obj, mesh, mats in original)
    assert counts == {key: len(getattr(bpy.data, key)) for key in counts}
    assert (image.filepath, image.file_format) == image_state
    assert pathlib.Path(image.filepath).read_bytes() == source_bytes
    assert pathlib.Path(settings.last_texture).exists()
    assert pathlib.Path(settings.last_texture + '.dds').stat().st_size > 0
    print('PASS imported rig GLB preserves stored joint order')
    print('PASS selected texture staging writes TGA/DDS without changing scene materials/images or source file')
    print('PASS exact GLB material/image names and original name collisions restored')
    original_writer = model.writeGameTexture
    model.writeGameTexture = lambda *args: [('WARNING', 'injected conversion failure')]
    error, path = model.exportStratGLB(bpy.context)
    assert 'injected' in error and not path
    assert counts == {key: len(getattr(bpy.data, key)) for key in counts}
    assert all(obj.data == mesh and tuple(obj.data.materials) == mats for obj, mesh, mats in original)
    print('PASS failed texture staging cleans up temporary datablocks')
    assert colliding_image.name == 'chosen' and colliding_material.name == 'chosen'
    replacement_path = pathlib.Path(tmp) / 'replacement.dds'
    replacement_bytes = pathlib.Path(settings.last_texture + '.dds').read_bytes()
    replacement_path.write_bytes(replacement_bytes)
    replacement = bpy.data.images.load(str(replacement_path), check_existing=False)
    diffuse_nodes = []
    for obj in meshes:
        for material in obj.data.materials:
            shader = model.principledNode(material)
            node = shader.inputs['Base Color'].links[0].from_node
            node.image = replacement
            diffuse_nodes.append(node)
    error, path = model.exportStratGLB(bpy.context)
    assert not error, error
    assert pathlib.Path(settings.last_texture + '.dds').read_bytes() == replacement_bytes
    assert replacement_path.read_bytes() == replacement_bytes
    assert all(node.image == replacement for node in diffuse_nodes)
    print('PASS replacement diffuse DDS exported byte-identically without re-encoding')
    # A DXT header promising a full chain must not hide truncated mip data.
    truncated_path = pathlib.Path(tmp) / 'truncated.dds'
    truncated_path.write_bytes(replacement_bytes[:128 + 64 * 64])
    truncated = bpy.data.images.load(str(truncated_path), check_existing=False)
    for node in diffuse_nodes:
        node.image = truncated
    error, path = model.exportStratGLB(bpy.context)
    assert 'injected conversion failure' in error and not path, error
    assert truncated_path.read_bytes() == replacement_bytes[:128 + 64 * 64]
    for node in diffuse_nodes:
        node.image = replacement
    print('PASS truncated DDS mip chain requires conversion instead of blind copy')
    model.writeGameTexture = original_writer
    replacement.pixels[:] = [0.8, 0.2, 0.1, 1.0] * 4096
    assert replacement.is_dirty
    error, path = model.exportStratGLB(bpy.context)
    assert not error, error
    assert pathlib.Path(settings.last_texture + '.dds').read_bytes() != replacement_bytes
    assert replacement_path.read_bytes() == replacement_bytes and replacement.is_dirty
    print('PASS painted replacement image pixels exported while original DDS and dirty image remain intact')
    extra = bpy.data.materials.new('extra_diffuse')
    extra.use_nodes = True
    node = extra.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = image
    extra.node_tree.links.new(node.outputs['Color'], model.principledNode(extra).inputs['Base Color'])
    meshes[0].data.materials.append(extra)
    error, path = model.exportStratGLB(bpy.context)
    assert 'one diffuse image' in error and not path, error
    print('PASS multiple diffuse images rejected instead of silently replaced')
    meshes[0].data.materials.pop(index=len(meshes[0].data.materials) - 1)
    for obj in meshes:
        for material in obj.data.materials:
            shader = model.principledNode(material)
            for link in list(shader.inputs['Base Color'].links):
                material.node_tree.links.remove(link)
    error, path = model.exportStratGLB(bpy.context)
    assert not error and path, error
    assert settings.last_texture == ''
    print('PASS textureless imported model clears prior staged texture')
