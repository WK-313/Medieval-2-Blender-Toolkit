import bpy
import json
import random
from pathlib import Path
from . import recurlayercollection
from .task_writer import unitTaskAppend, unitTaskRun, engineTaskAppend, engineTaskRun
script_folder = Path(__file__).parent.parent

def postImport(self, context):
        if context.scene.med2_toolkit_units.frame_toggle:
            bpy.ops.view3d.view_all(center=False)
        if context.scene.med2_toolkit_units.textured_toggle and bpy.context.space_data.shading.type == 'SOLID':
            bpy.context.space_data.shading.light = 'FLAT'
            bpy.context.space_data.shading.color_type = 'TEXTURE'

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

def unitChecker(model_folder, unit_list, upgrade):
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
    fileChecker(model_folder, files_to_check)
    engineChecker(model_folder, engines_to_check)


def fileChecker(model_folder, model_list):
    with open(script_folder/('text/model_dictionary.json'), 'r') as bmdb_input:
        bmdb_dictionary = json.load(bmdb_input)
    missing_count = 0
    for model_id in model_list:
        model_mesh = bmdb_dictionary[model_id]['Mesh']
        if not Path(str(model_folder)+model_mesh).exists():
            print("Model '%s' not found in folder %s." % (model_mesh, str(model_folder)))
            print("Appending to the task file")
            unitTaskAppend(model_id)
            missing_count += 1
    if missing_count != 0:
        unitTaskRun()


def engineChecker(model_folder, model_list):
    missing_count = 0
    for model_id in model_list:
        engine_mesh = model_id+'.glb'
        if not Path(str(model_folder)+engine_mesh).exists():
            print("Model '%s' not found in folder %s." % (engine_mesh, str(model_folder)))
            print("Appending to the task file")
            engineTaskAppend(model_id)
            missing_count += 1
    if missing_count != 0:
        engineTaskRun()


def unitImporter(model_folder, unit_info, faction_id, coordinates, upgrade):
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
    if unit_attachment == 'unused':
        result, width, z_offset = modelImporter(model_folder, unit_name, faction_id, model_info, model_id)
        if result == 0:
            return(0)
        if coordinates != [0, 0, 0]:
            coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
        bpy.data.objects[unit_name].location = coordinates
        bpy.data.objects[unit_name].location[2] += z_offset
    elif unit_attachment[0] == 'mount':
        mount_info = attachment_dictionary[unit_attachment[1]]
        mount_model = bmdb_dictionary[mount_info['Model']]
        result, width, z_offset = modelImporter(model_folder, unit_name, faction_id, mount_model, model_id)
        if result == 0:
            return(0)
        if coordinates != [0, 0, 0]:
            coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
        mount_object = bpy.data.objects[unit_name]
        mount_object.location = coordinates
        mount_object.location[2] += z_offset
        n = 1
        for member in mount_info['Crew']:
            rider_coordinates = [
                float(member[0]),
                float(member[1]),
                float(member[2])
            ]
            result, c_width, z_offset = modelImporter(model_folder, unit_name+' Rider '+str(n), faction_id, model_info, model_id)
            if result == 0:
                return(0)
            rider_object = bpy.data.objects[unit_name+' Rider '+str(n)]
            rider_object.parent = mount_object
            rider_object.location = rider_coordinates
            n += 1
    elif unit_attachment[0] == 'engine':
        engine_info = attachment_dictionary[unit_attachment[1]]
        engine_model = unit_attachment[1]
        result, width, z_offset = engineImporter(model_folder, unit_name, faction_id, engine_model+'.glb')
        if result == 0:
            return(0)
        if coordinates != [0, 0, 0]:
            coordinates[0] = coordinates[0] + round(width*0.5, 1) + 0.25
        engine_object = bpy.data.objects[unit_name]
        engine_object.location = coordinates
        engine_object.location[2] += z_offset
        n = 1
        for member in engine_info['Crew']:
            rider_coordinates = [
                float(member[0]),
                -float(member[1]),
                float(member[2])
            ]
            result, c_width, z_offset = modelImporter(model_folder, unit_name+' Crew '+str(n), faction_id, model_info, model_id)
            if result == 0:
                return(0)
            crew_object = bpy.data.objects[unit_name+' Crew '+str(n)]
            crew_object.parent = engine_object
            crew_object.location = rider_coordinates
            crew_object.location[2] += z_offset
            n += 1
    if result == 2:
        item = bpy.context.scene.med2_toolkit_import_list.add()
        item.name = unit_name
        item.id = unit_info['ID']
        if unit_attachment == 'unused':
            item.icon = unit_attachment
        else:
            item.icon = unit_attachment[0]
    return(width)


def engineImporter(model_folder, unit_name, faction_id, engine_model):
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

def materialWorkflow(texture_path, texture, normal_texture, material):
    #Setup material mode and keywords
    material.use_nodes = True
    material.blend_method = 'CLIP'
    material.use_backface_culling = True
    nodes = material.node_tree.nodes
    new_link = material.node_tree.links.new

    #Defining nodes
    shader_node = material.node_tree.nodes["Principled BSDF"]
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