import bpy
import re
from pathlib import Path
from . import recurlayercollection
from .importer import principledNode
from .task_writer import settlementTaskAppend, settlementTaskRun
script_folder = Path(__file__).parent.parent


def worldPath(settlement_folder, world, suffix='.glb'):
    """Where IWTE puts the converted world, under the settlements output folder.

    The world is stored relative to the mod - `data\\settlements\\...` - but
    settlement_pkgs.json written before the reader moved to Path joins has a
    LEADING separator on it, and joining an absolute-looking path onto a folder
    throws the folder away. So the separators are stripped before the join and
    an old scan keeps working without being redone.
    """
    return Path(settlement_folder)/Path(str(world).replace('.world', suffix).lstrip('\\/'))


def settlementChecker(settlement_folder, world, name):
    glb_path = worldPath(settlement_folder, world)
    if not bpy.context.scene.med2_toolkit_settlements.use_existing_settlement:
        print("Appending to the task file: %s" % world)
        settlementTaskAppend(world)
        settlementTaskRun()
        return glb_path.exists()
    if not glb_path.exists():
        print("World '%s' not found in folder %s." % (name, settlement_folder))
        print("Appending to the task file")
        settlementTaskAppend(world)
        settlementTaskRun()
    return glb_path.exists()


def settlementImporter(settlement_folder, name, world):
    settlement_root = Path(settlement_folder)
    if not settlement_root.exists():
        return('Settlement folder not found: %s' % settlement_root)

    glb_path = worldPath(settlement_root, world)
    if not settlementChecker(settlement_root, world, name):
        print("Files %s not found in folder %s." % (world, settlement_root))
        return('Files from %s not found: %s' % (settlement_root, glb_path.name))

    recurlayercollection.findCollection(name.replace('.Worldpkgdesc', ''))
    bpy.ops.import_scene.gltf(filepath=str(glb_path))
    imported = bpy.context.selected_objects
    if bpy.context.scene.med2_toolkit_settlements.hide_complexes:
        for obj in imported:
            if 'complex_' in obj.name.lower():
                obj.hide_render = True
                obj.hide_set(True)
    bpy.ops.view3d.view_all(center=False)
    print('Material setup starting')
    #Setup materials
    texture_path = settlement_root/'data'/'blockset'/'textures'
    for material in bpy.data.materials:
        texture_name = re.sub(r"_dds.*", ".dds", material.name)
        texture_file = texture_path/texture_name
        if not texture_file.exists():
            print("Texture %s not found for material %s in folder %s." % (texture_name, material.name, texture_path))
            continue

        if material.node_tree is None:
            material.use_nodes = True

        # a second settlement in the same scene keeps the first one's materials,
        # so anything already textured is left alone. This used to `continue` the
        # node loop rather than the material one, which did nothing at all
        if any(node.type == 'TEX_IMAGE' for node in material.node_tree.nodes):
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
        texture_image.image = bpy.data.images.load(str(texture_file))
        #Linking nodes: colour -> shader
        new_link(shader_node.inputs[0], texture_image.outputs[0])
    print('Material setup finished')
    # only when the import came from a 3D view - the operator is F3 searchable,
    # and a settlement imported from anywhere else must not take the addon down
    space = bpy.context.space_data
    if space is not None and getattr(space, 'type', '') == 'VIEW_3D':
        space.shading.light = 'FLAT'
        space.shading.color_type = 'TEXTURE'
    return('Finished')
