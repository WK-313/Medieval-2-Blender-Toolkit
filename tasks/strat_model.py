"""Turning a battle unit into a campaign map (strat) model.

The manual process this replaces is the "Quick Tutorial For Strat Models w/
Blender and IWTE" guide, which is nine steps of hand work plus the Material
Combiner addon:

    extract the unit with IWTE -> delete the variations -> combine the main and
    attachment textures into one atlas by hand -> import a strat armature ->
    match the bone name case -> strip the bones the strat skeleton does not
    have and re-rig whatever was weighted to them -> join every mesh -> parent
    with empty groups -> limit weights to one bone and normalise -> assign the
    combined texture -> scale both UV islands 50% and slide them into place ->
    export -> convert back to .cas with IWTE

buildStratModel does all of that in one operator, and exportStratCAS does the
conversion. Two things are done properly here that the guide leaves to the
modder:

- the atlas is built to a known layout rather than whatever Material Combiner
  packs, so the UV transform is exact instead of a guess. The addon already
  requires the main texture's UVs in tile u 0-1 and the attachment's in u 1-2
  (see export_checks.checkUVSpace), which is all the information needed to put
  each island in its own half of the atlas.
- weights on bones the strat skeleton does not have (clavicals, jaw, eyebrow,
  weapon groups, bowstrings, anything custom) are folded into the nearest
  ancestor bone that does exist, instead of being dropped. Dropped weights are
  what produces IWTE's "Some vertices have no bone weights and have been
  assigned to the models first bone eg pelvis" warning and the limbs that trail
  off the model on the campaign map.
"""
import os
import re
import shutil

import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree

from .armature_tools import caseConvertedName, mergeGroupInto, skeletonUsesLowercase
from .export_checks import activeExportArmature, deselectAll, exportMeshes, materialImages
from .importer import principledNode
from .iwte_run import NO_WINE, canRunWindowsExe, findIWTEExe, startIWTETask, winePath
from .strat_data import NON_DEFORM_BONES, STRAT_BONES

# The UV layer every mesh is renamed to before the join. join() only merges UV
# layers that share a name; differently named ones each become a separate layer
# on the result and the mesh ends up with one UV set per source object.
JOINED_UV = 'joined_uv'

STRAT_TAG = 'med2_strat_model'

# The campaign map crashes on load on a strat model past 10,000 triangles, so
# this is the game's own ceiling rather than a style guide. Nothing here refuses
# to build or export on it - an over-budget model is still the modder's to
# decimate - but the build says so in red and the panel does too, and the 7,000
# mark is called out in yellow while there is still room to do something about
# it.
STRAT_TRIANGLE_LIMIT = 10000
STRAT_TRIANGLE_CAUTION = 7000


def cleanPath(path):
    return os.path.normpath(path.strip('"').strip("'")) if path else ''


def triangleCount(obj):
    """Triangles the mesh exports as: a quad is two, an n-gon is n - 2, which is
    how the GLB - and so the .cas IWTE writes from it - counts them.

    foreach_get rather than a walk over polygons because the panel asks for this
    on every redraw, and a battle unit is tens of thousands of faces.
    """
    mesh = obj.data
    faces = len(mesh.polygons)
    if not faces:
        return 0
    loop_totals = np.empty(faces, dtype=np.int32)
    mesh.polygons.foreach_get('loop_total', loop_totals)
    return int(loop_totals.sum()) - 2 * faces


def modelTriangles(meshes):
    """Triangles the strat model will have. The join never merges geometry, so
    the sum over the source meshes is what comes out of it."""
    return sum(triangleCount(obj) for obj in meshes)


def triangleLevel(triangles):
    """How bad a triangle count is: 'ERROR' past the game's limit, 'WARNING'
    approaching it, 'INFO' below. The one place the two thresholds are read, so
    the build report and the panel always agree."""
    if triangles > STRAT_TRIANGLE_LIMIT:
        return 'ERROR'
    if triangles > STRAT_TRIANGLE_CAUTION:
        return 'WARNING'
    return 'INFO'


def freeName(collection, name):
    """Make a datablock name available.

    The strat material and its image must carry the texture name EXACTLY - the
    .cas records it and the campaign map crashes on load when it does not match
    a file in the mod - so Blender handing back `name.001` is not an option. A
    datablock already sitting on the name is dropped when nothing uses it and
    renamed aside when something does, which is never destructive: rebuilding a
    model twice must not strip the material off the first build's mesh.
    """
    existing = collection.get(name)
    if existing is None:
        return
    if existing.users == 0:
        collection.remove(existing)
    else:
        existing.name = name + "_previous"


def stratBoneNames(lowercase):
    return [caseConvertedName(name, True) if lowercase else name
            for name, _parent, _head, _tail in STRAT_BONES]


#   -------------------  #
#   The strat skeleton    #
#   -------------------  #

def buildStratArmature(context, collection, name, lowercase, matrix):
    """Create the strat skeleton from strat_data, in the bone name case the
    model is rigged in, sitting at the source rig's transform."""
    data = bpy.data.armatures.new(name)
    armature = bpy.data.objects.new(name, data)
    armature[STRAT_TAG] = True
    collection.objects.link(armature)
    armature.matrix_world = matrix

    previous_active = context.view_layer.objects.active
    context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for bone_name, parent, head, tail in STRAT_BONES:
            if lowercase:
                bone_name = caseConvertedName(bone_name, True)
                parent = caseConvertedName(parent, True) if parent else ''
            bone = data.edit_bones.new(bone_name)
            bone.head = Vector(head)
            bone.tail = Vector(head) + Vector(tail)
            bone.roll = 0.0
            if parent:
                bone.parent = data.edit_bones[parent]
            # every strat bone is a free-standing joint: connecting them would
            # drag each head onto its parent's tail and move the skeleton
            bone.use_connect = False
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = previous_active
    return armature


#   ---------------  #
#   Weights          #
#   ---------------  #

def remapOrphanGroups(source_armature, meshes, strat_names):
    """Fold every vertex group weighted to a bone the strat skeleton has not
    got into the nearest ancestor bone it has.

    A battle rig carries clavicals, a jaw, an eyebrow and the weapon groups;
    custom rigs add bowstring and cloth bones. Their weights have to go
    somewhere - a clavicle's onto the torso, a jaw's onto the head - or the
    vertices they hold come out unweighted. Returns (report, remapped names).
    """
    report = []
    keep = {name.lower() for name in strat_names}
    mapping = {}
    orphans = []
    for bone in source_armature.data.bones:
        if bone.name.lower() in keep:
            continue
        parent = bone.parent
        while parent is not None and parent.name.lower() not in keep:
            parent = parent.parent
        if parent is None:
            orphans.append(bone.name)
        else:
            mapping[bone.name.lower()] = parent.name

    remapped = set()
    for obj in meshes:
        for group in list(obj.vertex_groups):
            target_name = mapping.get(group.name.lower())
            if target_name is None:
                continue
            target = obj.vertex_groups.get(target_name)
            if target is None:
                target = obj.vertex_groups.new(name=target_name)
            # mergeGroupInto deletes the source, so its name is read first
            source_name = group.name
            mergeGroupInto(obj, group, target)
            remapped.add("%s -> %s" % (source_name, target_name))

    if remapped:
        report.append(('INFO', "Bones the strat skeleton has not got, folded into their nearest parent: %s"
                       % ", ".join(sorted(remapped))))
    if orphans:
        report.append(('WARNING', "Bone(s) with no strat equivalent anywhere up their parent chain, their weights are dropped: %s"
                       % ", ".join(sorted(orphans))))
    return report


def collapseToOneBone(obj, strat_names):
    """The .cas format gives a vertex exactly one bone, so every vertex keeps
    only its strongest weight, at 1.0 - the guide's "limit total to 1" followed
    by "normalize all", done directly on the mesh data.

    Groups that do not name a strat bone are ignored when picking the winner
    and removed afterwards, so a leftover group cannot quietly win a vertex and
    then convert to nothing. Returns the vertices left with no weight at all.
    """
    keep = {name.lower() for name in strat_names} - NON_DEFORM_BONES
    valid = {group.index for group in obj.vertex_groups if group.name.lower() in keep}
    dead = [group.name for group in obj.vertex_groups if group.index not in valid]

    # decided in full first, then written back per group: removing weights
    # while walking a vertex's own group list invalidates it underneath us
    winners = {}
    unweighted = []
    for vertex in obj.data.vertices:
        best_group = None
        best_weight = 0.0
        for entry in vertex.groups:
            if entry.group in valid and entry.weight > best_weight:
                best_group = entry.group
                best_weight = entry.weight
        if best_group is None:
            unweighted.append(vertex.index)
        else:
            winners.setdefault(best_group, []).append(vertex.index)

    every_vertex = [vertex.index for vertex in obj.data.vertices]
    for group in obj.vertex_groups:
        group.remove(every_vertex)
    for group_index, vertices in winners.items():
        obj.vertex_groups[group_index].add(vertices, 1.0, 'REPLACE')

    # by name: each removal renumbers the groups after it
    for name in dead:
        group = obj.vertex_groups.get(name)
        if group is not None:
            obj.vertex_groups.remove(group)
    return unweighted


def weldUnweighted(obj, unweighted):
    """Give every unweighted vertex the bone of the nearest weighted one.

    These are the "loose vertices" the guide's troubleshooting section has the
    modder hunt down by hand after IWTE warns about them. The nearest weighted
    neighbour is nearly always the right answer, because they are loose exactly
    where a stripped bone (a clavicle, a bowstring) used to hold a few verts in
    the middle of an otherwise weighted mesh.
    """
    if not unweighted:
        return []
    loose = set(unweighted)
    weighted = [v for v in obj.data.vertices if v.index not in loose]
    if not weighted:
        return [('WARNING', "No vertex on the joined mesh carries a weight - nothing to weld the loose ones to")]

    tree = kdtree.KDTree(len(weighted))
    for position, vertex in enumerate(weighted):
        tree.insert(vertex.co, position)
    tree.balance()

    fixed = 0
    for index in unweighted:
        _co, position, _distance = tree.find(obj.data.vertices[index].co)
        source = weighted[position]
        group_index = next((entry.group for entry in source.groups if entry.weight > 0.0), None)
        if group_index is None:
            continue
        obj.vertex_groups[group_index].add([index], 1.0, 'REPLACE')
        fixed += 1
    if fixed:
        return [('INFO', "%d vertex/vertices had no weight left and were welded to their nearest weighted neighbour" % fixed)]
    return [('WARNING', "%d vertex/vertices have no weight and could not be welded - IWTE will assign them to the pelvis" % len(unweighted))]


#   ---------------  #
#   Texture atlas    #
#   ---------------  #

SCRATCH_IMAGE = '_med2_strat_scratch'


def imagePixels(image, width, height):
    """The image resampled to width x height as a (height, width, 4) array.
    None when the image has no pixels (a texture whose file has gone).

    The resampling goes through a scratch image so Blender does the filtering,
    but the pixels are read out of the source rather than copying the datablock:
    Image.copy() of a generated or painted image copies how it was made, not
    what is in it, and would hand back a blank half of the atlas.
    """
    if image is None:
        return None
    try:
        source_width, source_height = image.size
        if source_width <= 0 or source_height <= 0:
            return None
        buffer = np.empty(source_width * source_height * 4, dtype=np.float32)
        image.pixels.foreach_get(buffer)
    except (RuntimeError, ValueError):
        return None
    if (source_width, source_height) == (width, height):
        return buffer.reshape(height, width, 4)

    scratch = bpy.data.images.new(SCRATCH_IMAGE, source_width, source_height,
                                  alpha=True, float_buffer=True)
    try:
        scratch.pixels.foreach_set(buffer)
        scratch.scale(width, height)
        scaled = np.empty(width * height * 4, dtype=np.float32)
        scratch.pixels.foreach_get(scaled)
        return scaled.reshape(height, width, 4)
    except (RuntimeError, ValueError):
        return None
    finally:
        bpy.data.images.remove(scratch)


def buildAtlas(name, main_image, attach_image, size, square, filepath):
    """Write the combined texture and return (image, error).

    Layout, with the main texture always in the left half:

        square (the guide's): a size x size image, main top-left, attach
            top-right, bottom half unused. This is the layout the tutorial's
            createStratModel.py assumes and what is known to work in game.
        wide: a size x size/2 image, main left, attach right, nothing wasted.

    Either way a source UV of (u, v) in the main tile lands at (u/2, ...) and
    one in the attach tile at (0.5 + u/2, ...), which is what remapUVs applies.
    """
    height = size if square else size // 2
    cell = size // 2
    atlas = np.zeros((height, size, 4), dtype=np.float32)
    # Blender's pixel rows run bottom to top, so "the top half" is the far end
    top = height - cell

    missing = []
    for image, column in ((main_image, 0), (attach_image, cell)):
        if image is None:
            continue
        pixels = imagePixels(image, cell, cell)
        if pixels is None:
            missing.append(image.name)
            continue
        atlas[top:top + cell, column:column + cell] = pixels

    freeName(bpy.data.images, name)
    result = bpy.data.images.new(name, size, height, alpha=True)
    result.pixels.foreach_set(atlas.ravel())
    result.filepath_raw = filepath
    result.file_format = 'TARGA'
    try:
        result.save()
    except RuntimeError as error:
        return None, "Could not write %s: %s" % (filepath, error)
    result.filepath = filepath
    if missing:
        return result, "No pixel data for %s (is the file still on disk?) - that half of the atlas is blank" % ", ".join(missing)
    return result, None


#   ---------------  #
#   UVs              #
#   ---------------  #

def remapUVs(obj, main_material, attach_material, square):
    """Scale each face's UVs into its half of the atlas.

    Done per face rather than per object so a mesh carrying both materials
    still comes out right, and the tile shift is measured rather than assumed:
    an attachment island already sitting in u 1-2 is brought back a tile first,
    one left in u 0-1 is taken as it is.
    """
    uv_layer = obj.data.uv_layers.active
    if uv_layer is None:
        return

    attach_loops = []
    main_loops = []
    for polygon in obj.data.polygons:
        material = None
        if polygon.material_index < len(obj.material_slots):
            material = obj.material_slots[polygon.material_index].material
        # == rather than `is`: comparing bpy structs by identity is unreliable
        is_attach = (attach_material is not None and material is not None
                     and material == attach_material and material != main_material)
        (attach_loops if is_attach else main_loops).extend(polygon.loop_indices)

    shift = 0.0
    if attach_loops:
        lowest = min(uv_layer.data[index].uv[0] for index in attach_loops)
        # the addon's own export check puts the attachment island in u 1-2; a
        # model that never moved it there is scaled where it stands
        shift = 1.0 if lowest >= 0.5 else 0.0

    for index in main_loops:
        uv = uv_layer.data[index].uv
        uv[0] = uv[0] * 0.5
        if square:
            uv[1] = uv[1] * 0.5 + 0.5
    for index in attach_loops:
        uv = uv_layer.data[index].uv
        uv[0] = 0.5 + (uv[0] - shift) * 0.5
        if square:
            uv[1] = uv[1] * 0.5 + 0.5


#   ---------------  #
#   The build        #
#   ---------------  #

def duplicateRig(context, armature, meshes, collection):
    """A standalone copy of the rig in its own collection.

    Copied by hand rather than with duplicate(): that operator only copies mesh
    data when the "Duplicate Data" preference says so, and a strat build that
    silently edited the battle model's meshes instead of its own would destroy
    the unit the user still needs.
    """
    new_armature = armature.copy()
    new_armature.data = armature.data.copy()
    new_armature.animation_data_clear()
    collection.objects.link(new_armature)

    new_meshes = []
    for obj in meshes:
        copy = obj.copy()
        copy.data = obj.data.copy()
        copy.animation_data_clear()
        collection.objects.link(copy)
        new_meshes.append((obj, copy))

    context.view_layer.update()
    for original, copy in new_meshes:
        world = original.matrix_world.copy()
        # a mesh parented to a bone keeps parent_type 'BONE' through the copy,
        # which would re-home it onto whatever bone name it remembers
        copy.parent_type = 'OBJECT'
        copy.parent = new_armature
        copy.matrix_parent_inverse = Matrix.Identity(4)
        copy.matrix_world = world
        for modifier in list(copy.modifiers):
            if modifier.type == 'ARMATURE':
                modifier.object = new_armature
    return new_armature, [copy for _original, copy in new_meshes]


def joinMeshes(context, meshes, name):
    """Join every mesh into one, after giving their UV layers a common name.

    join() only merges UV layers whose names match, so meshes that came out of
    IWTE with per-object UV names ("characterlod0_map", "shield_map", ...) would
    otherwise produce one UV layer per source object on the joined mesh, and
    only the first would be the one the atlas was built for. Extra layers are
    dropped for the same reason - a strat model uses exactly one.
    """
    for obj in meshes:
        active = obj.data.uv_layers.active
        # by name, not by identity: Blender hands back a fresh wrapper on every
        # attribute access, so `layer is active` is False even for the same layer
        keep = active.name if active is not None else None
        for name in [uv_layer.name for uv_layer in obj.data.uv_layers if uv_layer.name != keep]:
            obj.data.uv_layers.remove(obj.data.uv_layers[name])
        if obj.data.uv_layers.active is not None:
            obj.data.uv_layers.active.name = JOINED_UV

    deselectAll(context)
    for obj in meshes:
        obj.select_set(True)
    target = meshes[0]
    context.view_layer.objects.active = target
    if len(meshes) > 1:
        bpy.ops.object.join()
    target.name = name
    target.data.name = name
    return target


def assignAtlasMaterial(obj, image, name):
    """One material, named after the texture. IWTE writes the texture name it
    finds here into the .cas, and the campaign map crashes on load when that
    name does not match a file in the mod - so the material, the image
    datablock and the .tga on disk all carry the same name."""
    obj.data.materials.clear()
    freeName(bpy.data.materials, name)
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.location = (-320, 280)
    principled = principledNode(material)
    material.node_tree.links.new(texture.outputs['Color'], principled.inputs['Base Color'])
    if 'Alpha' in principled.inputs:
        material.node_tree.links.new(texture.outputs['Alpha'], principled.inputs['Alpha'])
    if 'Roughness' in principled.inputs:
        principled.inputs['Roughness'].default_value = 1.0
    obj.data.materials.append(material)
    return material


def resolveMaterials(armature, meshes):
    """(main, attach) materials for the rig, from the Export workmode's
    settings. Both may be None."""
    export_data = getattr(armature, 'med2_toolkit_unit_export', None)

    def resolve(name):
        return bpy.data.materials.get(name) if name and name != 'none' else None

    main_material = resolve(getattr(export_data, 'material_main', ''))
    attach_material = resolve(getattr(export_data, 'material_attach', ''))
    if main_material is None:
        # nothing picked and nothing detectable: whatever the first mesh uses
        for obj in meshes:
            for slot in obj.material_slots:
                if slot.material is not None and slot.material != attach_material:
                    return slot.material, attach_material
    return main_material, attach_material


def stratOutputFolder(context, name):
    """Every model gets its own folder under the Strat Output path, the same
    way the unit export lays out its GLB, textures and task file."""
    base = cleanPath(bpy.path.abspath(context.scene.med2_toolkit_reader.directory_strat))
    return os.path.join(base, name) if base else ''


def buildStratModel(context):
    """Build the strat model from the active rig. Returns (report, object)."""
    settings = context.scene.med2_toolkit_strat
    armature = activeExportArmature(context)
    if armature is None:
        return [('ERROR', "Select the unit's armature, or a mesh under it")], None

    meshes = [obj for obj in armature.children_recursive
              if obj.type == 'MESH' and (not settings.visible_only or obj.visible_get())]
    if not meshes:
        return [('ERROR', "No mesh objects under the armature (check the Visible Only toggle)")], None

    name = settings.model_name.strip() or armature.name.lower()
    texture_name = settings.texture_name.strip() or (name + "_strat")
    out_dir = stratOutputFolder(context, name)
    if not out_dir:
        return [('ERROR', "Set the Strat Output path first")], None
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as error:
        return [('ERROR', "Could not create %s: %s" % (out_dir, error))], None

    report = []
    main_material, attach_material = resolveMaterials(armature, meshes)
    if main_material is None:
        report.append(('WARNING', "No main material found - run Check Model for Export in the Export workmode, or set the materials there"))
    main_image, _normal = materialImages(main_material)
    attach_image, _normal = materialImages(attach_material)
    if main_image is None:
        report.append(('WARNING', "The main material has no image texture, so the atlas has no main half"))

    # 1. a copy to work on, in its own collection, so the battle unit survives
    collection = bpy.data.collections.new(name)
    context.scene.collection.children.link(collection)
    if settings.keep_source:
        armature, meshes = duplicateRig(context, armature, meshes, collection)
    else:
        for obj in [armature] + meshes:
            for parent_collection in list(obj.users_collection):
                parent_collection.objects.unlink(obj)
            collection.objects.link(obj)

    lowercase = skeletonUsesLowercase(armature)
    strat_names = stratBoneNames(lowercase)
    report.append(('INFO', "Strat skeleton built with %s bone names" % ("lowercase" if lowercase else "uppercase")))

    # 2. weights on bones the strat skeleton has not got move to their nearest
    #    surviving parent, while the source rig is still around to be asked
    report.extend(remapOrphanGroups(armature, meshes, strat_names))

    # 3. UVs into their half of the atlas, per mesh, before the join loses
    #    which material each face used
    for obj in meshes:
        remapUVs(obj, main_material, attach_material, settings.atlas_layout == 'square')

    # 4. one mesh
    mesh = joinMeshes(context, meshes, name)
    triangles = triangleCount(mesh)
    level = triangleLevel(triangles)
    advice = ("Decimate the mesh, or leave the armour upgrades and hidden variants out with Visible Only")
    if level == 'ERROR':
        report.append(('ERROR', "%s triangles - over the %s limit, the campaign map will CRASH on load. %s"
                       % ("{:,}".format(triangles), "{:,}".format(STRAT_TRIANGLE_LIMIT), advice)))
    elif level == 'WARNING':
        report.append(('WARNING', "%s triangles - close to the %s the campaign map crashes past. %s"
                       % ("{:,}".format(triangles), "{:,}".format(STRAT_TRIANGLE_LIMIT), advice)))
    else:
        report.append(('INFO', "%s triangles" % "{:,}".format(triangles)))

    # 5. the strat skeleton, at the old rig's transform, and the mesh onto it
    strat_armature = buildStratArmature(context, collection, "Armature_" + name,
                                        lowercase, armature.matrix_world.copy())
    for modifier in list(mesh.modifiers):
        if modifier.type == 'ARMATURE':
            mesh.modifiers.remove(modifier)
    world = mesh.matrix_world.copy()
    mesh.parent = strat_armature
    mesh.matrix_parent_inverse = Matrix.Identity(4)
    mesh.matrix_world = world
    modifier = mesh.modifiers.new('Armature', 'ARMATURE')
    modifier.object = strat_armature
    for bone_name in strat_names:
        if mesh.vertex_groups.get(bone_name) is None:
            mesh.vertex_groups.new(name=bone_name)
    bpy.data.objects.remove(armature, do_unlink=True)
    # the view layer still lists the object that has just gone, and anything
    # walking context.view_layer.objects before it is rebuilt hits a None
    context.view_layer.update()

    # 6. one bone per vertex, and nothing left loose
    unweighted = collapseToOneBone(mesh, strat_names)
    if unweighted:
        report.extend(weldUnweighted(mesh, unweighted))

    # 7. the combined texture, and the single material that names it
    atlas_path = os.path.join(out_dir, texture_name + ".tga")
    atlas, error = buildAtlas(texture_name, main_image, attach_image,
                              int(settings.atlas_size), settings.atlas_layout == 'square',
                              atlas_path)
    if error:
        report.append(('WARNING', error))
    if atlas is not None:
        assignAtlasMaterial(mesh, atlas, texture_name)
        report.append(('INFO', "Combined texture written: %s" % atlas_path))

    settings.last_build_dir = out_dir
    settings.last_texture = atlas_path
    strat_armature[STRAT_TAG] = name

    deselectAll(context)
    strat_armature.select_set(True)
    mesh.select_set(True)
    context.view_layer.objects.active = strat_armature
    report.append(('INFO', "Strat model '%s' ready in the '%s' collection" % (name, collection.name)))
    return report, strat_armature


#   ---------------  #
#   Export           #
#   ---------------  #

def activeStratArmature(context):
    """The strat rig the panel acts on: the active object if it is one (or its
    parent), else the only one in the scene."""
    obj = context.object
    while obj is not None:
        if obj.type == 'ARMATURE' and obj.get(STRAT_TAG):
            return obj
        obj = obj.parent
    built = [o for o in context.scene.objects if o.type == 'ARMATURE' and o.get(STRAT_TAG)]
    return built[0] if len(built) == 1 else None


def exportStratGLB(context):
    """Write the strat rig out as a GLB for IWTE. Returns (error, path)."""
    settings = context.scene.med2_toolkit_strat
    armature = activeStratArmature(context)
    if armature is None:
        return "No strat model selected - build one first, or select its armature", ''
    meshes = [obj for obj in armature.children_recursive if obj.type == 'MESH']
    if not meshes:
        return "The strat armature has no mesh under it", ''

    name = settings.model_name.strip() or armature.get(STRAT_TAG) or armature.name
    out_dir = stratOutputFolder(context, name)
    if not out_dir:
        return "Set the Strat Output path first", ''
    os.makedirs(out_dir, exist_ok=True)
    glb_path = os.path.join(out_dir, name + ".glb")

    hidden = [(obj, obj.hide_get()) for obj in [armature] + meshes]
    try:
        for obj, was_hidden in hidden:
            if was_hidden:
                obj.hide_set(False)
        deselectAll(context)
        for obj in [armature] + meshes:
            obj.select_set(True)
        context.view_layer.objects.active = armature
        unselectable = [obj.name for obj in [armature] + meshes if not obj.select_get()]
        if unselectable:
            return "Cannot select for export (excluded collection?): %s" % ", ".join(unselectable), ''
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format='GLB',
            use_selection=True,
            export_apply=True,
            export_animations=False,
        )
    finally:
        for obj, was_hidden in hidden:
            if was_hidden:
                obj.hide_set(True)

    settings.last_exported_glb = glb_path
    return '', glb_path


def writeStratTask(task_path, glb_path, out_dir, cas_name, cas_format, skeleton_scale):
    """The IWTE extract_to_cas task file - the task behind Model Files > Cas
    Models > dae/ms3d to cas_mesh, which is the step the guide does by hand.

    The two paths go in as Windows paths: off Windows IWTE runs under Wine and
    reads a POSIX path as relative to its own folder."""
    with open(task_path, 'w', encoding='utf-8') as task_file:
        task_file.write(
            '<task_id>                                           extract_to_cas'
            '                                                       # read an extract file (.glb, .dae, .ms3d) and write a *.cas\n'
            '<extract_file_full_path_in>                         "%s"\n'
            '\n'
            '<directory_out>                                     "%s"\n'
            '\n'
            '<cas_mesh_file_name_out>                            "%s"\n'
            '<cas_animation_file_format>                         %s'
            '                                                                   # rr, m2 or full\n'
            '<skeleton_scale>                                    %.4f'
            '                                                               # scaling used to reset the skeleton *.cas to scale 1.0\n'
            % (winePath(glb_path), winePath(out_dir), cas_name, cas_format, skeleton_scale)
        )


def exportStratCAS(context):
    """Write the task file and launch IWTE. Returns an error string, or the job
    dict for the caller to watch until IWTE has written the .cas."""
    settings = context.scene.med2_toolkit_strat
    reader = context.scene.med2_toolkit_reader
    glb_path = cleanPath(settings.last_exported_glb)
    if not os.path.isfile(glb_path):
        return "No exported GLB found - run Export GLB first"

    iwte_dir = cleanPath(bpy.path.abspath(reader.directory_iwte))
    if not os.path.isdir(iwte_dir):
        return "Invalid IWTE folder"
    iwte_exe = findIWTEExe(iwte_dir)
    if not iwte_exe:
        return "IWTE executable not found"
    if not canRunWindowsExe():
        return NO_WINE % "IWTE"

    out_dir = os.path.dirname(glb_path)
    name = os.path.splitext(os.path.basename(glb_path))[0]
    task_path = os.path.join(out_dir, "iwte_extract_to_cas_%s_task.txt" % name)
    writeStratTask(task_path, glb_path, out_dir, name + ".cas",
                   settings.cas_format, settings.skeleton_scale)

    cas_path = os.path.join(out_dir, name + ".cas")
    settings.last_cas = cas_path
    return startIWTETask(iwte_exe, iwte_dir, task_path, cas_path)


#   ---------------  #
#   Checking         #
#   ---------------  #

# A .cas stores its texture reference as a plain string in the binary. The
# guide has the modder open the file in a text editor and search for ".tga"; the
# same search reads better from here.
CAS_NAME_BYTES = re.compile(rb'[A-Za-z0-9_\-./\\ ]{1,160}\.tga')


def casTextureNames(cas_path):
    """Every .tga the converted .cas refers to."""
    try:
        with open(cas_path, 'rb') as cas_file:
            data = cas_file.read()
    except OSError:
        return []
    names = []
    for match in CAS_NAME_BYTES.finditer(data):
        name = match.group().decode('ascii', errors='ignore').strip()
        if name and name not in names:
            names.append(name)
    return names


def checkCASTexture(context):
    """Compare what the .cas asks for against the texture that was written.
    The campaign map crashes on load when they disagree, which is the guide's
    single most common failure."""
    settings = context.scene.med2_toolkit_strat
    cas_path = cleanPath(settings.last_cas)
    if not os.path.isfile(cas_path):
        return [('ERROR', "No converted .cas to check yet")]

    names = casTextureNames(cas_path)
    if not names:
        return [('WARNING', "%s names no .tga at all - the material may have had no image when it was exported"
                 % os.path.basename(cas_path))]

    expected = os.path.basename(cleanPath(settings.last_texture)) if settings.last_texture else ''
    report = [('INFO', "%s refers to: %s" % (os.path.basename(cas_path), ", ".join(names)))]
    if expected:
        if any(os.path.basename(name.replace('\\', '/')).lower() == expected.lower() for name in names):
            report.append(('INFO', "Matches the texture that was written (%s)" % expected))
        else:
            report.append(('ERROR', "None of them is %s - the campaign map will crash on load unless the mod has a texture under the name(s) above"
                           % expected))
    return report


def installStratModel(context):
    """Copy the .cas and its .tga into the mod folder the user picked."""
    settings = context.scene.med2_toolkit_strat
    destination = cleanPath(bpy.path.abspath(settings.install_directory))
    if not destination:
        return [('ERROR', "Set the Install To folder first")]
    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as error:
        return [('ERROR', "Could not create %s: %s" % (destination, error))]

    report = []
    for label, source in (("model", settings.last_cas), ("texture", settings.last_texture)):
        source = cleanPath(source)
        if not source or not os.path.isfile(source):
            report.append(('WARNING', "No %s to install yet" % label))
            continue
        target = os.path.join(destination, os.path.basename(source))
        try:
            shutil.copy2(source, target)
        except OSError as error:
            report.append(('ERROR', "Could not copy %s: %s" % (os.path.basename(source), error)))
            continue
        report.append(('INFO', "Installed %s" % target))
    return report
