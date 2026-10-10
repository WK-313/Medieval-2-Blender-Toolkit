"""IWTE extraction used by the Strat browser and unsupported CAS fallback."""
import os
import tempfile
import subprocess
import threading
import time
from pathlib import Path

import bpy

from .iwte_run import (IWTE_OUTPUT_TIMEOUT, IWTE_TASK_TIMEOUT, abortIWTEJob,
                       findIWTEExe, iwteOutputReady, startIWTETask, winePath)
from .strat_importer import finalizeStratImport


def cleanupStratExtract(job):
    """Retain scratch storage until IWTE closes; never touch Blender off-thread."""
    temporary = job.pop('temporary', None)
    if temporary is None:
        return
    process = job['process']

    def cleanup():
        process.wait()
        for attempt in range(20):
            try:
                temporary.cleanup()
                return
            except OSError:
                time.sleep(0.25)

    # Even after exit Windows may briefly hold file handles open.
    if process.poll() is not None:
        try:
            temporary.cleanup()
            return
        except OSError:
            pass
    threading.Thread(target=cleanup, name='Strat scratch cleanup', daemon=True).start()


def waitStratExtract(job, timeout=IWTE_TASK_TIMEOUT):
    """Bound a headless conversion; interactive imports use the modal watcher."""
    try:
        job['process'].wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        abortIWTEJob(job)
        job.setdefault('notes', []).append(('ERROR', 'IWTE strat extraction timed out after %gs' % timeout))
        return False
    deadline = time.monotonic() + IWTE_OUTPUT_TIMEOUT
    while not iwteOutputReady(job):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)
    return True


def startStratExtract(cas_path, iwte_folder):
    executable = findIWTEExe(iwte_folder)
    if not executable:
        raise ValueError("Set Paths > IWTE to a folder containing the IWTE executable")
    temporary = tempfile.TemporaryDirectory(prefix='med2_strat_import_')
    folder = Path(temporary.name)
    output = folder / 'model.glb'
    task = folder / 'cas_to_extract_task.txt'
    fields = [
        ('task_id', 'cas_to_extract'),
        ('cas_mesh_file_full_path_in', '"%s"' % winePath(str(cas_path))),
        ('directory_out', '"%s"' % winePath(str(folder) + os.sep)),
        ('extract_file_name_out', '"model.glb"'),
        ('cas_animation_file_format', 'm2'),
        ('extract_file_type', 'glb'),
        ('create_text_file', 'no'),
    ]
    try:
        task.write_text(''.join('<%s> %s\n' % field for field in fields), encoding='utf-8')
        # IWTE's command-line task parser requires forward slashes on Windows.
        job = startIWTETask(executable, iwte_folder, task.as_posix(), str(output))
    except Exception:
        temporary.cleanup()
        raise
    job['temporary'] = temporary
    return job


def importStratExtract(context, glb_path, cas_path, metadata, texture_path):
    """Import one completed extract; roll back only data created by this import."""
    kinds = ('objects', 'meshes', 'armatures', 'materials', 'images', 'collections', 'actions')
    before = {kind: set(getattr(bpy.data, kind)) for kind in kinds}
    selected = list(context.selected_objects)
    active = context.view_layer.objects.active
    settings = getattr(context.scene, 'med2_toolkit_strat', None)
    previous_settings = {name: getattr(settings, name) for name in
                         ('model_name', 'texture_name', 'skeleton_scale', 'last_build_dir',
                          'last_texture', 'last_exported_glb', 'last_cas')} if settings else {}
    try:
        result = bpy.ops.import_scene.gltf(filepath=str(glb_path))
        if result != {'FINISHED'}:
            raise ValueError("Blender could not import the IWTE extract")
        objects = set(bpy.data.objects) - before['objects']
        rigs = [obj for obj in objects if obj.type == 'ARMATURE']
        # glTF creates mesh objects for bone display shapes. They are rig UI,
        # not CAS geometry, and must stay outside the imported model hierarchy.
        shapes = {bone.custom_shape for armature in rigs for bone in armature.pose.bones
                  if bone.custom_shape is not None}
        meshes = [obj for obj in objects if obj.type == 'MESH' and obj not in shapes]
        if not meshes or len(rigs) > 1:
            raise ValueError("IWTE extract must contain meshes and at most one armature")
        if rigs:
            rig = rigs[0]
        else:
            data = bpy.data.armatures.new(Path(cas_path).stem)
            rig = bpy.data.objects.new(Path(cas_path).stem, data)
            context.scene.collection.objects.link(rig)
        for obj in meshes:
            if obj not in rig.children_recursive:
                world = obj.matrix_world.copy()
                obj.parent = rig
                obj.matrix_world = world
        report = finalizeStratImport(context, rig, metadata, cas_path, texture_path, 'IWTE')
        return report, rig
    except Exception as error:
        if context.object is not None and context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for kind in kinds:
            collection = getattr(bpy.data, kind)
            for item in set(collection) - before[kind]:
                if kind in ('objects', 'collections'):
                    collection.remove(item, do_unlink=True)
                elif item.users == 0:
                    collection.remove(item)
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in selected:
            if obj.name in context.view_layer.objects:
                obj.select_set(True)
        context.view_layer.objects.active = active
        for name, value in previous_settings.items():
            setattr(settings, name, value)
        return [('ERROR', 'Strat import failed: %s' % error)], None
