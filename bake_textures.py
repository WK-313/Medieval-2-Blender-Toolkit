import bpy

# To do:
# Option to clear primary/secondary UVs
# Option to auto assign new material to selection

def bake_textures(resolution, alpha_toggle, reset_uvs, rotation_toggle, create_material, bake_type):
    if len(bpy.context.selected_objects)!=0:
        # Define lists for materials/object using the material
        # Reset Bake textures to apply changes to settings
        # Filter non mesh objects and objects without materials
        # List the first appearance of a material and the object using it so they can be used to select by material
        mat_list = []
        mbj_list = []
        if bake_type in ('Diffuse','Both'):
            bake_texture = bpy.data.images.get("Bake_texture")
            if bake_texture != None:
                bpy.data.images.remove(bake_texture)
            bpy.data.images.new("Bake_texture", resolution, resolution, alpha=alpha_toggle)
        if bake_type in ('Normal','Both'):
            normal_texture = bpy.data.images.get("Bake_normal")
            if normal_texture != None:
                bpy.data.images.remove(normal_texture)
            bpy.data.images.new("Bake_normal", resolution, resolution, alpha=alpha_toggle)
        for obj in bpy.context.selected_objects:
            if obj.type != 'MESH' or len(obj.data.materials) == 0:
                obj.select_set(False)
            else:
                uv_map = obj.data.uv_layers.get('UV_Bake')
                if uv_map == None:
                    obj.data.uv_layers.new(name='UV_Bake')
                elif reset_uvs:
                    obj.data.uv_layers.remove(uv_map)
                    obj.data.uv_layers.new(name='UV_Bake')
                obj.data.uv_layers['UV_Bake'].active = True
                for mat in obj.data.materials:
                    if mat not in mat_list:
                        mat_list.append(mat)
                        mbj_list.append(obj)
                print(mat_list)

        # Save the selection so that it can be reset later
        obj_list = bpy.context.selected_objects
        # Set up bake texture and from selection choose all objects using the same material
        # Check for bake UVs and create if missing. Set bake UVs as active
        # Repack the UVs and offset them to avoid overlapping with other materials before final packing
        i_obj = 0
        offset = 1
        for mat in mat_list:
            # Set up bake texture
            nodes = mat.node_tree.nodes
            new_link = mat.node_tree.links.new
            uv_test = nodes.get("Diffuse Bake")
            if uv_test != None:
                nodes.active = uv_test
                uv_test.select = True
                if uv_test.image == None:
                    uv_test.image = bpy.data.images.get("Bake_texture")
            else:
                texture_image = nodes.new("ShaderNodeTexImage")
                nodes.active = texture_image
                texture_image.name = "Diffuse Bake"
                texture_image.location = (456, 344)
                texture_image.image = bpy.data.images.get("Bake_texture")
            normal_test = nodes.get("Normal Bake")
            if normal_test == None:
                normal_image = nodes.new("ShaderNodeTexImage")
                normal_image.name = "Normal Bake"
                normal_image.location = (456, 50)
                normal_image.image = bpy.data.images.get("Bake_normal")
            else:
                if normal_test != None and normal_test.image == None:
                    normal_test.image = bpy.data.images.get("Bake_normal")
            # Set up UVs
            bpy.context.view_layer.objects.active = mbj_list[i_obj]
            bpy.ops.object.select_linked(type='MATERIAL')
            for selected in bpy.context.selected_objects:
                if selected not in obj_list:
                    selected.select_set(False)
            original_area = bpy.context.area.type
            bpy.context.area.ui_type = 'UV'
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.pack_islands(rotate=False, merge_overlap=True, margin=0.0)
            bpy.ops.transform.translate(value=(offset, 0, 0))
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.area.type = original_area
            offset += 1
            i_obj += 1

        # Reselect the original selection
        bpy.ops.object.select_all(action='DESELECT')
        for obj in obj_list:
            obj.select_set(True)

        # Pack all UVs together
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(rotate=rotation_toggle, merge_overlap=True, margin=0.0)
        bpy.ops.object.mode_set(mode='OBJECT')
        # Save render settings
        render_engine = bpy.context.scene.render.engine
        render_samples = bpy.context.scene.cycles.samples
        render_direct = bpy.context.scene.render.bake.use_pass_direct
        render_indirect = bpy.context.scene.render.bake.use_pass_indirect
        render_colour = bpy.context.scene.render.bake.use_pass_color
        render__margin = bpy.context.scene.render.bake.margin
        # Change render settings and bake textures
        bpy.context.scene.render.engine = 'CYCLES'
        bpy.context.scene.cycles.samples = 1
        use_pass = bpy.context.scene.render.bake.use_pass_direct
        bpy.context.scene.cycles.bake_type = 'NORMAL'
        bpy.context.scene.render.bake.normal_g = 'NEG_Y'
        bpy.context.scene.cycles.bake_type = 'DIFFUSE'
        bpy.context.scene.render.bake.use_pass_direct = False
        bpy.context.scene.render.bake.use_pass_indirect = False
        bpy.context.scene.render.bake.use_pass_color = True
        bpy.context.scene.render.bake.margin = 0

        if bake_type in ('Diffuse','Both'):
            bpy.ops.object.bake(type='DIFFUSE')
        if bake_type in ('Normal','Both'):
            for mat in mat_list:
                bake_flag = 0
                nodes = mat.node_tree.nodes
                normal_test = nodes.get("Normal Bake")
                if normal_test != None:
                    nodes.active = normal_test
                    normal_test.select = True
                    bake_flag = 1
            if bake_flag == 1:
                bpy.ops.object.bake(type='NORMAL')

        # If on, create material for the bake textures if one doesn't already exist
        material = bpy.data.materials.get('Bake Material')
        if material == None:
            if create_material:
                material = bpy.data.materials.new('Bake Material')
                # Setup material mode and keywords
                material.use_nodes = True
                material.preview_render_type = 'FLAT'
                material.blend_method = 'CLIP'
                material.use_backface_culling = True
                nodes = material.node_tree.nodes
                new_link = material.node_tree.links.new
                # Defining nodes
                shader_node = material.node_tree.nodes["Principled BSDF"]
                shader_node.inputs['Metallic'].default_value = 0
                texture_image = nodes.new("ShaderNodeTexImage")
                texture_image.name = 'Diffuse Texture'
                texture_image.location = (-506, 444)
                texture_image.image = bpy.data.images.get("Bake_texture")
                # Linking nodes: colour -> shader; alpha -> shader
                new_link(shader_node.inputs[0], texture_image.outputs[0])
                new_link(shader_node.inputs[4], texture_image.outputs[1])
                if bake_type in ('Normal', 'Both'):
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
                    normal_image.image = bpy.data.images.get("Bake_normal")
                    normal_image.image.colorspace_settings.name = 'Non-Color'
                    # Linking nodes: normal -> curves -> normal map -> shader
                    new_link(shader_node.inputs[5], normal_map.outputs[0])
                    new_link(rgb_curve.inputs[1], normal_image.outputs[0])
                    new_link(normal_map.inputs[1], rgb_curve.outputs[0])
        else:
            nodes = material.node_tree.nodes
            texture_image = nodes.get("Diffuse Texture")
            texture_image.image = bpy.data.images.get("Bake_texture")

        # Revert render settings
        bpy.context.scene.render.engine = render_engine
        bpy.context.scene.cycles.samples = render_samples
        bpy.context.scene.render.bake.use_pass_direct = render_direct
        bpy.context.scene.render.bake.use_pass_indirect = render_indirect
        bpy.context.scene.render.bake.use_pass_color = render_colour
        bpy.context.scene.render.bake.margin = render__margin
        # Set the main layer back to active layer
        for obj in bpy.context.selected_objects:
            obj.data.uv_layers[0].active = True