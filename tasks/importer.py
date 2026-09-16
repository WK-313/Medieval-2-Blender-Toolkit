import bpy
import json
import random
from pathlib import Path
from . import recurlayercollection
from ..directories import withTrailingSep
from .task_writer import unitTaskAppend, unitTaskRun, engineTaskAppend, engineTaskRun
from .unit_groups import tagGroup
script_folder = Path(__file__).parent.parent

def postImport(self, context):
        if context.scene.med2_toolkit_units.frame_toggle:
            bpy.ops.view3d.view_all(center=False)
        if context.scene.med2_toolkit_units.textured_toggle and bpy.context.space_data.shading.type == 'SOLID':
            bpy.context.space_data.shading.light = 'FLAT'
            bpy.context.space_data.shading.color_type = 'TEXTURE'

def importedArmature(existing_objects):
    # Return the armature created since existing_objects was captured. modelImporter
    # names the new object after the unit, but when that name is already taken (e.g.
    # a unit lists the same officer twice, or every armour upgrade shares the unit's
    # ID) Blender appends ".001", so looking the object up by the requested name hands
    # back the earlier duplicate and the real new rig never gets positioned - it sits
    # at the world origin. Diff the object set instead.
    for obj in bpy.data.objects:
        if obj not in existing_objects and obj.type == 'ARMATURE':
            return obj
    return None

def selectionBoundingBox():
    selection_bounding_box = []
    for child in bpy.context.active_object.children_recursive:
        if child.type == 'MESH':
            box = [v[:] for v in child.bound_box]
            selection_bounding_box += box
    boundaries_min = [min(idx) for idx in zip(*selection_bounding_box)]
    boundaries_max = [max(idx) for idx in zip(*selection_bounding_box)]
    width = boundaries_max[0] - boundaries_min[0]
    z_offset = boundaries_min[2]*-1
    print("Width: %s" % width)
    print("Z Offset: %s" % z_offset)
    return(width, z_offset)

def unitChecker(model_folder, unit_list, upgrade, defer=False):
    # defer=True appends the missing models to the task files but does NOT hand
    # them to IWTE, and returns (units, engines) so the caller can run one
    # conversion for a whole batch and watch it without freezing Blender. The
    # default runs the task straight away, which is what every single-unit
    # import wants.
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    with open(script_folder/('text/attachment_dictionary.json'), 'r') as attachment_input:
        attachment_dictionary = json.load(attachment_input)
    files_to_check = []
    engines_to_check = []
    for unit_info in unit_list:
        unit_attachment = unit_info['Attachment']
        try:
            model_id = unit_info['Model'][upgrade]
        except IndexError:
            model_id = unit_info['Model'][-1]
        if unit_attachment[0] == 'mount':
            mount_info = attachment_dictionary[unit_attachment[1]]['Model']
            files_to_check.append(mount_info)
        files_to_check.append(model_id)
        if unit_attachment[0] == 'engine':
            engines_to_check.append(unit_attachment[1])
    missing_units = fileChecker(model_folder, files_to_check, defer)
    missing_engines = engineChecker(model_folder, engines_to_check, defer)
    return missing_units, missing_engines


def unconvertedModels(model_folder, unit_list, upgrade):
    """[(model id, what is wrong)] for every model these units need that is still
    not in the import folder, ready to print as "model id: what is wrong".

    unitChecker reports what it handed IWTE, not what IWTE handed back, so a
    model whose .mesh is nowhere on disk comes out of it looking converted and
    then imports as nothing: modelImporter returns 0, unitImporter passes that
    straight out, and the operator finishes without a word. The usual cause is a
    vanilla asset - a mod that rides, say, mount_armoured_horse has no loose
    .mesh for IWTE to read unless the game's own data/packs have been unpacked -
    and on a mounted unit it costs you the rider too, because the mount is
    imported first and its failure returns before the rider is reached.

    Run this AFTER the conversion: whatever is still missing here is something no
    import can produce.
    """
    model_folder = withTrailingSep(model_folder)
    with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
        bmdb_dictionary = json.load(bmdb_input)
    with open(script_folder/('text/attachment_dictionary.json'), 'r') as attachment_input:
        attachment_dictionary = json.load(attachment_input)
    missing = []
    for unit_info in unit_list:
        unit_attachment = unit_info['Attachment']
        model_ids = []
        if not unit_info['Model']:
            # the EDU named no model at all - see eduEntries, which falls back to
            # the `soldier` line, so this is a unit read before that existed or
            # an entry with neither. Nothing to look for on disk, so say what is
            # wrong rather than raising IndexError out of a helper.
            missing.append((unit_info.get('ID') or unit_info.get('Type', 'unit'),
                            'no model named in export_descr_unit.txt'))
        else:
            try:
                model_ids.append(unit_info['Model'][upgrade])
            except IndexError:
                model_ids.append(unit_info['Model'][-1])
        if unit_attachment[0] == 'mount':
            # named before the unit's own model because it is imported first and
            # a missing mount takes the rider with it
            model_ids.insert(0, attachment_dictionary[unit_attachment[1]]['Model'])
        for wanted in model_ids:
            model_info = bmdb_dictionary.get(wanted)
            if model_info is None:
                missing.append((wanted, 'not in battle_models.modeldb'))
            elif not Path(str(model_folder)+model_info['Mesh']).exists():
                missing.append((wanted, 'no %s, and nothing to convert at %s/%s'
                                        % (model_info['Mesh'], model_info['Folder'],
                                           model_info['Mesh'].replace('.glb', '.mesh'))))
        if unit_attachment[0] == 'engine':
            engine_mesh = unit_attachment[1]+'.glb'
            if not Path(str(model_folder)+engine_mesh).exists():
                missing.append((unit_attachment[1], 'no %s, and IWTE did not convert it' % engine_mesh))
    # a unit can name one model twice - the same upgrade on both sides of a
    # mount, say - and it is one problem, not two
    return list(dict.fromkeys(missing))


def fileChecker(model_folder, model_list, defer=False):
    # Returns the model ids that were appended to the task file. With
    # defer=True the task is left for the caller to run - see unitChecker.
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
        bmdb_dictionary = json.load(bmdb_input)
    missing = []
    for model_id in model_list:
        model_mesh = bmdb_dictionary[model_id]['Mesh']
        if not Path(str(model_folder)+model_mesh).exists():
            print("Model '%s' not found in folder %s." % (model_mesh, str(model_folder)))
            print("Appending to the task file")
            unitTaskAppend(model_id)
            missing.append(model_id)
    if missing and not defer:
        unitTaskRun()
    return missing


def engineChecker(model_folder, model_list, defer=False):
    # Returns the engine ids that were appended to the task file.
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    missing = []
    for model_id in model_list:
        engine_mesh = model_id+'.glb'
        if not Path(str(model_folder)+engine_mesh).exists():
            print("Model '%s' not found in folder %s." % (engine_mesh, str(model_folder)))
            print("Appending to the task file")
            engineTaskAppend(model_id)
            missing.append(model_id)
    if missing and not defer:
        engineTaskRun()
    return missing


def missingModelPaths(model_folder, model_ids, engine_ids):
    """Where each deferred conversion is expected to land, so a watcher can
    count how many of them have appeared. Unit meshes are named by the BMDB, an
    engine simply by its own id.

    Deduplicated by NAME, not by model id: several BMDB entries can point at one
    .glb - they differ only in their textures - so a caller that has already
    deduplicated its ids still ends up asking for the same file twice. England
    alone is 123 ids over 114 files."""
    model_folder = withTrailingSep(model_folder)
    with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
        bmdb_dictionary = json.load(bmdb_input)
    names = [bmdb_dictionary[model_id]['Mesh'] for model_id in model_ids]
    names += [engine_id+'.glb' for engine_id in engine_ids]
    return [Path(str(model_folder)+name) for name in dict.fromkeys(names)]


def placeMember(member_object, role, member_coordinates, member_width, member_z,
                unit, coordinates, apply_offset):
    """Put one rider or crew member in place, whether or not the thing it rides
    turned up, and record it in `unit`.

    A mount or engine that would not convert used to abort the whole import -
    see unconvertedModels for why a model goes missing at all - which cost the
    user the rider too, and the rider is usually the model they came for. So
    when nothing has claimed the root yet, the first member that does arrive
    takes the mount's place on the ground, and the ones after it hang off that
    member at their offsets MINUS its own, which keeps an elephant's crew spread
    out and standing on the ground rather than floating at the height the
    missing elephant would have carried them.

    With a real root present nothing changes: members parent to it at exactly
    the offsets descr_mount / descr_engines gives.
    """
    if unit['root']:
        member_object.parent = unit['root']
        location = [member_coordinates[axis] - unit['offset'][axis] for axis in range(3)]
        if unit['grounded']:
            # nothing is carrying them any more, so they all stand on the
            # ground rather than keeping the heights the missing mount held
            # them at - an elephant's crew sit in a howdah and on its neck, and
            # the lower one would end up buried. They are all the same model,
            # so the root's own z_offset is theirs too and z stays flat.
            location[2] = 0
        member_object.location = location
        unit['parts'].append((member_object, role))
        return
    if apply_offset and coordinates != [0, 0, 0]:
        coordinates[0] = coordinates[0] + round(member_width*0.5, 1) + 0.25
    member_object.location = list(coordinates)
    member_object.location[2] += member_z
    unit['root'] = member_object
    unit['role'] = "Unit"
    unit['offset'] = list(member_coordinates)
    unit['width'] = member_width
    unit['grounded'] = True


def unitImporter(model_folder, unit_info, faction_id, coordinates, upgrade, apply_offset=True):
    # apply_offset=False lets a caller place this exact `coordinates` (e.g.
    # stacking a unit's armour upgrades on Z) without the auto x-spacing below,
    # which otherwise fires on any non-origin `coordinates` regardless of axis.
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
        bmdb_dictionary = json.load(bmdb_input)
    with open(script_folder/('text/attachment_dictionary.json'), 'r') as attachment_input:
        attachment_dictionary = json.load(attachment_input)
    unit_name = unit_info["ID"]
    unit_attachment = unit_info['Attachment']
    try:
        model_id = unit_info['Model'][upgrade]
    except IndexError:
        model_id = unit_info['Model'][-1]
    recurlayercollection.findCollection(unit_name)
    model_info = bmdb_dictionary[model_id]
    result = 0
    # What the unit ends up rooted on, filled in as the import goes. A mount or
    # an engine imports as several armatures - itself plus one per crew member -
    # and it is the root when it arrives; when it does NOT, the first member to
    # arrive stands in its place instead of the whole unit being abandoned (see
    # placeMember). 'parts' collects the rest as [(object, role)], tied to the
    # root by tagGroup below so every tool downstream can treat the lot as one
    # unit however they end up parented once they have control rigs. 'offset' is
    # what member offsets are measured from, which is the origin while the root
    # is the real mount or engine.
    # 'grounded' says the root is a member standing in for a mount or engine
    # that never arrived, which changes how the members after it are placed.
    unit = {'root': None, 'role': "Unit", 'offset': [0, 0, 0], 'width': 0,
            'grounded': False, 'parts': []}
    # Every rig imported here is looked up by diffing the object set, never by
    # bpy.data.objects[unit_name]: each armour upgrade of a unit is named after
    # the same unit ID, so Blender hands the later ones a ".001" suffix and a
    # name lookup returns the FIRST rig instead. That moved upgrade 0 out to the
    # right and left the newest rig unpositioned at the origin, sunk below the
    # ground because its z_offset was never applied.
    if unit_attachment == 'unused':
        existing = set(bpy.data.objects)
        result, width, z_offset = modelImporter(model_folder, unit_name, faction_id, model_info, model_id)
        if result == 0:
            return(0)
        if apply_offset and coordinates != [0, 0, 0]:
            coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
        root_object = importedArmature(existing)
        if root_object:
            root_object.location = coordinates
            root_object.location[2] += z_offset
            unit['root'] = root_object
            unit['width'] = width
    elif unit_attachment[0] == 'mount':
        mount_info = attachment_dictionary[unit_attachment[1]]
        mount_model = bmdb_dictionary[mount_info['Model']]
        existing = set(bpy.data.objects)
        result, width, z_offset = modelImporter(model_folder, unit_name, faction_id, mount_model, model_id)
        mount_object = importedArmature(existing) if result != 0 else None
        if mount_object:
            if apply_offset and coordinates != [0, 0, 0]:
                coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
            mount_object.location = coordinates
            mount_object.location[2] += z_offset
            unit['root'] = mount_object
            unit['role'] = "Mount"
            unit['width'] = width
        n = 1
        for member in mount_info['Crew']:
            rider_coordinates = [
                float(member[0]),
                float(member[1]),
                float(member[2])
            ]
            existing = set(bpy.data.objects)
            result, rider_width, rider_z = modelImporter(model_folder, unit_name+' Rider '+str(n), faction_id, model_info, model_id)
            rider_object = importedArmature(existing) if result != 0 else None
            if rider_object:
                placeMember(rider_object, 'Rider %d' % n, rider_coordinates,
                            rider_width, rider_z, unit, coordinates, apply_offset)
            n += 1
    elif unit_attachment[0] == 'engine':
        engine_info = attachment_dictionary[unit_attachment[1]]
        engine_model = unit_attachment[1]
        existing = set(bpy.data.objects)
        result, width, z_offset = engineImporter(model_folder, unit_name, faction_id, engine_model+'.glb')
        engine_object = importedArmature(existing) if result != 0 else None
        if engine_object:
            if apply_offset and coordinates != [0, 0, 0]:
                coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
            engine_object.location = coordinates
            engine_object.location[2] += z_offset
            unit['root'] = engine_object
            unit['role'] = "Engine"
            unit['width'] = width
        n = 1
        for member in engine_info['Crew']:
            rider_coordinates = [
                float(member[0]),
                -float(member[1]),
                float(member[2])
            ]
            existing = set(bpy.data.objects)
            result, crew_width, crew_z = modelImporter(model_folder, unit_name+' Crew '+str(n), faction_id, model_info, model_id)
            crew_object = importedArmature(existing) if result != 0 else None
            if crew_object:
                # unlike a rider, a crew member stands on the ground beside its
                # engine, so its own z_offset goes into the offset itself
                rider_coordinates[2] += crew_z
                placeMember(crew_object, 'Crew %d' % n, rider_coordinates,
                            crew_width, crew_z, unit, coordinates, apply_offset)
            n += 1
    root_object, parts, root_role = unit['root'], unit['parts'], unit['role']
    # whatever arrived, rather than "the last modelImporter call succeeded":
    # a unit can now be listed with its mount missing, or with one rider of
    # three, and it is the objects in the scene the list has to match
    if root_object:
        group = tagGroup(root_object, parts, root_role) if parts else ""
        # the icon comes from what arrived too - a mounted unit whose mount did
        # not convert is on foot in this scene, and the list's type filter must
        # not offer a mount row that has no mount behind it
        icon = {'Mount': 'mount', 'Engine': 'engine'}.get(root_role, 'unused')
        import_list = bpy.context.scene.med2_toolkit_import_list
        item = import_list.add()
        item.name = unit_name
        item.id = unit_info['ID']
        # the real object name, which carries a .001 suffix when several
        # upgrades of the same unit are in the scene - the list's delete
        # option needs it to find the right rig
        item.object_name = root_object.name if root_object else unit_name
        item.faction = faction_id
        item.icon = icon
        item.group = group
        # One entry per armature of a multi-part unit, folded under the root's
        # disclosure arrow. They carry the same unit id and type as the root, so
        # searching and the type filter keep a unit and its crew together.
        for part_object, role in parts:
            part_item = import_list.add()
            part_item.name = role
            part_item.id = unit_info['ID']
            part_item.object_name = part_object.name
            part_item.faction = faction_id
            part_item.icon = icon
            part_item.group = group
            part_item.role = role
            part_item.is_part = True
    # the width of whatever is standing at `coordinates`, which is the rider
    # rather than the mount when the mount did not arrive - the caller spaces
    # the next unit off this
    return(unit['width'])


def engineImporter(model_folder, unit_name, faction_id, engine_model):
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    if not Path(str(model_folder)+engine_model).exists():
        print("Model '%s' not found in folder %s." % (engine_model, str(model_folder)))
        return(0, 0, 0)
    # checkCollections(faction_id)
    bpy.ops.import_scene.gltf(filepath=(model_folder+engine_model), disable_bone_shape=True)
    obj_armature = bpy.context.active_object
    obj_armature.name = unit_name
    width, z_offset = selectionBoundingBox()
    skel_armature = obj_armature.data
    skel_armature.name = unit_name
    skel_armature.display_type = 'STICK'
    obj_armature.show_in_front = False
    # Materials
    bpy.ops.object.select_all(action='DESELECT')
    obj_armature.select_set(True)
    texture_folder = model_folder+('textures/')
    for parent_object in bpy.context.selected_objects:
        for obj in parent_object.children_recursive:
            material = obj.data.materials[0]
            texture = material.name.split('__')[1]
            material.name = texture
            normal_texture = texture.replace('.dds', '_bump.dds')
            materialWorkflow(texture_folder, texture, normal_texture, material)
    return(2, width, z_offset)

def modelImporter(model_folder, unit_name, faction_id, model_info, model_id):
    # the Unit Output path is joined onto bare file names below, and the
    # Paths field holds it with a trailing separator only when it was
    # browsed to rather than typed
    model_folder = withTrailingSep(model_folder)
    model_mesh = model_info['Mesh']
    if not Path(str(model_folder)+model_mesh).exists():
        print("Model '%s' for %s not found in folder %s." % (model_mesh, model_id, str(model_folder)))
        return(0, 0, 0)
    # checkCollections(faction_id)
    # Import models
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    bpy.ops.import_scene.gltf(filepath=(model_folder+model_mesh), disable_bone_shape=True)
    obj_armature = bpy.context.active_object
    obj_armature.name = unit_name
    width, z_offset = selectionBoundingBox()
    skel_armature = obj_armature.data
    skel_armature.name = unit_name
    skel_armature.display_type = 'STICK'
    obj_armature.show_in_front = False
    # Materials
    try:
        textures = model_info['Textures'][faction_id]
    except KeyError:
        textures = list(model_info['Textures'].values())[0]
    if len(textures) == 4:
        attachment_textures = textures[2:]
    main_textures = textures[:2]
    texture_folder = model_folder+('textures/')
    bpy.ops.object.select_all(action='DESELECT')
    obj_armature.select_set(True)
    for parent_object in bpy.context.selected_objects:
        for obj in parent_object.children_recursive:
            material = obj.data.materials[0]
            if any(x in material.name for x in ['__main', '__single']) and checkExistingMaterials(material, main_textures[0]) == False:
                material.name = main_textures[0]
                materialWorkflow(texture_folder, main_textures[0], main_textures[1], material)
            elif '__attach' in material.name and checkExistingMaterials(material, attachment_textures[0])  == False:
                material.name = attachment_textures[0]
                materialWorkflow(texture_folder, attachment_textures[0], attachment_textures[1], material)
    bpy.ops.object.select_all(action='DESELECT')
    obj_armature.select_set(True)
    if bpy.context.scene.med2_toolkit_units.hide_toggle:
        hideVariations()
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    return(2, width, z_offset)


def checkCollections(faction_id):
    # Check if faction has a collection. Create if not
    with open(script_folder/('text/available_factions.json'), 'r') as import_factions_input:
        factions = json.load(import_factions_input)
    for faction in factions:
        if factions[faction] == faction_id:
            faction_name = faction
            break
    recurlayercollection.findCollection(faction_name)

def checkExistingMaterials(current_material, material_name):
    #Test whenever a material is already in use, if not, proceed to material setup. If it already exists, replace the current material with the exisiting one
    seach_material = bpy.data.materials.get(material_name)
    if seach_material == None:
        print("Material doesn't exists: creating")
        return False
    model = findFirstObject(current_material)
    if model == "None":
        return False
    model.select_set(True)
    bpy.context.view_layer.objects.active = model
    bpy.ops.object.select_linked(type='MATERIAL')
    model.data.materials[0] = seach_material
    bpy.ops.object.make_links_data(type='MATERIAL')
    return True

def findFirstObject(current_material):
    #Find the first object which uses the current material, then return the object
    bpy.ops.object.select_all(action='DESELECT')
    for model in bpy.data.objects:
        #Only proceed if object is a mesh
        if model.type == 'MESH' and len(model.data.materials)!=0:
            if model.data.materials[0] == current_material:
                return(model)
    return("None")

def principledNode(material):
    """The material's Principled BSDF, looked up by node type, never by name.

    A Blender whose interface language is not English and which has
    Preferences > Interface > Translation > New Data switched on names every
    newly created node in that language, so the shader the glTF importer built
    comes back as "Принципиальный BSDF" (or whatever the language is) and
    nodes["Principled BSDF"] raises a KeyError - the model imports, the
    material setup dies before a single texture is loaded. Node types are not
    translated. A material that genuinely arrived without a principled shader
    gets one built and wired to the output here, so the caller always has a
    shader to link its textures into."""
    node_tree = material.node_tree
    for node in node_tree.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node
    shader_node = node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    shader_node.location = (10, 300)
    output_node = None
    for node in node_tree.nodes:
        if node.type == 'OUTPUT_MATERIAL':
            output_node = node
            break
    if output_node is None:
        output_node = node_tree.nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (300, 300)
    #Sockets by index for the same reason: BSDF out -> Surface in
    node_tree.links.new(output_node.inputs[0], shader_node.outputs[0])
    return shader_node

def materialWorkflow(texture_path, texture, normal_texture, material):
    #Setup material mode and keywords
    material.use_nodes = True
    material.blend_method = 'CLIP'
    material.use_backface_culling = True
    nodes = material.node_tree.nodes
    new_link = material.node_tree.links.new

    #Defining nodes
    shader_node = principledNode(material)
    shader_node.inputs['Metallic'].default_value = 0
    shader_node.inputs['Roughness'].default_value = 0.5
    
    texture_image = nodes.new("ShaderNodeTexImage")
    texture_image.name = 'Diffuse Texture'
    texture_image.location = (-506, 444)
    #Check if texture file doesn't exist
    file_check = Path(texture_path+texture)
    if not file_check.exists():
        print("No texture file found;", texture)
    else:
        print("Image found")
        texture_image.image = bpy.data.images.load(texture_path+texture)
        #Linking nodes: colour -> shader; alpha -> shader
        new_link(shader_node.inputs[0], texture_image.outputs[0])
        new_link(shader_node.inputs[4], texture_image.outputs[1])
    
    rgb_curve = nodes.new("ShaderNodeRGBCurve")
    rgb_curve.location = (-506, 124)
    #Flip the green channel
    curve_g = rgb_curve.mapping.curves[1]
    curve_g.points[0].location = (0, 1)
    curve_g.points[1].location = (1, 0)
    
    normal_map = nodes.new("ShaderNodeNormalMap")
    normal_map.location = (-206, 124)
    normal_image = nodes.new("ShaderNodeTexImage")
    normal_image.name = 'Normal Texture'
    normal_image.location = (-836, 124)
    multiply_node = nodes.new("ShaderNodeMath")
    multiply_node.location = (-206, 295)
    multiply_node.operation = 'MULTIPLY'
    multiply_node.inputs[1].default_value = 7.5

    #Check if texture file doesn't exist
    file_check = Path(texture_path+normal_texture)
    if not file_check.exists():
        print("No texture file found:", normal_texture)
    else:
        normal_image.image = bpy.data.images.load(texture_path+normal_texture)
        normal_image.image.colorspace_settings.name = 'Non-Color'
        #Linking nodes: normal -> curves -> normal map -> shader
        new_link(rgb_curve.inputs[1], normal_image.outputs[0])
        new_link(shader_node.inputs[1], multiply_node.outputs[0])
    new_link(multiply_node.inputs[0], normal_image.outputs[1])
    new_link(normal_map.inputs[1], rgb_curve.outputs[0])
    new_link(shader_node.inputs[5], normal_map.outputs[0])

#Check the comments of the model names and hide variations
def hideVariations():
    for parent_object in bpy.context.selected_objects:
        #Unhide all
        for obj in parent_object.children:
            obj.hide_render = False
            obj.hide_set(False)
        parent_object.select_set(True)
        list_of_names = []
        n = 0
        #Compare the object comment to the list of comments, if it's already registered, hide the current object
        obj_list = [x for x in parent_object.children if x.type == 'MESH']
        random.shuffle(obj_list)
        shield = "shieldpassive"
        weapon = "secondaryactive"
        if bpy.context.scene.med2_toolkit_units.primary_secondary == "secondary":
            if any ("shieldpassive" in obj.name for obj in obj_list):
                shield = "shieldactive"
            if any ("secondaryactive" in obj.name for obj in obj_list):
                weapon = "primaryactive"
        for obj in obj_list:
            object_group = obj.name.split("__")
            #Hide secondaries and passives
            if any(x in obj.name for x in [shield, weapon]):
                obj.hide_render = True
                obj.hide_set(True)
            elif object_group[0] in list_of_names:
                obj.hide_render = True
                obj.hide_set(True)
            else:
                list_of_names.append(object_group[0])