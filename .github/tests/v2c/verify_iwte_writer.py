"""Independent IWTE acceptance of a CAS built without a source template.

Run in Blender with MED2_IWTE_EXE and MED2_FORMAT_SOURCE (package directory).
No game files are read or written. Scratch files are deleted on success and
retained, with IWTE stdout and decoded text, on failure. The zero pelvis keeps
the static attachment at origin while a child pivot exercises skinned geometry.
"""
from array import array
import importlib
import os
from pathlib import Path
import subprocess
import shutil
import time
import sys
import tempfile
import types

import bpy

source = Path(os.environ['MED2_FORMAT_SOURCE'])
package = types.ModuleType('writer_test_formats')
package.__path__ = [str(source)]
sys.modules[package.__name__] = package
cas = importlib.import_module(package.__name__ + '.cas')

scene = cas.CasScene(source='new.cas', version=3.2, length=0.0,
                     nodes=['Scene Root', 'bone_pelvis', 'bone_head'], parents=[-1, 0, 1],
                     pivots=array('f', [0, 0, 0, 0, 0, 0, 0.25, 0.5, 0.75]),
                     key_times=array('f', [0]))
scene.materials = [cas.CasMaterial(texture=r'textures\test.tga'),
                   cas.CasMaterial(texture=r'textures\test.tga')]
for index, skinned in enumerate((False, True)):
    scene.objects.append(cas.CasObject(
        name='skin' if skinned else 'static', skinned=skinned, material=index,
        positions=array('f', [0, 0, 0, 1, 0, 0, 0, 1, 0]),
        normals=array('f', [0, 0, 1] * 3),
        uvs=array('f', [0, 0, 1, 0, 0, 1]),
        indices=array('H', [0, 1, 2]),
        bones=array('I', [2, 2, 2] if skinned else [])))

exe = Path(os.environ['MED2_IWTE_EXE'])
folder = Path(tempfile.mkdtemp(prefix='cas_writer_iwte_'))
print('IWTE diagnostics:', folder, flush=True)
model = folder / 'new.cas'
model.write_bytes(cas.write_cas(scene))
task = folder / 'verify_task.txt'
task.write_text('\n'.join([
    '<task_id> cas_to_extract',
    '<cas_mesh_file_full_path_in> "%s"' % model.as_posix(),
    '<directory_out> "%s/"' % folder.as_posix(),
    '<extract_file_name_out> "new.glb"',
    '<cas_animation_file_format> m2',
    '<extract_file_type> glb',
    '<create_text_file> yes',
    '<create_task_file_from_input> no',
]) + '\n', encoding='utf-8')
log = (folder / 'iwte-stdout.log').open('w')
process = subprocess.Popen([str(exe), '--uh', '--st', task.as_posix()],
                           cwd=str(exe.parent), stdout=log, stderr=subprocess.STDOUT,
                           creationflags=0x08000000)
try:
    deadline = time.monotonic() + 90
    while process.poll() is None and time.monotonic() < deadline:
        if 'Traceback' in (folder / 'iwte-stdout.log').read_text(errors='replace'):
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            raise AssertionError('IWTE rejected fixture; diagnostics: ' + str(folder))
        time.sleep(0.5)
    assert process.wait(timeout=1) == 0, 'IWTE extraction failed'
except subprocess.TimeoutExpired:
    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
    process.wait(timeout=10)
    raise
finally:
    log.close()
glb = folder / 'new.glb'
assert glb.is_file(), 'IWTE did not produce a GLB'
before = set(bpy.data.objects)
assert bpy.ops.import_scene.gltf(filepath=str(glb)) == {'FINISHED'}
imported = set(bpy.data.objects) - before
shapes = {bone.custom_shape for obj in imported if obj.type == 'ARMATURE'
          for bone in obj.pose.bones if bone.custom_shape}
meshes = [obj for obj in imported if obj.type == 'MESH' and obj not in shapes]
assert sum(len(obj.data.polygons) for obj in meshes) == 2
assert {obj.name for obj in meshes} == {'static', 'skin'}
expected = [(0, 0, 0), (1, 0, 0), (0, 0, 1),
            (0.25, 0.75, 0.5), (1.25, 0.75, 0.5), (0.25, 0.75, 1.5)]
for name, targets in (('static', expected[:3]), ('skin', expected[3:])):
    obj = next(obj for obj in meshes if obj.name == name)
    points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
    assert len(points) == 3 and len(obj.data.polygons) == 1
    for point in targets:
        assert min(sum((vertex[i] - point[i]) ** 2 for i in range(3))
                   for vertex in points) < 1e-10, (name, point, points)
skin = next(obj for obj in meshes if obj.name == 'skin')
head_group = skin.vertex_groups['bone_head']
assert all(abs(head_group.weight(vertex.index) - 1.0) < 1e-6
           for vertex in skin.data.vertices)
rig = next(obj for obj in imported if obj.type == 'ARMATURE')
head = rig.matrix_world @ rig.data.bones['bone_head'].head_local
assert (head - __import__('mathutils').Vector((0.25, 0.75, 0.5))).length < 1e-5, head
print('PASS IWTE independently reads fresh static/skinned CAS with correct geometry and pivots')

shutil.rmtree(folder)
