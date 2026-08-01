import os
import shutil
import struct
import subprocess
import time
import bpy
from pathlib import Path
from .export_checks import deselectAll, materialImages, activeExportArmature, exportSettings
from ..directories import loadStoredValue
from .bmdb_writer import buildEntry, parseRelativeUnitPath, bmdbEntryNames

addon_folder = Path(__file__).parent.parent

def clean_path(path):
    return os.path.normpath(path.strip('"').strip("'"))

def get_texconv_path():
    texconv = addon_folder/'bin'/'texconv.exe'
    return texconv if texconv.exists() else None

def open_folder(path):
    if os.path.exists(path):
        os.startfile(path)

def selectedModFolder(context):
    reader = context.scene.med2_toolkit_reader
    if reader.mods_filtered != "custom":
        return reader.mods_filtered
    return reader.directory_mod_data

def defaultTaskTemplate(reader):
    """Template used for rigs without their own: the last used one if it still
    exists on disk, else the global one from the Paths panel."""
    stored = loadStoredValue('last_iwte_task_template')
    if stored and os.path.isfile(clean_path(stored)):
        return stored
    return reader.directory_iwte_task_template

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

DXT_FOURCCS = ('DXT1', 'DXT3', 'DXT5')

def ddsFourcc(path):
    """FourCC of a .dds file on disk. Uncompressed DDS files leave the field
    zeroed, so '' means "not DXT compressed" as much as "not a DDS"."""
    try:
        with open(path, "rb") as dds_input:
            header = dds_input.read(88)
    except OSError:
        return ""
    if len(header) < 88 or header[0:4] != b'DDS ':
        return ""
    return header[84:88].decode('ascii', errors='ignore').strip('\x00')

def ddsMipCount(path):
    """Number of mip levels in a .dds on disk. 1 means the base image only.
    dwMipMapCount is only meaningful when DDSD_MIPMAPCOUNT (0x20000) is set -
    plenty of writers leave a stale count behind with the flag cleared."""
    try:
        with open(path, "rb") as dds_input:
            header = dds_input.read(32)
    except OSError:
        return 0
    if len(header) < 32 or header[0:4] != b'DDS ':
        return 0
    flags, = struct.unpack("<I", header[8:12])
    if not flags & 0x20000:
        return 1
    return max(1, struct.unpack("<I", header[28:32])[0])

def runTexconv(texconv, source, tex_dir, out_base):
    """Convert an image to DXT5 with a full mipmap chain at tex_dir/out_base.dds
    and return that path, or None when texconv fails. The output is staged in a
    temp folder first so this also works when source IS the destination (a .dds
    being recompressed in place), which texconv itself refuses to do."""
    staging = os.path.join(tex_dir, "_texconv")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    try:
        subprocess.run(
            [
                str(texconv),
                "-f", "DXT5",
                "-m", "0",
                "-nologo",
                "-y",
                "-o", staging,
                source
            ],
            check=True
        )
        produced = os.path.join(staging, os.path.splitext(os.path.basename(source))[0] + ".dds")
        if not os.path.exists(produced):
            return None
        final = os.path.join(tex_dir, out_base + ".dds")
        os.replace(produced, final)
        return final
    except (subprocess.CalledProcessError, OSError):
        return None
    finally:
        shutil.rmtree(staging, ignore_errors=True)

def writeTexture(savefiletexture, ddsdata):
    """Wrap DDS data in the game's .texture header. Returns None on success, or
    a reason string when the data can't be used - callers must surface it, a
    silently skipped texture leaves the unit untextured in game."""
    if ddsdata[0:4] != b'DDS ':
        return "not a DDS file"

    height = struct.unpack("<I", ddsdata[12:16])[0]
    width = struct.unpack("<I", ddsdata[16:20])[0]

    if (width & (width - 1)) != 0 or (height & (height - 1)) != 0:
        return "%dx%d is not a power of two" % (width, height)

    fourcc = ddsdata[84:88].decode('ascii', errors='ignore')

    if fourcc in ('DXT5', 'DXT3'):
        dxt = 64
    elif fourcc == 'DXT1':
        dxt = 16
    else:
        return "%s DDS, the game only reads DXT1/DXT3/DXT5" % (fourcc.strip('\x00') or "uncompressed")

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
    return None

def texturePlan(context):
    """Resolve the main/attach materials into (image, out_name) pairs and the
    effective texture names used for conversion and the BMDB entry."""
    export_data = exportSettings(context)
    main_mat = bpy.data.materials.get(export_data.material_main)
    attach_mat = bpy.data.materials.get(export_data.material_attach) if export_data.material_attach != 'none' else None
    main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
    attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

    def out_name(image, requested):
        if requested:
            return requested
        if image:
            return os.path.splitext(os.path.basename(image.filepath) or image.name)[0]
        return ""

    plan = {
        'main': (main_diff, out_name(main_diff, export_data.out_main)),
        'main_norm': (main_norm, out_name(main_norm, export_data.out_main_norm)),
        'attach': (attach_diff, out_name(attach_diff, export_data.out_attach)),
        'attach_norm': (attach_norm, out_name(attach_norm, export_data.out_attach_norm)),
    }
    return plan

def generateBlankNormal(texconv, tex_dir, out_name, size):
    blank = addon_folder/'normals'/('%d.dds' % size)
    if not blank.exists():
        return "No blank normal available for %dx%d (only 512/1024/2048)" % (size, size)
    dds_path = os.path.join(tex_dir, out_name + ".dds")
    shutil.copy2(blank, dds_path)
    # the bundled blanks ship mipped, but a hand-replaced one may not be
    if ddsFourcc(dds_path) not in DXT_FOURCCS or ddsMipCount(dds_path) <= 1:
        if runTexconv(texconv, dds_path, tex_dir, out_name) is None:
            return "Blank normal %s not converted: texconv could not convert it" % out_name
    with open(dds_path, "rb") as f:
        error = writeTexture(os.path.join(tex_dir, out_name + ".texture"), f.read())
    if error:
        return "Blank normal %s not converted: %s" % (out_name, error)
    return None

def writeBMDBEntry(context, out_dir, plan):
    armature = activeExportArmature(context)
    export_data = armature.med2_toolkit_unit_export
    factions = [item.faction_id for item in armature.med2_toolkit_export_factions if item.enabled]
    if not factions:
        return "BMDB entry skipped: no factions selected for ownership"
    if not export_data.bmdb_unit_path:
        return "BMDB entry skipped: no unit path set"
    relative = parseRelativeUnitPath(export_data.bmdb_unit_path)
    main_name = plan['main'][1]
    main_norm_name = plan['main_norm'][1] or (export_data.out_main_norm if export_data.gen_blank_normals else "")
    attach_name = plan['attach'][1] or main_name
    attach_norm_name = plan['attach_norm'][1] or (export_data.out_attach_norm if export_data.gen_blank_normals else "") or main_norm_name
    entry_name = export_data.bmdb_entry_name or export_data.export_glb_name
    entry = buildEntry(
        model_name=entry_name,
        relative_path=relative,
        out_main=main_name,
        out_main_norm=main_norm_name,
        sprite=export_data.bmdb_sprite,
        out_attach=attach_name,
        out_attach_norm=attach_norm_name,
        footer=export_data.bmdb_footer,
        factions=factions,
        mesh_name=export_data.export_glb_name,
    )
    entry_path = os.path.join(out_dir, export_data.export_glb_name + "_bmdb.txt")
    with open(entry_path, "w", encoding="utf-8") as f:
        f.write(entry + "\n")
    existing = bmdbEntryNames(bpy.path.abspath(selectedModFolder(context)))
    if existing is not None and entry_name.lower() in existing:
        return "BMDB entry '%s' already exists in the mod's battle_models.modeldb - replace the old entry instead of appending" % entry_name
    return None

def exportArmatureGLB(context):
    texconv = get_texconv_path()
    if not texconv:
        return "texconv.exe not found in the addon's bin folder"

    arm = activeExportArmature(context)
    if not arm:
        return "Select an Armature"

    export_data = arm.med2_toolkit_unit_export
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
    plan = texturePlan(context)
    rename_map = {}
    for image, name in plan.values():
        if image is not None and name:
            rename_map[bpy.path.abspath(image.filepath)] = name

    visibility_backup = [(obj, obj.hide_get()) for obj in export_objects]
    # Stacked or dead Armature modifiers (duplicates, object=None, or aimed at
    # another rig) get baked into the mesh by export_apply and wreck the
    # result. Keep only the first one driven by the exported armature.
    modifier_backup = []
    # The GLB references textures by image name, so temporarily rename the
    # images to their output names for the duration of the export.
    image_name_backup = []
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

        for image, name in plan.values():
            if image is not None and name and image.name != name:
                image_name_backup.append((image, image.name))
                image.name = name

        deselectAll(context)
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
        for image, original_name in image_name_backup:
            image.name = original_name
        for modifier, show_viewport, show_render in modifier_backup:
            modifier.show_viewport = show_viewport
            modifier.show_render = show_render
        for obj, was_hidden in visibility_backup:
            if was_hidden:
                obj.hide_set(True)

    tex_dir = os.path.join(out_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)

    texture_errors = []
    for tex in collect_textures(meshes):
        if not os.path.exists(tex):
            continue

        ext = os.path.splitext(tex)[1].lower()
        out_base = rename_map.get(bpy.path.abspath(tex)) or os.path.splitext(os.path.basename(tex))[0]
        dst = os.path.join(tex_dir, out_base + ext)
        shutil.copy2(tex, dst)

        name = os.path.join(tex_dir, out_base)

        if ext in [".png", ".jpg", ".jpeg", ".tga"]:
            dds = runTexconv(texconv, dst, tex_dir, out_base)
        elif ext == ".dds":
            dds = dst
            # a .dds is not automatically game-ready: uncompressed, BC7 and
            # DX10-header files all load fine in Blender but the game only
            # reads DXT1/DXT3/DXT5, so recompress those the same way a png.
            # A flat DXT file is recompressed too - the game picks a mip level
            # by distance, so one without a chain shimmers and stays at full
            # resolution at every range. Everything texconv writes is mipped.
            if ddsFourcc(dst) not in DXT_FOURCCS or ddsMipCount(dst) <= 1:
                dds = runTexconv(texconv, dst, tex_dir, out_base)
        else:
            continue

        if dds is None or not os.path.exists(dds):
            texture_errors.append("%s (texconv could not convert it)" % os.path.basename(tex))
            continue
        with open(dds, "rb") as f:
            error = writeTexture(name + ".texture", f.read())
        if error:
            texture_errors.append("%s (%s)" % (os.path.basename(tex), error))

    notes = []
    if texture_errors:
        notes.append("no .texture written for %s" % "; ".join(texture_errors))
    if export_data.gen_blank_normals:
        for slot, norm_out_prop in (('main', 'out_main_norm'), ('attach', 'out_attach_norm')):
            diffuse, _ = plan[slot]
            norm_image, _ = plan[slot + '_norm']
            requested = getattr(export_data, norm_out_prop)
            if diffuse is None or norm_image is not None or not requested:
                continue
            size = diffuse.size[0]
            error = generateBlankNormal(texconv, tex_dir, requested, size)
            if error:
                notes.append(error)

    if export_data.generate_bmdb:
        error = writeBMDBEntry(context, out_dir, plan)
        if error:
            notes.append(error)

    if notes:
        return "Finished, but: " + "; ".join(notes)
    return "Finished"

def exportToMeshIWTE(context):
    """Write the IWTE task file and launch the conversion. Returns an error
    string on failure, or a job dict for the caller to monitor until IWTE exits."""
    reader = context.scene.med2_toolkit_reader
    export_data = exportSettings(context)
    if export_data is None:
        return "Select an Armature"
    glb_path = clean_path(export_data.last_exported_glb)
    iwte_dir = clean_path(reader.directory_iwte)
    if not export_data.iwte_task_template:
        # adopt the last used / Paths template so the rig remembers it
        export_data.iwte_task_template = defaultTaskTemplate(reader)
    template = clean_path(export_data.iwte_task_template)

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

    mesh_path = os.path.join(unit_folder, unit_name + ".mesh")
    try:
        previous_mtime = os.path.getmtime(mesh_path)
    except OSError:
        previous_mtime = None

    process = subprocess.Popen(
        [iwte_exe, "--uh", "--st", task_path],
        cwd=iwte_dir,
        creationflags=0x08000000
    )

    return {
        'process': process,
        'mesh_path': mesh_path,
        'mesh_name': unit_name + ".mesh",
        'previous_mtime': previous_mtime,
        'start': time.time(),
    }
