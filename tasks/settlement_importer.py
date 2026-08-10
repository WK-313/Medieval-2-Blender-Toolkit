import bpy
import os
import re
from pathlib import Path
from . import recurlayercollection
from .importer import principledNode
from .task_writer import settlementTaskAppend, settlementTaskRun, unitTaskAppend
script_folder = Path(__file__).parent.parent

def settlementChecker(settlement_folder, world, name):
    if not bpy.context.scene.med2_toolkit_settlements.use_existing_settlement:
        print("Appending to the task file")
        settlementTaskAppend(world)
        settlementTaskRun()
        return
    if not Path(settlement_folder+world.replace('.world', '.glb')).exists():
        print("World '%s' not found in folder %s." % (name, settlement_folder))
        print("Appending to the task file")
        settlementTaskAppend(world)
        settlementTaskRun()
        

def settlementImporter(settlement_folder, name, world):
    settlementChecker(settlement_folder, world, name)
    if not Path(settlement_folder+world.replace('.world', '.glb')).exists():
        print("Files %s not found in folder %s." % (world, settlement_folder))
        return('Files not found')
    recurlayercollection.findCollection(name.replace('.Worldpkgdesc', ''))
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    bpy.ops.import_scene.gltf(filepath=(settlement_folder+world.replace('.world', '.glb')))
    imported = bpy.context.selected_objects
    for obj in imported:
        if 'complex_' in obj.name:
            obj.hide_render = True
            obj.hide_set(True)
    bpy.ops.view3d.view_all(center=False)
    print('Material setup starting')
    #Setup materials
    texture_path = os.path.join(settlement_folder, 'data\\blockset\\textures\\')
    for material in bpy.data.materials:
        texture_name = re.sub(r"_dds.*", ".dds", material.name)
        if not Path(texture_path+texture_name).exists():
            print("Texture %s not found for material %s in folder %s." % (texture_name, material.name, texture_path))
            continue
        
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE':
                print('Skipping already set up material %s' % material.name)
                continue
        
        #Setup material mode and keywords
        material.use_nodes = True
        material.blend_method = 'CLIP'
        material.use_backface_culling = True
        nodes = material.node_tree.nodes
        new_link = material.node_tree.links.new

        #Defining nodes
        shader_node = principledNode(material)
        texture_image = nodes.new("ShaderNodeTexImage")
        texture_image.location = (-506, 444)
        texture_image.image = bpy.data.images.load(texture_path+texture_name)
        #Linking nodes: colour -> shader; alpha -> shader; normal -> curves -> normal map -> shader
        new_link(shader_node.inputs[0], texture_image.outputs[0])
    print('Material setup finished')
    bpy.context.space_data.shading.light = 'FLAT'
    bpy.context.space_data.shading.color_type = 'TEXTURE'
    return('Finished')
