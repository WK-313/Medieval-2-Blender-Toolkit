import bpy
from pathlib import Path
script_folder = Path(__file__).parent

def render_setup():
    bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[0]
    #Create camera and controller
    bpy.context.scene.render.resolution_x = 480
    bpy.context.scene.render.resolution_y = 640
    bpy.context.scene.render.film_transparent = True
    bpy.context.scene.render.image_settings.file_format = 'TARGA'
    bpy.ops.object.camera_add(enter_editmode=False, align='VIEW', location=(0.016065, 2.67329, 1.633482), rotation=(1.4926, 0.0133, 3.146288))
    camera = bpy.context.object
    camera.data.ortho_scale = 1.2
    camera.data.type = 'ORTHO'
    camera.data.show_background_images = True
    reference = bpy.data.images.load(filepath=str(script_folder)+"/images/unit card sample transparent.png")
    background = camera.data.background_images.new()
    background.image = reference
    camera.data.background_images[0].display_depth = 'FRONT'
    camera.data.background_images[0].alpha = 1
    camera.lock_location[1] = True
    camera.lock_location[2] = True
    bpy.ops.object.empty_add(type='ARROWS', align='WORLD', location=(0, 1.63087, 2.0792))
    empty = bpy.context.object
    empty.scale=(0.229259, 0.229259, 0.229259)
    empty.name = "Camera Controller"
    empty.lock_location[1] = True
    empty.lock_location[2] = True
    
    #Create camera driver
    fcurve = camera.driver_add('location', 0)
    drv = fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = "int(var)  if (int(var) % 2 == 0) else int(var) -1"
    variable = drv.variables.new()
    variable.name = "var"
    variable.type = 'TRANSFORMS'
    variable.targets[0].id = bpy.data.objects[empty.name]
    variable.targets[0].transform_type = 'LOC_X'
    variable.targets[0].transform_space = 'WORLD_SPACE'
    controller = empty
    
    #Create compositor nodes
    if not bpy.context.scene.use_nodes:
        bpy.context.scene.use_nodes = True
    compositor = bpy.context.scene.node_tree
    compositor.nodes.clear()
    new_link = compositor.links.new
    # Rescaling
    render_input = compositor.nodes.new(type="CompositorNodeRLayers")
    render_input.location = (-950, 342)
    blur = compositor.nodes.new(type="CompositorNodeBilateralblur")
    blur.location = (-650, 342)
    blur.iterations = 2
    blur.sigma_color = 3
    blur.sigma_space = 2.5
    transform = compositor.nodes.new(type="CompositorNodeTransform")
    transform.location = (-450, 342)
    transform.inputs[4].default_value = 0.1
    # Layout and links
    frame1 = compositor.nodes.new(type="NodeFrame")
    frame1.label = "rescale"
    frame1.use_custom_color = True
    frame1.color = (0.458027, 0.608, 0.308053)
    render_input.parent = frame1
    blur.parent = frame1
    transform.parent = frame1
    new_link(blur.inputs[0], render_input.outputs[0])
    new_link(transform.inputs[0], blur.outputs[0])
    # Colour adjust
    brightness = compositor.nodes.new(type="CompositorNodeBrightContrast")
    brightness.location = (-230, 342)
    brightness.inputs[1].default_value = 0
    gamma = compositor.nodes.new(type="CompositorNodeGamma")
    gamma.location = (-30, 342)
    gamma.inputs[1].default_value = 1
    exposure = compositor.nodes.new(type="CompositorNodeExposure")
    exposure.location = (170, 342)
    exposure.inputs[1].default_value = 0
    rgb_curve = compositor.nodes.new(type="CompositorNodeCurveRGB")
    rgb_curve.location = (370, 342)
    # Layout and links
    frame2 = compositor.nodes.new(type="NodeFrame")
    frame2.label = "Colour Adjust"
    frame2.use_custom_color = True
    frame2.color = (0.320128, 0.33139, 0.608)
    brightness.parent = frame2
    gamma.parent = frame2
    exposure.parent = frame2
    rgb_curve.parent = frame2
    new_link(brightness.inputs[0], transform.outputs[0])
    new_link(gamma.inputs[0], brightness.outputs[0])
    new_link(exposure.inputs[0], gamma.outputs[0])
    new_link(rgb_curve.inputs[1], exposure.outputs[0])
    # Sharpen
    diamond = compositor.nodes.new(type="CompositorNodeFilter")
    diamond.location = (650, 342)
    diamond.filter_type = 'SHARPEN_DIAMOND'
    diamond.inputs[0].default_value = 0.2
    hue = compositor.nodes.new(type="CompositorNodeHueSat")
    hue.location = (810, 342)
    # Layout and links
    frame3 = compositor.nodes.new(type="NodeFrame")
    frame3.label = "Sharpen"
    frame3.use_custom_color = True
    frame3.color = (0.452784, 0.645006, 0.653327)
    diamond.parent = frame3
    hue.parent = frame3
    new_link(diamond.inputs[1], rgb_curve.outputs[0])
    new_link(hue.inputs[0], diamond.outputs[0])
    # Border size
    reference = compositor.nodes.new(type="CompositorNodeImage")
    reference.location = (1040, 342)
    background = bpy.data.images.load(filepath=str(script_folder)+"/images/unit card sample.png")
    reference.image = background
    alpha = compositor.nodes.new(type="CompositorNodeAlphaOver")
    alpha.location = (1220, 342)
    alpha.premul = 0
    alpha.inputs[0].default_value = 1
    mix = compositor.nodes.new(type="CompositorNodeMixRGB")
    mix.location = (1380, 342)
    # Layout and links
    frame4 = compositor.nodes.new(type="NodeFrame")
    frame4.label = "Border Size"
    frame4.use_custom_color = True
    frame4.color = (0.473327, 0.119403, 0.137491)
    reference.parent = frame4
    alpha.parent = frame4
    mix.parent = frame4
    new_link(alpha.inputs[1], reference.outputs[0])
    new_link(alpha.inputs[2], hue.outputs[0])
    new_link(mix.inputs[1], alpha.outputs[0])
    new_link(mix.inputs[2], hue.outputs[0])
    # Final + Preview
    output = compositor.nodes.new(type="CompositorNodeOutputFile")
    output.location = (1600, 342)
    view = compositor.nodes.new(type="CompositorNodeViewer")
    view.location = (1600, 222)
    # Layout and links
    frame5 = compositor.nodes.new(type="NodeFrame")
    frame5.label = "Final + Preview"
    output.parent = frame5
    view.parent = frame5
    new_link(output.inputs[0], mix.outputs[0])
    new_link(view.inputs[0], mix.outputs[0])
