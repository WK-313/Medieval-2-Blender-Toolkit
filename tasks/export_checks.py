import re
import bpy
from .armature_tools import skeletonUsesLowercase

RECOMMENDED_SIZES = (512, 1024, 2048)

def deselectAll(context):
    # select_all(action='DESELECT') skips objects hidden with the collection
    # eye toggle, which keep their selection and sneak into use_selection
    # exports. Clear the flag directly on every object instead.
    for obj in context.view_layer.objects:
        try:
            obj.select_set(False)
        except RuntimeError:
            pass

def activeExportArmature(context):
    """The armature whose export settings apply: the active object if it's an
    armature, else the nearest armature up the parent chain."""
    obj = context.object
    while obj is not None:
        if obj.type == 'ARMATURE':
            return obj
        obj = obj.parent
    return None

def exportSettings(context):
    """The active armature's per-object export settings, or None."""
    armature = activeExportArmature(context)
    return armature.med2_toolkit_unit_export if armature else None

def exportMeshes(context, armature):
    export_data = armature.med2_toolkit_unit_export
    return [
        obj for obj in armature.children_recursive
        if obj.type == 'MESH'
        and (not export_data.export_visible_only or obj.visible_get())
    ]

def isPowerOfTwo(n):
    return n > 0 and (n & (n - 1)) == 0

def baseName(name):
    if "." in name and name.split(".")[-1].isdigit():
        return name.rsplit(".", 1)[0]
    return name

# The __opt marker flags a mesh as an optional part. It is applied by the QOL
# "Toggle __opt Suffix" tool and must survive every naming cleanup untouched:
# it sits AFTER the mesh name but BEFORE Blender's trailing .001 number, so a
# duplicate reads object__opt.001, never object.001__opt. The helpers below let
# the cleanup passes set it aside, work on the bare name, then restore it.
OPT_SUFFIX = "__opt"

def splitNumberSuffix(name):
    """Split a trailing '.001'-style Blender number off a name. Returns
    (base, number) where number is '.001' etc. or '' when there is none."""
    if "." in name and name.rsplit(".", 1)[1].isdigit():
        base, num = name.rsplit(".", 1)
        return base, "." + num
    return name, ""

def hasOptSuffix(name):
    """True if name carries the intentional __opt marker (before any .001)."""
    base, _ = splitNumberSuffix(name)
    return base.endswith(OPT_SUFFIX)

def addOptSuffix(name):
    """Insert __opt before the trailing number: object.001 -> object__opt.001."""
    base, num = splitNumberSuffix(name)
    if base.endswith(OPT_SUFFIX):
        return name
    return base + OPT_SUFFIX + num

def removeOptSuffix(name):
    """Strip a trailing __opt marker, keeping any number: object__opt.001 -> object.001."""
    base, num = splitNumberSuffix(name)
    if base.endswith(OPT_SUFFIX):
        return base[:-len(OPT_SUFFIX)] + num
    return name

def splitOptSuffix(name):
    """Peel __opt and any trailing number off a name for cleanup passes.
    Returns (base, opt, number) so it can be rebuilt as base + opt + number."""
    core, number = splitNumberSuffix(name)
    if core.endswith(OPT_SUFFIX):
        return core[:-len(OPT_SUFFIX)], OPT_SUFFIX, number
    return core, "", number

def formatExportName(base):
    """Convert a bare mesh name to the x__y export format. `base` must already
    have the __opt marker and any trailing .001 peeled off (splitOptSuffix).
    Returns (new_base, kind) with kind None when the name is already valid.

        name                            -> name__name
        name1_name2                     -> name1__name2
        namenumber / name_number /
        name__number                    -> name__name_number

    A number after the separator is never a second name, so those three all
    collapse to the same name__name_number shape."""
    if "__" in base:
        head, _, tail = base.partition("__")
        if head and tail.isdigit():
            return "%s__%s_%s" % (head, head, tail), 'numbered'
        return base, None
    if "_" in base:
        head, _, tail = base.partition("_")
        if head and tail.isdigit():
            return "%s__%s_%s" % (head, head, tail), 'numbered'
        return head + "__" + tail, 'underscored'
    match = re.fullmatch(r"(.*?[A-Za-z])(\d+)", base)
    if match:
        stem, number_part = match.groups()
        return "%s__%s_%s" % (stem, stem, number_part), 'numbered'
    if base:
        return "%s__%s" % (base, base), 'doubled'
    return base, None

def materialImages(material):
    """Return (diffuse_image, normal_image) for a material."""
    diffuse = None
    normal = None
    if not material or not material.use_nodes:
        return None, None
    for node in material.node_tree.nodes:
        if node.type != 'TEX_IMAGE' or not node.image:
            continue
        feeds_normal = False
        for link in material.node_tree.links:
            if link.from_node == node and (link.to_node.type == 'NORMAL_MAP' or link.to_socket.name == 'Normal'):
                feeds_normal = True
        if feeds_normal or 'norm' in node.image.name.lower():
            if normal is None:
                normal = node.image
        elif diffuse is None:
            diffuse = node.image
    return diffuse, normal

def uniqueMaterials(meshes):
    materials = []
    for obj in meshes:
        for slot in obj.material_slots:
            if slot.material and slot.material not in materials:
                materials.append(slot.material)
    return materials

def materialFingerprint(material):
    images = set()
    if material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                images.add(bpy.path.abspath(node.image.filepath) or node.image.name)
    return (baseName(material.name), frozenset(images))

def dedupeMaterialSlots(obj):
    """Collapse repeated material slots on one mesh: remap its faces to the
    first slot holding each material, then drop the now-duplicate slots.
    Returns the number of slots removed."""
    mesh = obj.data
    slots = obj.material_slots
    # remember each face's material by identity before we disturb slot indices
    poly_material = []
    for poly in mesh.polygons:
        if 0 <= poly.material_index < len(slots):
            poly_material.append(slots[poly.material_index].material)
        else:
            poly_material.append(None)
    seen = set()
    duplicate_indices = []
    for index, slot in enumerate(slots):
        material = slot.material
        if material is None:
            continue
        if material in seen:
            duplicate_indices.append(index)
        else:
            seen.add(material)
    if not duplicate_indices:
        return 0
    # remove from the highest index down so lower indices stay valid
    for index in reversed(duplicate_indices):
        mesh.materials.pop(index=index)
    # reassign faces by material identity to the surviving slot order
    mat_to_index = {slot.material: index for index, slot in enumerate(obj.material_slots) if slot.material is not None}
    for poly, material in zip(mesh.polygons, poly_material):
        if material in mat_to_index:
            poly.material_index = mat_to_index[material]
    return len(duplicate_indices)

def stripTrailingNumbers(meshes):
    """Remove trailing .001-style suffixes from the export set. If the base
    name is held by an object outside the set, swap names with it; if it's
    held inside the set, that's a real conflict. Returns (renamed, errors)."""
    renamed = []
    errors = []
    for obj in meshes:
        if not ("." in obj.name and obj.name.split(".")[-1].isdigit()):
            continue
        base = obj.name.rsplit(".", 1)[0]
        holder = bpy.data.objects.get(base)
        if holder and holder is not obj and holder in meshes:
            group = sorted(o.name for o in meshes if baseName(o.name) == base)
            errors.append("Cannot remove trailing number: %s all share the base name '%s'" % (", ".join(group), base))
            continue
        old_name = obj.name
        if holder and holder is not obj:
            obj.name = base + ".__swap__"
            holder.name = old_name
        obj.name = base
        renamed.append("%s -> %s" % (old_name, obj.name))
    return renamed, errors

def runSelectCleanup(context):
    """Select the armature's export set and run all validation/cleanup checks.
    Returns a list of (level, message) where level is INFO/WARNING/ERROR."""
    report = []
    armature = activeExportArmature(context)
    if not armature:
        return [('ERROR', "Select an Armature first")]

    deselectAll(context)
    meshes = exportMeshes(context, armature)
    if not meshes:
        return [('ERROR', "No mesh objects found under the armature (check the Visible Only toggle)")]

    armature.hide_set(False)
    armature.select_set(True)
    for obj in meshes:
        obj.select_set(True)
    context.view_layer.objects.active = armature

    # 1. trailing .001 suffix cleanup, with conflict detection inside the set.
    # Runs again after step 2, whose renames can collide and pick up fresh
    # suffixes; errors are deduplicated across the two passes.
    renamed, name_errors = stripTrailingNumbers(meshes)

    # 2. x_y -> x__y (first underscore doubled), anything ending in a number
    # like hair1 / hair_1 / hair__1 -> hair__hair_1, bare hair -> hair__hair,
    # then x__y format check
    underscored = []
    numbered = []
    doubled = []
    bad_format = []
    renames = {'underscored': underscored, 'numbered': numbered, 'doubled': doubled}
    for obj in meshes:
        # Set the intentional __opt marker (and any trailing number) aside so
        # its double underscore isn't mistaken for the x__y prefix separator;
        # the format fix runs on the bare name, then __opt is restored.
        base, opt, number = splitOptSuffix(obj.name)
        new_base, kind = formatExportName(base)
        if new_base != base:
            old_name = obj.name
            obj.name = new_base + opt + number
            renames[kind].append("%s -> %s" % (old_name, obj.name))
        if "__" not in new_base:
            bad_format.append(obj.name)

    # second .001 sweep: the step-2 renames collide with existing names and
    # silently gain a fresh trailing number, which the first pass never saw
    renamed_after, errors_after = stripTrailingNumbers(meshes)
    renamed += renamed_after
    for error in errors_after:
        if error not in name_errors:
            name_errors.append(error)

    if renamed:
        report.append(('INFO', "Removed trailing numbers from %d object(s): %s" % (len(renamed), ", ".join(renamed))))
    for error in name_errors:
        report.append(('ERROR', error))
    if underscored:
        report.append(('INFO', "Converted x_y to x__y naming on %d object(s): %s" % (len(underscored), ", ".join(underscored))))
    if numbered:
        report.append(('INFO', "Converted name+number to name__name_number on %d object(s): %s" % (len(numbered), ", ".join(numbered))))
    if doubled:
        report.append(('INFO', "Converted name to name__name on %d object(s): %s" % (len(doubled), ", ".join(doubled))))
    if bad_format:
        report.append(('WARNING', "Not in x__y naming format: %s" % ", ".join(bad_format)))

    # 3/4. primaryactive0/secondaryactive0 presence by skeleton type
    names_lower = [o.name.lower() for o in meshes]
    has_primary = any(n.startswith("primaryactive0__") for n in names_lower)
    has_secondary = any(n.startswith("secondaryactive0__") for n in names_lower)
    if skeletonUsesLowercase(armature):
        if not has_primary:
            report.append(('WARNING', "Ranged skeleton: no primaryactive0__ object found"))
        if not has_secondary:
            report.append(('WARNING', "Ranged skeleton: no secondaryactive0__ object found"))
    else:
        if not has_primary:
            report.append(('INFO', "Melee skeleton: no primaryactive0__ object found"))
        if not has_secondary:
            report.append(('INFO', "Melee skeleton: no secondaryactive0__ object, check if needed"))

    # 5. collapse repeated material slots on a single object (same material
    # assigned to two slots), so the count check below sees real materials
    slot_deduped = []
    for obj in meshes:
        removed = dedupeMaterialSlots(obj)
        if removed:
            slot_deduped.append("%s (%d)" % (obj.name, removed))
    if slot_deduped:
        report.append(('INFO', "Removed duplicate material slots from %d object(s): %s" % (len(slot_deduped), ", ".join(slot_deduped))))

    # 6. material count per object
    bad_counts = []
    for obj in meshes:
        count = sum(1 for slot in obj.material_slots if slot.material)
        if count > 2 or count == 0:
            bad_counts.append("%s (%d)" % (obj.name, count))
    if bad_counts:
        report.append(('ERROR', "Objects need 1-2 materials: %s" % ", ".join(bad_counts)))

    # 7. de-duplicate identical materials (material1 vs material1.001)
    fingerprints = {}
    remapped = []
    for material in uniqueMaterials(meshes):
        fp = materialFingerprint(material)
        original = fingerprints.get(fp)
        if original is None:
            fingerprints[fp] = material
            continue
        for obj in meshes:
            for slot in obj.material_slots:
                if slot.material == material:
                    slot.material = original
        remapped.append("%s -> %s" % (material.name, original.name))
    if remapped:
        report.append(('INFO', "Merged duplicate materials: %s" % ", ".join(remapped)))

    # 8. objects with no weights at all
    weightless = []
    for obj in meshes:
        has_weight = False
        if obj.vertex_groups:
            for v in obj.data.vertices:
                if any(g.weight > 0.0 for g in v.groups):
                    has_weight = True
                    break
        if not has_weight:
            weightless.append(obj.name)
    if weightless:
        report.append(('ERROR', "Objects with no vertex weights: %s" % ", ".join(weightless)))

    # 9. per-texture UV tile placement runs separately (checkUVSpace), after
    # the operator has auto-detected the main/attach textures, so it can tell
    # main objects (first tile) from attach objects (tile to the right).

    # 10. texture dimensions
    seen_images = set()
    for material in uniqueMaterials(meshes):
        if not material.use_nodes:
            continue
        for node in material.node_tree.nodes:
            if node.type != 'TEX_IMAGE' or not node.image or node.image in seen_images:
                continue
            seen_images.add(node.image)
            w, h = node.image.size
            if w == 0 and h == 0:
                report.append(('WARNING', "%s: image file not found on disk" % node.image.name))
            elif w != h or not isPowerOfTwo(w) or not isPowerOfTwo(h):
                reason = "not square" if w != h else "not a power of two"
                report.append(('ERROR', "%s: %dx%d is not a standard texture format (%s)" % (node.image.name, w, h, reason)))
            elif w not in RECOMMENDED_SIZES:
                hint = "too low" if w < RECOMMENDED_SIZES[0] else "too high"
                report.append(('WARNING', "%s: %dx%d is %s, 512/1024/2048 recommended" % (node.image.name, w, h, hint)))

    if not report:
        report.append(('INFO', "All checks passed"))
    return report

def objectMainAttach(obj, main_mat, attach_mat):
    """Classify a mesh as an attach-texture object (True) or a main-texture
    object (False) from the materials on its slots."""
    mats = [slot.material for slot in obj.material_slots if slot.material]
    return attach_mat is not None and attach_mat in mats and main_mat not in mats

def checkUVSpace(context):
    """Check UV tile placement per texture: main-texture objects must keep
    their UVs in the first tile (u 0..1), attach-texture objects in the tile
    one unit to the right (u 1..2). Returns (report, wrong_objects) where
    wrong_objects is the list of offending mesh objects for the optional
    select-and-edit toggle. Skips (with a warning) when the textures aren't
    set yet or a duplicate/extra-texture problem still needs resolving."""
    report = []
    wrong = []
    armature = activeExportArmature(context)
    if not armature:
        return report, wrong
    export_data = armature.med2_toolkit_unit_export
    meshes = exportMeshes(context, armature)
    if not meshes:
        return report, wrong

    def resolve(name):
        return bpy.data.materials.get(name) if name and name != 'none' else None
    main_mat = resolve(export_data.material_main)
    attach_mat = resolve(export_data.material_attach)

    # can't tell which tile an object belongs in with no texture assigned
    if main_mat is None and attach_mat is None:
        report.append(('WARNING', "Textures not set, so UV space checking was not initiated. Set the main/attach texture and rerun the check."))
        return report, wrong

    # UV tiles are assigned per texture, so every mesh must use only the main
    # and/or attach material; a third texture makes the tile ambiguous
    allowed = {m for m in (main_mat, attach_mat) if m is not None}
    extra = sorted({obj.name for obj in meshes for slot in obj.material_slots
                    if slot.material and slot.material not in allowed})
    if extra:
        report.append(('WARNING', "Multiple material textures still present on: %s. Resolve them (Force Textures or remove the extra material) before UV space checking." % ", ".join(extra)))
        return report, wrong

    eps = 0.001
    main_wrong = []
    attach_wrong = []
    for obj in meshes:
        is_attach = objectMainAttach(obj, main_mat, attach_mat)
        target = attach_wrong if is_attach else main_wrong
        lo, hi = (1.0, 2.0) if is_attach else (0.0, 1.0)
        uv_layer = obj.data.uv_layers.active
        if uv_layer is None:
            wrong.append(obj)
            target.append(obj.name + " (no UVs)")
            continue
        for loop_uv in uv_layer.data:
            u, v = loop_uv.uv
            if u < lo - eps or u > hi + eps or v < -eps or v > 1.0 + eps:
                wrong.append(obj)
                target.append(obj.name)
                break

    if main_wrong:
        report.append(('WARNING', "Main-texture objects with UVs outside the first tile (u 0-1): %s" % ", ".join(main_wrong)))
    if attach_wrong:
        report.append(('WARNING', "Attach-texture objects with UVs outside the tile to the right (u 1-2): %s" % ", ".join(attach_wrong)))
    return report, wrong

def forceTextures(context):
    """Fold every .NNN numbered duplicate of the selected main/attach material
    into that material across all export mesh slots, even if the duplicates use
    different textures. Only 'material.001'/'material.002' style names match;
    'material1.001' has base 'material1' and is left alone unless it is the
    selected material. Returns a list of (level, message)."""
    armature = activeExportArmature(context)
    if not armature:
        return [('ERROR', "Select an Armature first")]
    export_data = armature.med2_toolkit_unit_export
    meshes = exportMeshes(context, armature)
    if not meshes:
        return [('ERROR', "No mesh objects found under the armature (check the Visible Only toggle)")]

    keepers = []
    main_mat = bpy.data.materials.get(export_data.material_main)
    if main_mat:
        keepers.append(main_mat)
    attach_mat = bpy.data.materials.get(export_data.material_attach) if export_data.material_attach != 'none' else None
    if attach_mat and attach_mat not in keepers:
        keepers.append(attach_mat)
    if not keepers:
        return [('ERROR', "Select a main material first")]

    # a numbered material folds into a keeper when it shares the keeper's base
    # name; keepers themselves are never folded
    keeper_set = set(keepers)
    remap = {}
    for material in uniqueMaterials(meshes):
        if material in keeper_set:
            continue
        if not ("." in material.name and material.name.split(".")[-1].isdigit()):
            continue
        base = material.name.rsplit(".", 1)[0]
        for keeper in keepers:
            if baseName(keeper.name) == base:
                remap[material] = keeper
                break

    if not remap:
        return [('INFO', "No .NNN duplicate materials found for the selected material(s)")]

    report = []
    changed = 0
    for obj in meshes:
        for slot in obj.material_slots:
            if slot.material in remap:
                target = remap[slot.material]
                report.append(('INFO', "%s: %s -> %s" % (obj.name, slot.material.name, target.name)))
                slot.material = target
                changed += 1
    # forcing usually leaves the keeper in two slots on the same object
    for obj in meshes:
        dedupeMaterialSlots(obj)
    report.insert(0, ('INFO', "Forced %d material slot(s) to the selected texture(s)" % changed))
    return report
