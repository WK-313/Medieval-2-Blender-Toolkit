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

def exportMeshes(context, armature):
    export_data = context.scene.med2_toolkit_unit_export
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

def runSelectCleanup(context):
    """Select the armature's export set and run all validation/cleanup checks.
    Returns a list of (level, message) where level is INFO/WARNING/ERROR."""
    report = []
    armature = context.object
    if not armature or armature.type != 'ARMATURE':
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

    # 1. trailing .001 suffix cleanup, with conflict detection inside the set
    renamed = []
    for obj in meshes:
        if not ("." in obj.name and obj.name.split(".")[-1].isdigit()):
            continue
        base = obj.name.rsplit(".", 1)[0]
        holder = bpy.data.objects.get(base)
        if holder and holder is not obj and holder in meshes:
            group = sorted(o.name for o in meshes if baseName(o.name) == base)
            report.append(('ERROR', "Cannot remove trailing number: %s all share the base name '%s'" % (", ".join(group), base)))
            continue
        old_name = obj.name
        if holder and holder is not obj:
            obj.name = base + ".__swap__"
            holder.name = old_name
        obj.name = base
        renamed.append("%s -> %s" % (old_name, obj.name))
    if renamed:
        report.append(('INFO', "Removed trailing numbers from %d object(s): %s" % (len(renamed), ", ".join(renamed))))

    # 2. x_y -> x__y (first underscore doubled), name+number like hair1 ->
    # hair__hair_1, then x__y format check
    underscored = []
    numbered = []
    bad_format = []
    for obj in meshes:
        if "__" not in obj.name and "_" in obj.name:
            old_name = obj.name
            head, _, tail = obj.name.partition("_")
            obj.name = head + "__" + tail
            underscored.append("%s -> %s" % (old_name, obj.name))
        elif "_" not in obj.name:
            match = re.fullmatch(r"([A-Za-z]+?)(\d+)", obj.name)
            if match:
                old_name = obj.name
                base, number = match.groups()
                obj.name = "%s__%s_%s" % (base, base, number)
                numbered.append("%s -> %s" % (old_name, obj.name))
        if "__" not in obj.name:
            bad_format.append(obj.name)
    if underscored:
        report.append(('INFO', "Converted x_y to x__y naming on %d object(s): %s" % (len(underscored), ", ".join(underscored))))
    if numbered:
        report.append(('INFO', "Converted name+number to name__name_number on %d object(s): %s" % (len(numbered), ", ".join(numbered))))
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

    # 5. material count per object
    bad_counts = []
    for obj in meshes:
        count = sum(1 for slot in obj.material_slots if slot.material)
        if count > 2 or count == 0:
            bad_counts.append("%s (%d)" % (obj.name, count))
    if bad_counts:
        report.append(('ERROR', "Objects need 1-2 materials: %s" % ", ".join(bad_counts)))

    # 6. de-duplicate identical materials (material1 vs material1.001)
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

    # 7. objects with no weights at all
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

    # 8. UVs must stay inside the main tile and one tile to the right
    eps = 0.001
    uv_offenders = []
    for obj in meshes:
        uv_layer = obj.data.uv_layers.active
        if uv_layer is None:
            uv_offenders.append(obj.name + " (no UVs)")
            continue
        for loop_uv in uv_layer.data:
            u, v = loop_uv.uv
            if u < -eps or u > 2.0 + eps or v < -eps or v > 1.0 + eps:
                uv_offenders.append(obj.name)
                break
    if uv_offenders:
        report.append(('WARNING', "UVs outside the allowed 2x1 tile space: %s" % ", ".join(uv_offenders)))

    # 9. texture dimensions
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
