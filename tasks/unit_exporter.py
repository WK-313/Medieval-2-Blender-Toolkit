import os
import shutil
import struct
import subprocess
import sys
import bpy
from pathlib import Path
from .export_checks import deselectAll, materialImages, activeExportArmature, exportSettings
from ..directories import loadStoredValue
from .bmdb_writer import buildEntry, parseRelativeUnitPath, bmdbEntryNames
from .iwte_run import NO_WINE, canRunWindowsExe, findIWTEExe, startIWTETask, usesWine, winePath, wineWrap
from .iwte_tasks import applySkeletonTask

addon_folder = Path(__file__).parent.parent

def clean_path(path):
    return os.path.normpath(path.strip('"').strip("'"))

def get_texconv_path():
    """The DDS converter. The bundled binary is the Windows build, which off
    Windows runs through Wine - but a native texconv on PATH is used in
    preference, since it needs no Wine at all."""
    if os.name != 'nt':
        native = shutil.which('texconv')
        if native:
            return Path(native)
    texconv = addon_folder/'bin'/'texconv.exe'
    return texconv if texconv.exists() else None

def open_folder(path):
    """Show a folder in the system's own file manager."""
    if not os.path.exists(path):
        return
    if os.name == 'nt':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])

def reveal_file(path):
    """Open the file manager with one file highlighted. Only Windows and macOS
    have a documented way to ask for that, so elsewhere the file's folder is
    opened instead - which is what the caller wanted to show anyway."""
    path = str(Path(path))
    if not os.path.exists(path):
        return
    if os.name == 'nt':
        # one argument, "/select,C:\\path\\file" - explorer does not accept the
        # path as a separate argv entry
        subprocess.run(['explorer', '/select,' + path])
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', path])
    else:
        subprocess.Popen(['xdg-open', os.path.dirname(path)])

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

def runTexconv(texconv, source, tex_dir, out_base, opaque_alpha=False):
    """Convert an image to DXT5 with a full mipmap chain at tex_dir/out_base.dds
    and return that path, or None when texconv fails. The output is staged in a
    temp folder first so this also works when source IS the destination (a .dds
    being recompressed in place), which texconv itself refuses to do.

    opaque_alpha writes alpha 1 everywhere and keeps the colour - the fix for a
    diffuse whose alpha channel is not meant as a cutout."""
    staging = os.path.join(tex_dir, "_texconv")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    command = wineWrap([
        str(texconv),
        "-f", "DXT5",
        "-m", "0",
        "-nologo",
        "-y",
    ])
    if not command:
        return None
    if opaque_alpha:
        command += ["-swizzle", "rgb1"]
    # texconv is a Windows exe too, so off Windows it reads these the same way
    # IWTE reads a task file: as paths relative to its own folder unless they
    # carry a drive letter. A native texconv on PATH takes them as they are.
    if usesWine(texconv):
        command += ["-o", winePath(staging), winePath(source)]
    else:
        command += ["-o", staging, source]
    try:
        subprocess.run(command, check=True)
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

# a DXT5 alpha block whose 16 three-bit indices all select palette entry 6,
# the fixed 0 of the a0 <= a1 mode - the only way a block with two non-zero
# endpoints can still be fully transparent
ALL_SIX_INDICES = sum(6 << (3 * i) for i in range(16)).to_bytes(6, "little")

def alphaBlockIsTransparent(block, dxt3):
    """True when every texel of one 8-byte DXT3/DXT5 alpha block is alpha 0.

    DXT5 stores two endpoints and 16 three-bit indices into a palette built
    from them, and texconv writes a flat transparent block as endpoints
    (255, 0) with every index on the second one - so the endpoints alone are
    not enough to tell, the indices have to be read."""
    if dxt3:
        return block == b"\x00" * 8
    a0, a1 = block[0], block[1]
    if a0 > a1:
        if a1 > 0:
            return False
        palette = [a0, a1] + [((7 - i) * a0 + i * a1 + 3) // 7 for i in range(1, 7)]
    else:
        if a0 > 0:
            return block[2:8] == ALL_SIX_INDICES
        palette = [a0, a1] + [((5 - i) * a0 + i * a1 + 2) // 5 for i in range(1, 5)] + [0, 255]
    indices = int.from_bytes(block[2:8], "little")
    return all(palette[(indices >> (3 * i)) & 7] == 0 for i in range(16))

def ddsHasTransparentAreas(path):
    """True when the top mip of a DXT3/DXT5 .dds holds fully transparent blocks.
    The game draws nothing where the diffuse alpha is zero, so a texture painted
    with an empty or half-empty alpha channel comes out see-through in game. A
    soft alpha gradient never trips it, and DXT1 has no real alpha channel."""
    try:
        with open(path, "rb") as dds_input:
            header = dds_input.read(128)
            if len(header) < 128 or header[0:4] != b'DDS ':
                return False
            fourcc = header[84:88].decode('ascii', errors='ignore').strip('\x00')
            if fourcc not in ('DXT3', 'DXT5'):
                return False
            height, = struct.unpack("<I", header[12:16])
            width, = struct.unpack("<I", header[16:20])
            blocks = max(1, (width + 3) // 4) * max(1, (height + 3) // 4)
            top_mip = dds_input.read(blocks * 16)
    except OSError:
        return False
    dxt3 = fourcc == 'DXT3'
    return any(alphaBlockIsTransparent(top_mip[i:i + 8], dxt3)
               for i in range(0, len(top_mip) - 15, 16))

SUPPORTED_TEXTURE_EXTS = ('.png', '.jpg', '.jpeg', '.tga', '.dds')

def textureFromFile(texconv, source, tex_dir, out_base, diffuse=False, opaque_alpha=False):
    """Copy an image into tex_dir under out_base, convert it to mipped DXT5 and
    wrap that .dds as out_base.texture.

    `diffuse` marks a main/attachment texture, whose alpha the game reads as
    transparency; `opaque_alpha` throws that alpha away. Both are ignored for
    anything else - a normal map's alpha is its specular map, not a cutout.

    Returns (error, warning) - error is the reason no .texture was written,
    warning is something worth saying about one that was. Both None on a clean
    conversion."""
    ext = os.path.splitext(source)[1].lower()
    if ext not in SUPPORTED_TEXTURE_EXTS:
        return "%s is not a format the export can convert" % (ext or "no extension"), None

    dst = os.path.join(tex_dir, out_base + ext)
    if not (os.path.exists(dst) and os.path.samefile(source, dst)):
        shutil.copy2(source, dst)

    force_opaque = diffuse and opaque_alpha
    if force_opaque:
        # even a game-ready .dds is reconverted here: passing it through would
        # keep exactly the alpha channel this is meant to drop
        dds = runTexconv(texconv, dst, tex_dir, out_base, opaque_alpha=True)
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
        dds = runTexconv(texconv, dst, tex_dir, out_base)

    if dds is None or not os.path.exists(dds):
        return "texconv could not convert it", None

    with open(dds, "rb") as f:
        error = writeTexture(os.path.join(tex_dir, out_base + ".texture"), f.read())
    if error:
        return error, None

    # every branch above either ran texconv (-m 0, a full chain) or passed
    # through a .dds that already had one, so a flat result means the conversion
    # did not do what it was asked. Say so rather than shipping a texture that
    # shimmers and stays full-resolution at every range.
    if ddsMipCount(dds) <= 1:
        return None, "%s.texture was written without mipmaps" % out_base
    if diffuse and not force_opaque and ddsHasTransparentAreas(dds):
        return None, ("%s.texture has fully transparent areas in its alpha channel - the game "
                      "draws nothing there, so those parts of the unit are see-through. Tick "
                      "Ignore Diffuse Alpha if that alpha is not a deliberate cutout" % out_base)
    return None, None

def normalFromFile(prop_value, requested):
    """A normal map browsed from disk for a material that carries none.
    Returns (absolute path, output name), or (None, "") when nothing usable is
    set - a path that no longer exists counts as nothing, same as a blank one."""
    if not prop_value:
        return None, ""
    path = clean_path(bpy.path.abspath(prop_value))
    if not os.path.isfile(path):
        return None, ""
    return path, (requested or os.path.splitext(os.path.basename(path))[0])

def normalFileName(prop_value):
    """What to show for a browsed normal map: its file name, or "" when nothing
    is set or the path no longer points at a file."""
    return os.path.basename(normalFromFile(prop_value, "")[0] or "")

# the slots of a texture plan holding a Blender image; the *_norm_file ones hold
# a path on disk instead and must not be walked with them
IMAGE_SLOTS = ('main', 'main_norm', 'attach', 'attach_norm')

def texturePlan(context):
    """Resolve the main/attach materials into (image, out_name) pairs and the
    effective texture names used for conversion and the BMDB entry."""
    export_data = exportSettings(context)
    main_mat = bpy.data.materials.get(export_data.material_main) if export_data.material_main != 'none' else None
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
        # a normal map the user pointed at on disk, for a material that carries
        # none of its own. The material's own normal map always wins, and with
        # no material picked for the slot there is nothing to be the normal of.
        'main_norm_file': normalFromFile(export_data.norm_main_file, export_data.out_main_norm)
            if (main_mat and main_norm is None) else (None, ""),
        'attach_norm_file': normalFromFile(export_data.norm_attach_file, export_data.out_attach_norm)
            if (attach_mat and attach_norm is None) else (None, ""),
    }
    return plan

def generateBlankNormal(texconv, tex_dir, out_name, size):
    blank = addon_folder/'normals'/('%d.dds' % size)
    if not blank.exists():
        return "No blank normal available for %dx%d (only 512/1024/2048)" % (size, size)
    # the bundled blanks ship mipped, but a hand-replaced one may not be -
    # textureFromFile rebuilds the chain either way
    error, warning = textureFromFile(texconv, str(blank), tex_dir, out_name)
    if error:
        return "Blank normal %s not converted: %s" % (out_name, error)
    if warning:
        return "Blank normal %s: %s" % (out_name, warning)
    return None

def bmdbEntryText(context, plan=None):
    """The battle_models.modeldb entry for the active rig's export settings.

    Returns (entry_text, entry_name, relative_path, error) - the same text the
    export writes to <name>_bmdb.txt and the installer writes into the mod, so
    the two can never drift apart."""
    armature = activeExportArmature(context)
    if armature is None:
        return None, "", "", "Select an Armature"
    export_data = armature.med2_toolkit_unit_export
    factions = [item.faction_id for item in armature.med2_toolkit_export_factions if item.enabled]
    if not factions:
        return None, "", "", "no factions selected for ownership"
    if not export_data.bmdb_unit_path:
        return None, "", "", "no unit path set"
    if plan is None:
        plan = texturePlan(context)
    relative = parseRelativeUnitPath(export_data.bmdb_unit_path)
    main_name = plan['main'][1]
    main_norm_name = (plan['main_norm'][1] or plan['main_norm_file'][1]
                      or (export_data.out_main_norm if export_data.gen_blank_normals else ""))
    attach_name = plan['attach'][1] or main_name
    attach_norm_name = (plan['attach_norm'][1] or plan['attach_norm_file'][1]
                        or (export_data.out_attach_norm if export_data.gen_blank_normals else "")
                        or main_norm_name)
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
    return entry, entry_name, relative, None

def writeBMDBEntry(context, out_dir, plan):
    export_data = activeExportArmature(context).med2_toolkit_unit_export
    entry, entry_name, _relative, error = bmdbEntryText(context, plan)
    if error:
        return "BMDB entry skipped: %s" % error
    entry_path = os.path.join(out_dir, export_data.export_glb_name + "_bmdb.txt")
    with open(entry_path, "w", encoding="utf-8") as f:
        f.write(entry + "\n")
    existing = bmdbEntryNames(bpy.path.abspath(selectedModFolder(context)))
    if existing is not None and entry_name.lower() in existing:
        return "BMDB entry '%s' already exists in the mod's battle_models.modeldb - use Install to Mod to replace or rename it" % entry_name
    return None

def exportArmatureGLB(context):
    texconv = get_texconv_path()
    if not texconv:
        return "texconv.exe not found in the addon's bin folder"
    if not wineWrap([str(texconv)]):
        return NO_WINE % "texconv"

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
    for image, name in (plan[slot] for slot in IMAGE_SLOTS):
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

        for image, name in (plan[slot] for slot in IMAGE_SLOTS):
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
    texture_warnings = []

    # the main and attachment textures are the ones the game alpha-tests
    diffuse_names = {plan['main'][1], plan['attach'][1]} - {""}

    def convert(source, out_base, label, diffuse=False):
        error, warning = textureFromFile(texconv, source, tex_dir, out_base,
                                         diffuse=diffuse,
                                         opaque_alpha=export_data.ignore_diffuse_alpha)
        if error:
            texture_errors.append("%s (%s)" % (label, error))
        if warning:
            texture_warnings.append(warning)

    for tex in collect_textures(meshes):
        if not os.path.exists(tex):
            continue
        if os.path.splitext(tex)[1].lower() not in SUPPORTED_TEXTURE_EXTS:
            continue
        out_base = rename_map.get(bpy.path.abspath(tex)) or os.path.splitext(os.path.basename(tex))[0]
        convert(tex, out_base, os.path.basename(tex), diffuse=out_base in diffuse_names)

    # normal maps pointed at a file on disk instead of being wired into the
    # material go through the same conversion, so a normal map painted in an
    # image editor becomes a .texture here rather than in a separate IWTE run
    for slot in ('main_norm_file', 'attach_norm_file'):
        source, out_base = plan[slot]
        if source and out_base:
            convert(source, out_base, os.path.basename(source))

    notes = []
    if texture_errors:
        notes.append("no .texture written for %s" % "; ".join(texture_errors))
    notes.extend(texture_warnings)
    if export_data.gen_blank_normals:
        for slot, norm_out_prop in (('main', 'out_main_norm'), ('attach', 'out_attach_norm')):
            diffuse, _ = plan[slot]
            norm_image, _ = plan[slot + '_norm']
            norm_file, _ = plan[slot + '_norm_file']
            requested = getattr(export_data, norm_out_prop)
            # a browsed normal map has already been converted for this slot
            if diffuse is None or norm_image is not None or norm_file or not requested:
                continue
            size = diffuse.size[0]
            error = generateBlankNormal(texconv, tex_dir, requested, size)
            if error:
                notes.append(error)

    # In install mode the entry is written into the mod's modeldb from the
    # Install to Mod panel instead, after IWTE has produced the .mesh. 'both'
    # writes the txt here as well as installing it later
    if export_data.generate_bmdb and export_data.bmdb_mode in {'txt', 'both'}:
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
        # a rig on one of the QOL skeletons converts with that skeleton's
        # bundled sample; anything else adopts the last used / Paths template
        applySkeletonTask(activeExportArmature(context))
    if not export_data.iwte_task_template:
        export_data.iwte_task_template = defaultTaskTemplate(reader)
    template = clean_path(export_data.iwte_task_template)

    if not os.path.isfile(glb_path):
        return "No exported GLB found"

    if not os.path.isdir(iwte_dir):
        return "Invalid IWTE folder"

    if not os.path.isfile(template):
        return "Invalid IWTE task template"

    iwte_exe = findIWTEExe(iwte_dir)

    if not iwte_exe:
        return "IWTE executable not found"

    if not canRunWindowsExe():
        return NO_WINE % "IWTE"

    unit_folder = os.path.dirname(glb_path)
    unit_name = os.path.splitext(os.path.basename(glb_path))[0]

    with open(template, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        if line.strip().startswith("<extract_file_full_path_in>"):
            new_lines.append(f'<extract_file_full_path_in>    "{winePath(glb_path)}"\n')
        elif line.strip().startswith("<directory_out>"):
            new_lines.append(f'<directory_out>                "{winePath(unit_folder)}"\n')
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
    return startIWTETask(iwte_exe, iwte_dir, task_path, mesh_path)
