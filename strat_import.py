
import bpy
import os
from pathlib import Path, PurePath
import sys

def strat_importer(filepath):
    file_list = []
    file_type = bpy.context.scene.med2_tools.bulk_import_type
    if file_type == 'Collada':
        for file in os.listdir(filepath):
            #Get list of glb files
                if (file[-4:] == '.dae'):
                    file_list.append(PurePath(filepath, file))
        for object in file_list:
            bpy.ops.wm.collada_import(filepath = str(object))
    else:
        for file in os.listdir(filepath):
            #Get list of glb files
                if (file[-4:] == '.glb'):
                    file_list.append(PurePath(filepath, file))
        for object in file_list:
            bpy.ops.import_scene.gltf(filepath=(str(object)), disable_bone_shape=True)
    file = Path(filepath)
    folder = Path(filepath.rsplit('\\', 1)[0])
    #Setup materials
    normal_suffix = ['_normal.dds', '_norm.dds', '_nrm.dds', '_bump.dds']
    normal_textures = []
    for mat in bpy.data.materials:
        for path, subdirs, files in os.walk(folder):
            for texture in files:
                if any(suffix in texture for suffix in normal_suffix):
                    normal_textures.append(texture)
                    if mat.name.replace("_dds", ".dds").split('__')[0] == texture:
                        material = mat
                        #Setup material mode and keywords
                        material.use_nodes = True
                        material.blend_method = 'CLIP'
                        material.use_backface_culling = True
                        nodes = material.node_tree.nodes
                        new_link = material.node_tree.links.new

                        #Defining nodes
                        shader_node = material.node_tree.nodes["Principled BSDF"]
                        shader_node.inputs['Metallic'].default_value = 0
                        texture_image = nodes.new("ShaderNodeTexImage")
                        texture_image.location = (-506, 444)
                        texture_image.image = bpy.data.images.load(path+'\\'+texture)
                        #Linking nodes: colour -> shader; alpha -> shader; normal -> curves -> normal map -> shader
                        new_link(shader_node.inputs[0], texture_image.outputs[0])
                        # Normal setup
                        rgb_curve = nodes.new("ShaderNodeRGBCurve")
                        rgb_curve.location = (-506, 124)
                        # Flip the green channel
                        curve_g = rgb_curve.mapping.curves[1]
                        curve_g.points[0].location = (0, 1)
                        curve_g.points[1].location = (1, 0)
                        normal_map = nodes.new("ShaderNodeNormalMap")
                        normal_map.location = (-206, 124)
                        normal_image = nodes.new("ShaderNodeTexImage")
                        normal_image.name = 'Normal Texture'
                        normal_image.location = (-836, 124)
                        # Check Normal texture
                        for suffix in normal_suffix:
                            normal_texture = texture.replace(".dds", suffix)
                            if texture.replace(".dds", suffix) in normal_textures:
                                normal_image.image = bpy.data.images.load(path+'\\'+normal_texture)
                                normal_image.image.colorspace_settings.name = 'Non-Color'
                                # Linking nodes: normal -> curves -> normal map -> shader
                                new_link(shader_node.inputs[5], normal_map.outputs[0])
                                break
                        new_link(rgb_curve.inputs[1], normal_image.outputs[0])
                        new_link(normal_map.inputs[1], rgb_curve.outputs[0])

