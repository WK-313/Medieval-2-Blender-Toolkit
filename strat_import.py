
import bpy
import os
from pathlib import Path, PurePath
import sys
from math import pi

def layer_collection(name, _layer_collection=None):
    if _layer_collection is None:
        _layer_collection = bpy.context.view_layer.layer_collection
    if _layer_collection.name == name:
        return _layer_collection
    else:
        for l_col in _layer_collection.children:
            if rez := layer_collection(name=name, _layer_collection=l_col):
                return rez

def strat_importer(filepath):
    file_list = []
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    filepath = Path(filepath)
    test = bpy.data.collections.get(str(filepath).split('\\')[-1])
    if test == None:
        new_col = bpy.data.collections.new(str(filepath).split('\\')[-1])
        bpy.context.scene.collection.children.link(new_col)
        bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[-1]

    for path, subdirs, files in os.walk(filepath):
        #Create collections from subdirs
        test = bpy.data.collections.get(str(path).split('\\')[-1])
        if test == None:
            new_col = bpy.data.collections.new(str(path).split('\\')[-1])
            bpy.data.collections.get(str(path).split('\\')[-2]).children.link(new_col)
        #Get list of glb files
        for name in files:
            if (name[-3:] == 'glb'): file_list.append(PurePath(path, name))

    x = -21
    y = 0
    z = 0
    o = 0
    for model in file_list:
        if o == 15:
            y +=3
            x = -21
            o = 0
        test = bpy.data.collections.get(str(model).split('\\')[-2])
        if test == None:
            new_col = bpy.data.collections.new(str(model).split('\\')[-2])
            bpy.context.scene.collection.children.link(new_col)
            
        layer_col = layer_collection(name = str(model).split('\\')[-2])
        bpy.context.view_layer.active_layer_collection = layer_col
        
        bpy.ops.object.empty_add(type='CIRCLE')
        empty_parent = bpy.data.objects["Empty"]
        empty_parent.name=str(model).split('\\')[-1].split('.')[0]
        empty_parent.rotation_euler[0]=pi/2
        
        bpy.ops.import_scene.gltf(filepath=(str(model)), disable_bone_shape=True)
        bpy.context.view_layer.objects.active = empty_parent
        bpy.ops.object.parent_set(type='OBJECT', keep_transform=True)
        empty_parent.location=(x, y, z)
        x+=3
        o+=1

    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    #Setup materials
    for mat in bpy.data.materials:
        for path, subdirs, files in os.walk(filepath):
            for texture in files:
                if mat.name.split('.')[0].replace("_tga", ".tga") == texture:
                    material = mat
                    #Setup material mode and keywords
                    material.use_nodes = True
                    material.blend_method = 'CLIP'
                    material.use_backface_culling = True
                    nodes = material.node_tree.nodes
                    new_link = material.node_tree.links.new

                    #Defining nodes
                    shader_node = material.node_tree.nodes["Principled BSDF"]
                    texture_image = nodes.new("ShaderNodeTexImage")
                    texture_image.location = (-506, 444)
                    texture_image.image = bpy.data.images.load(path+'\\'+texture)
                    #Linking nodes: colour -> shader; alpha -> shader; normal -> curves -> normal map -> shader
                    new_link(shader_node.inputs[0], texture_image.outputs[0])

