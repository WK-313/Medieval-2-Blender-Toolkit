import os
import shutil
import struct
import subprocess
import bpy
from pathlib import Path

addon_folder = Path(__file__).parent.parent

def clean_path(path):
    return os.path.normpath(path.strip('"').strip("'"))

def get_texconv_path():
    texconv = addon_folder/'bin'/'texconv.exe'
    return texconv if texconv.exists() else None

def open_folder(path):
    if os.path.exists(path):
        os.startfile(path)

def collect_textures(objects):
    textures = set()
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for mat in obj.data.materials:
            if not mat or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image and node.image.filepath:
                    textures.add(bpy.path.abspath(node.image.filepath))
    return textures

def writeTexture(savefiletexture, ddsdata):
    if ddsdata[0:4] != b'DDS ':
        return False

    height = struct.unpack("<I", ddsdata[12:16])[0]
    width = struct.unpack("<I", ddsdata[16:20])[0]

    if (width & (width - 1)) != 0 or (height & (height - 1)) != 0:
        return False

    fourcc = ddsdata[84:88].decode('ascii', errors='ignore')

    if fourcc in ('DXT5', 'DXT3'):
        dxt = 64
    elif fourcc == 'DXT1':
        dxt = 16
    else:
        return False

    header_bytes = bytes([
        1,0,0,0,
        48,0,0,0,
        0,0,0,0,
        100,100,115,0,
        208,239,18,0,
        152,98,18,3,
        76,232,18,0,
        dxt,2,
        0,0,0,0,0,0,
        101,86,58,124,
        3,0,0,0,
        0,2,0,0
    ])

    with open(savefiletexture, "wb") as f:
        f.write(header_bytes)
        f.write(ddsdata)
    return True

def exportArmatureGLB(context):
    texconv = get_texconv_path()
    if not texconv:
        return "texconv.exe not found in the addon's bin folder"

    arm = context.object
    if not arm or arm.type != 'ARMATURE':
        return "Select an Armature"

    export_data = context.scene.med2_toolkit_unit_export
    base_out = clean_path(context.scene.med2_toolkit_reader.directory_unit_export)
    export_name = export_data.export_glb_name

    if not base_out or not export_name:
        return "Invalid output folder or name"

    out_dir = os.path.join(base_out, export_name)
    os.makedirs(out_dir, exist_ok=True)

    export_data.last_export_dir = out_dir
    glb_path = os.path.join(out_dir, export_name + ".glb")
    export_data.last_exported_glb = glb_path

    meshes = [
        obj for obj in arm.children_recursive
        if obj.type == 'MESH'
        and (not export_data.export_visible_only or obj.visible_get())
    ]

    if not meshes:
        return "No mesh objects found under the armature (check the Visible Only toggle)"

    export_objects = [arm] + meshes

    # Hidden objects silently refuse select_set(), and use_selection with an
    # empty selection writes an empty GLB. Unhide for the export, restore after.
    visibility_backup = [(obj, obj.hide_get()) for obj in export_objects]
    # Stacked or dead Armature modifiers (duplicates, object=None, or aimed at
    # another rig) get baked into the mesh by export_apply and wreck the
    # result. Keep only the first one driven by the exported armature.
    modifier_backup = []
    try:
        for obj, was_hidden in visibility_backup:
            if was_hidden:
                obj.hide_set(False)

        for obj in meshes:
            skin_found = False
            for modifier in obj.modifiers:
                if modifier.type != 'ARMATURE':
                    continue
                if modifier.object is arm and not skin_found:
                    skin_found = True
                    continue
                modifier_backup.append((modifier, modifier.show_viewport, modifier.show_render))
                modifier.show_viewport = False
                modifier.show_render = False

        bpy.ops.object.select_all(action='DESELECT')
        for obj in export_objects:
            obj.select_set(True)
        context.view_layer.objects.active = arm
        unselectable = [obj.name for obj in export_objects if not obj.select_get()]
        if unselectable:
            return "Cannot select for export (excluded collection?): %s" % ", ".join(unselectable)

        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format='GLB',
            use_selection=True,
            export_apply=True,
            export_animations=export_data.export_animations
        )
    finally:
        for modifier, show_viewport, show_render in modifier_backup:
            modifier.show_viewport = show_viewport
            modifier.show_render = show_render
        for obj, was_hidden in visibility_backup:
            if was_hidden:
                obj.hide_set(True)

    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)

    for tex in collect_textures(meshes):
        if not os.path.exists(tex):
            continue

        dst = os.path.join(tex_dir, os.path.basename(tex))
        shutil.copy2(tex, dst)

        name, ext = os.path.splitext(dst)
        ext = ext.lower()

        if ext in [".png", ".jpg", ".jpeg", ".tga"]:
            subprocess.run(
                [
                    str(texconv),
                    "-f", "DXT5",
                    "-m", "1",
                    "-nologo",
                    "-y",
                    "-o", tex_dir,
                    dst
                ],
                check=True
            )
            dds = name + ".dds"
        elif ext == ".dds":
            dds = dst
        else:
            continue

        if os.path.exists(dds):
            with open(dds, "rb") as f:
                writeTexture(name + ".texture", f.read())

    return "Finished"

def exportToMeshIWTE(context):
    reader = context.scene.med2_toolkit_reader
    glb_path = clean_path(context.scene.med2_toolkit_unit_export.last_exported_glb)
    iwte_dir = clean_path(reader.directory_iwte)
    template = clean_path(reader.directory_iwte_task_template)

    if not os.path.isfile(glb_path):
        return "No exported GLB found"

    if not os.path.isdir(iwte_dir):
        return "Invalid IWTE folder"

    if not os.path.isfile(template):
        return "Invalid IWTE task template"

    iwte_exe = next(
        (os.path.join(iwte_dir, f) for f in os.listdir(iwte_dir)
         if f.lower().startswith("iwte") and f.lower().endswith(".exe")),
        None
    )

    if not iwte_exe:
        return "IWTE executable not found"

    unit_folder = os.path.dirname(glb_path)
    unit_name = os.path.splitext(os.path.basename(glb_path))[0]

    with open(template, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith("<extract_file_full_path_in>"):
            new_lines.append(f'<extract_file_full_path_in>    "{glb_path}"\n')
        elif line.strip().startswith("<directory_out>"):
            new_lines.append(f'<directory_out>                "{unit_folder}"\n')
        elif line.strip().startswith("<mesh_file_name_out>"):
            new_lines.append(f'<mesh_file_name_out>           "{unit_name}.mesh"\n')
        else:
            new_lines.append(line)

    task_path = os.path.join(
        unit_folder,
        f"iwte_extract_to_mesh_{unit_name}_task.txt"
    )

    with open(task_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    subprocess.Popen(
        [iwte_exe, "--uh", "--st", task_path],
        cwd=iwte_dir,
        creationflags=0x08000000
    )

    return "Finished"
