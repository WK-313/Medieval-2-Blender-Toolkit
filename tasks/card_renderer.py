"""Unit card / unit info card rendering.

Ported from the v0.9.x toolkit's "Unit Cards" panel. Two things changed:

* Blender 5 dropped `Scene.node_tree` in favour of `Scene.compositing_node_group`,
  removed the Gamma and Mix RGB compositor nodes, turned the Filter node's
  `filter_type` into a menu socket, and - most importantly - the compositor output
  is now always the scene render resolution. The old setup rendered at 480x660,
  scaled the image to 10% with a Transform node and let an Alpha Over against a
  48x66 (fully transparent) reference image crop the canvas down to card size.
  The rescale half of that still works and is what the graph does: the render is
  a whole multiple of the card, the Transform takes it back to card size, and
  everything after it - the sharpen in particular - therefore acts at final card
  pixel size, which is the look the old .blend files have. The canvas half does
  not: Transform, Alpha Over and the Crop node all hand back an image the size of
  the render whatever they are fed, so the scaled-down card sits in the middle of
  a full-size transparent frame and the crop out of it is done in saveCard.
* Models and textures no longer have to be converted by hand. The card import
  reuses the same IWTE extraction the Unit Import workmode uses (unitChecker ->
  task file -> IWTE -> .glb + .dds), so pointing the toolkit at a mod is enough.
"""

import os
import bpy
import math
import shutil
import numpy as np
from pathlib import Path

from mathutils import Vector

from ..directories import readJsonCached
from .control_rig import controlRigOf, isControlRig
from .recurlayercollection import linkBeside, recurLayerCollection
from .unit_groups import createGroupControlRigs, groupParts, groupRoot

script_folder = Path(__file__).parent.parent
CARD_FOLDER = script_folder/'cards'
ASSET_FOLDER = script_folder/'assets'

COMPOSITOR_NAME = "Medieval 2 Unit Cards"
# Bumped whenever buildCompositor's graph changes, so a scene carrying a group
# from an older toolkit gets rebuilt instead of silently keeping the old chain.
COMPOSITOR_VERSION_TAG = "med2_compositor_version"
COMPOSITOR_VERSION = 3
# 480x660 - the game's own card UI chrome (experience chevrons, the numbers, the
# weapon and shield icons), so the framing can be checked against what the
# interface leaves visible. It is a 10x 48x66 image over a 48x64 card, i.e. two
# card pixels taller than the card, and those two rows belong BELOW the card -
# see guideOffset.
CAMERA_GUIDE = "Camera Preview.png"
GUIDE_SIZE = (48, 66)
# The guide that shipped before the camera preview. 480x640, the card's own
# shape, and it is what an older install still has on disk.
LEGACY_CAMERA_GUIDE = "unit card guide.png"
LEGACY_GUIDE_SIZE = (48, 64)
# The rescale Transform, by name, so the render settings can retune it without
# rebuilding the whole graph and the full-size and HD passes can switch it off.
RESCALE_NODE = "Card Rescale"
# The smoothing Bilateral Blur, likewise - the HD pass switches it off.
BLUR_NODE = "Card Smoothing"

# Camera pose the old card setup used, kept unchanged: an orthographic camera
# looking at the unit from +Y at roughly chest height, framed the way a Medieval 2
# unit card is. Only X is ever moved - that is how the renderer steps from one
# unit to the next.
CAMERA_LOCATION = (0.016065, 2.67329, 1.633482)
CAMERA_ROTATION = (1.4926, 0.0133, 3.146288)
CAMERA_ORTHO_SCALE = 1.2

# Some skeletons import sunk into the ground: the model's own z offset lands the
# unit half above and half below z=0. The card camera sits at a fixed height, so
# that unit is framed low - head cropped, legs in nothing. The fix is to set it
# down on the floor: lift it by exactly how far its lowest point is below z=0.
#
# How far below a unit has to reach before it counts as sunk (a boot sole a hair
# under the floor is not), and how much of it may be down there before it is
# something parked below the scene rather than a unit standing in the floor.
SUNK_DEPTH = 0.05
MAX_SUNK_SHARE = 0.75

# card type -> (width, height, ui subfolder, file name pattern, EDU directory key)
CARD_TYPES = {
    'unit_card':       (48, 64, 'units', '#%s.tga', 'Unit Card'),
    'unit_card_large': (68, 90, 'units', '#%s.tga', 'Unit Card'),
    'info_card':       (180, 230, 'unit_info', '%s_info.tga', 'Info Card'),
}

CARD_TYPE_ITEMS = [
    ('unit_card', "Unit Card (48x64)", "Battle UI unit card, written to units/<dir>/#<unit>.tga"),
    ('unit_card_large', "Unit Card (68x90)", "Larger unit card some mods use, written to units/<dir>/#<unit>.tga"),
    ('info_card', "Info Card (180x230)", "Unit info panel image, written to unit_info/<dir>/<unit>_info.tga"),
]


# Subfolder the untouched full-size render goes into, next to the finished card.
# The game only ever looks for its own .tga, so an extra folder is harmless.
FULL_SIZE_FOLDER = "full"
# Subfolder for the second, HD pass - a picture of the unit rather than a card,
# so it is kept apart from the card-sized renders.
HD_FOLDER = "hd"


def cardResolution(settings):
    """Final card size in pixels, before supersampling."""
    if settings.custom_size:
        return settings.card_width, settings.card_height
    return CARD_TYPES[settings.card_type][:2]


# The HD pass is a whole multiple of the 48x64 unit card rather than a 16:9
# screen size, so it frames exactly what the card frames - see hdOrthoScale, which
# on a 48x64 card then leaves the camera alone entirely.
HD_BASE = (48, 64)
HD_PRESETS = [
    ('10', "10x", "480 x 640"),
    ('20', "20x", "960 x 1280"),
    ('30', "30x", "1440 x 1920"),
    ('40', "40x", "1920 x 2560"),
]
HD_DEFAULT_MULTIPLE = 20


def hdMultiple(settings):
    try:
        return int(settings.hd_preset)
    except (TypeError, ValueError):
        return HD_DEFAULT_MULTIPLE


def hdResolution(settings):
    """Pixel size of the HD pass: 48x64 times the chosen multiple."""
    multiple = hdMultiple(settings)
    return HD_BASE[0]*multiple, HD_BASE[1]*multiple


def hdOrthoScale(settings, width, height):
    """Ortho scale that keeps everything the card frames inside the HD frame.

    The card cameras are orthographic and Blender's ortho scale always spans the
    LONGER side of the render, so an HD frame of a different shape re-frames the
    shot: a wider one would span the card's framing across the width and crop the
    unit's head and feet, a narrower one would clip its sides.

    So the scale is solved for instead. The card frames card_zoom across its own
    longer side, which is w_card x h_card world units; the HD frame has to be at
    least that big on both axes, and the larger of the two requirements wins. The
    unit is then never smaller in frame than it is on the card - only more of the
    scene around it shows.
    """
    card_width, card_height = cardResolution(settings)
    card_long = max(card_width, card_height)
    # what the card actually sees, in world units
    frame_w = settings.card_zoom * card_width / float(card_long)
    frame_h = settings.card_zoom * card_height / float(card_long)
    hd_long = float(max(width, height))
    return max(frame_h * hd_long / height, frame_w * hd_long / width)




def cardOutputParts(settings):
    """(ui subfolder, file name pattern, EDU directory key) for the card type."""
    return CARD_TYPES[settings.card_type][2:]


#   -----------------  #
#   Scene / card setup  #
#   -----------------  #

def guideImage():
    """(image, its nominal card size) for the framing overlay shown through the
    camera, or (None, None). Optional - the setup still works without it, the
    user just loses the on-screen guide.

    The older guide in cards/ is the fallback, so an install that has not picked
    up the camera preview asset still gets an overlay rather than none at all.
    """
    for folder, name, size in ((ASSET_FOLDER, CAMERA_GUIDE, GUIDE_SIZE),
                               (CARD_FOLDER, LEGACY_CAMERA_GUIDE, LEGACY_GUIDE_SIZE)):
        image = bpy.data.images.get(name)
        if image is not None:
            return image, size
        guide_path = folder/name
        if guide_path.exists():
            return bpy.data.images.load(str(guide_path)), size
    return None, None


def guideOffset(guide_size, card_size):
    """How far down the guide has to slide, as a fraction of the camera frame.

    The camera preview is 48x66 and the unit card is 48x64, so the guide is two
    card pixels taller than what is rendered. 'CROP' matches their widths and
    leaves the overshoot split evenly above and below, which puts the game's
    chrome one pixel low; the card is the TOP of the guide and the spare two
    rows hang off the bottom. So the guide is nudged down by half the overshoot,
    which is what closes that gap.

    Everything is derived from the two sizes rather than hardcoded, so a guide
    the same shape as its card (the legacy one, or a custom 48x66 card) comes
    out at zero and nothing moves.
    """
    guide_width, guide_height = guide_size
    card_width, card_height = card_size
    if not all((guide_width, guide_height, card_width, card_height)):
        return 0.0
    # 'CROP' scales the guide up until it covers the frame on both axes
    cover = max(card_width/float(guide_width), card_height/float(guide_height))
    overshoot = guide_height*cover - card_height
    # in camera view an offset of 1.0 is a whole frame, so half the overshoot in
    # card pixels is (overshoot/2)/card_height of one
    return -(overshoot/2.0)/card_height


def applyCameraGuide(camera_data, card_size):
    """Put the framing overlay on a card camera, aligned to the card frame."""
    guide, guide_size = guideImage()
    if guide is None:
        return False
    background = camera_data.background_images[0] if camera_data.background_images \
        else camera_data.background_images.new()
    background.image = guide
    background.display_depth = 'FRONT'
    background.alpha = 1
    # not 'STRETCH' (the default): that squashes a 48x66 guide onto a 48x64 card
    # and the chrome no longer lines up with anything
    background.frame_method = 'CROP'
    background.offset = (0.0, guideOffset(guide_size, card_size))
    return True


# Marker properties: a card camera and its sun carry the unit they belong to, so
# the renderer can rebuild its queue from the scene alone.
CAMERA_TAG = "med2_card_unit"
FACTION_TAG = "med2_card_faction"
SUN_TAG = "med2_card_sun"
# The rig the camera was made for, by name. The renderer needs it to hide every
# other object while that unit is being rendered.
TARGET_TAG = "med2_card_target"
# Card folder override, set on the rig rather than the camera so it survives
# deleting and rebuilding the cameras. Comma separated list of faction codenames,
# i.e. the ui/units subfolders the card is written into; empty means the EDU's
# own card_pic_dir / info_pic_dir decides, as before.
FOLDER_TAG = "med2_card_folders"
# Mercenaries have no faction entry in descr_sm_factions, but they do have a card
# folder - and the game spells it DIFFERENTLY for the two card types: the unit card
# goes in ui\units\mercs, the info card in ui\unit_info\merc. Both spellings ship
# with vanilla and mods follow them (DaC files 908 of its 910 units that way), so
# one constant cannot serve both - it put every unit card in units\merc, a folder
# the game never reads.
MERC_FOLDERS = {'units': "mercs", 'unit_info': "merc"}
# Either spelling means "the mercenary folder" when one is read back off a rig.
MERC_FOLDER_NAMES = frozenset(MERC_FOLDERS.values())


def mercFolder(subfolder):
    """The mercenary folder name under a ui subfolder ('units' / 'unit_info')."""
    return MERC_FOLDERS.get(subfolder, "mercs")


def normalizeMercFolders(folders, subfolder):
    """Pinned folders with the mercenary one respelled for the card type in hand.

    A pin is ONE list of folder names shared by both card types, so a unit pinned
    to 'mercs' has to write its info card into 'merc' all the same - and a pin
    written before this rule existed can hold either spelling. Every other folder
    is left exactly as it was pinned; only the mercenary one has two names.
    """
    merc = mercFolder(subfolder)
    normalized = []
    for name in folders:
        name = merc if name in MERC_FOLDER_NAMES else name
        if name not in normalized:
            normalized.append(name)
    return normalized


def cardFolders(target):
    """The folders a unit's card was pinned to by hand, or []."""
    if target is None:
        return []
    return [name for name in str(target.get(FOLDER_TAG, "")).split(',') if name]


def setCardFolders(target, folders):
    """Pin a unit's card to `folders`. An empty list clears the override."""
    if folders:
        target[FOLDER_TAG] = ','.join(folders)
    elif FOLDER_TAG in target:
        del target[FOLDER_TAG]


def unitOwnershipFolders(unit):
    """Every faction codename that owns an EDU unit, in the EDU's own order.

    The 'ownership' line rather than the era lines: a unit's card belongs in the
    folder of every faction that can ever field it, which is what ownership
    lists. The era lines are a subset of it.
    """
    if unit is None:
        return []
    owners = unit.get('Owners') or {}
    folders = []
    for faction_id in owners.get('ownership') or []:
        name = str(faction_id).strip()
        if name and name not in folders:
            folders.append(name)
    return folders


def defaultCardFolders(unit, faction, dir_key, subfolder):
    """Where a unit's card goes when nothing has been pinned by hand.

    Three cases, in order:

    - a rig that is not an EDU unit at all - a custom armature someone built
      themselves - has no ownership to read, and a hand-made unit is nearly
      always a mercenary, so it defaults to the mercenary folder of the card type
      being rendered rather than to whichever faction happened to be selected in
      the panel.
    - a unit whose EDU names its own card_pic_dir / info_pic_dir keeps that: it
      is an explicit instruction and the game obeys it over ownership.
    - anything else goes to every faction that owns it, so a unit several
      factions can field gets its card in each of their folders.
    """
    if unit is None:
        return [mercFolder(subfolder)]
    card_directory = unit.get(dir_key, 'faction')
    if card_directory not in ('', 'faction'):
        return [card_directory]
    return unitOwnershipFolders(unit) or [faction]

SUN_STRENGTH = 4.0
# A point lamp is an inverse-square falloff at card distance, so it needs to be
# orders of magnitude stronger than a sun to read the same.
POINT_STRENGTH = 500.0

CARD_LIGHT_TYPES = [
    ('SUN',   "Sun",   "Directional light, aimed the same way as the camera. Even across the whole unit"),
    ('POINT', "Point", "Point lamp at the camera. Falls off with distance, so it picks out whatever is nearest"),
]


def defaultLightStrength(light_type):
    return POINT_STRENGTH if light_type == 'POINT' else SUN_STRENGTH


def cardCameras(scene):
    """Every card camera in the scene, left to right."""
    cameras = [obj for obj in scene.objects if obj.type == 'CAMERA' and CAMERA_TAG in obj]
    cameras.sort(key=lambda obj: obj.matrix_world.translation.x)
    return cameras


def cardSuns(scene):
    return [obj for obj in scene.objects if obj.type == 'LIGHT' and SUN_TAG in obj]


def cameraName(unit_id):
    return "%s Card Cam" % unit_id


def cardCamera(unit_id=None):
    """A card camera by unit, or the first one in the file."""
    if unit_id is not None:
        camera = bpy.data.objects.get(cameraName(unit_id))
        if camera is not None and camera.type == 'CAMERA':
            return camera
        return None
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and CAMERA_TAG in obj:
            return obj
    return None


def cameraTarget(scene, camera):
    """The rig a card camera was made for, or None.

    Cameras built before TARGET_TAG existed only know their unit id, so they fall
    back to the armatures sharing their collection - which is where linkBeside
    puts a card camera - picking the one the camera is actually parked in front
    of. A control rig is only used when nothing else is there, since the mesh
    hangs off the Med2 skeleton it drives, not off the controller.
    """
    name = camera.get(TARGET_TAG, "")
    if name:
        target = scene.objects.get(name)
        if target is not None:
            return target
    candidates = []
    for collection in camera.users_collection:
        for obj in collection.objects:
            if obj.type == 'ARMATURE' and obj.name in scene.objects and obj not in candidates:
                candidates.append(obj)
    if not candidates:
        return None
    deform = [obj for obj in candidates if not isControlRig(obj)] or candidates
    # createCardCamera slides the camera to target.x + CAMERA_LOCATION[0], so the
    # rig it frames is the one nearest that X - this is what keeps a collection
    # holding several units from handing back the wrong one
    aimed_at = camera.matrix_world.translation.x - CAMERA_LOCATION[0]
    return min(deform, key=lambda obj: abs(obj.matrix_world.translation.x - aimed_at))


def createCardCamera(context, unit_id, faction, target, add_sun=True, light_strength=SUN_STRENGTH,
                     ortho_scale=CAMERA_ORTHO_SCALE, light_type='SUN'):
    """Build (or refresh) the camera - and its sun - that frames one unit.

    Every camera is the same pose slid along X onto its unit, which is the
    framing the game's cards use. Each one keeps its own sun so a single unit can
    be relit without touching the rest; the renderer hides all the other suns
    while that unit is being rendered, because a sun lights the whole scene and
    fifty of them pointing the same way would blow every card out.
    """
    name = cameraName(unit_id)
    camera = bpy.data.objects.get(name)
    created = False
    if camera is None or camera.type != 'CAMERA':
        camera_data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, camera_data)
        context.scene.collection.objects.link(camera)
        created = True
    # the camera belongs with its unit, not loose in the scene collection - and
    # refreshing re-homes cameras made before this was the rule
    linkBeside(camera, target, context)
    camera[CAMERA_TAG] = unit_id
    camera[FACTION_TAG] = faction
    camera[TARGET_TAG] = target.name
    camera.rotation_euler = CAMERA_ROTATION
    camera.location = (
        target.matrix_world.translation.x + CAMERA_LOCATION[0],
        CAMERA_LOCATION[1],
        CAMERA_LOCATION[2],
    )
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = ortho_scale
    # applied on a refresh too, not just on a new camera: one built under an
    # earlier card size is still carrying that size's guide alignment, and a
    # Refresh is how the user is expected to repair it
    applyCameraGuide(camera.data, cardResolution(context.scene.med2_toolkit_cards))
    camera.data.show_background_images = True

    sun = next((child for child in camera.children if child.type == 'LIGHT' and SUN_TAG in child), None)
    if add_sun:
        if sun is None:
            sun_data = bpy.data.lights.new(name + " Sun", type=light_type)
            sun = bpy.data.objects.new(name + " Sun", sun_data)
            context.scene.collection.objects.link(sun)
            sun.parent = camera
            sun.rotation_euler = (0, 0, 0)  # parented, so it inherits the camera's aim
        linkBeside(sun, target, context)
        sun[SUN_TAG] = unit_id
        sun.data.type = light_type
        sun.data.energy = light_strength
        # sits on the camera, so it lights every unit the same way however far
        # along X that unit sits
        sun.location = (0.0, 0.0, 0.0)
    elif sun is not None:
        bpy.data.objects.remove(sun, do_unlink=True)
    return camera, created


def deleteCardCameras(scene):
    """Remove every card camera and its sun. Returns how many cameras went."""
    doomed = cardCameras(scene)
    count = len(doomed)
    for camera in doomed:
        for child in list(camera.children):
            if SUN_TAG in child:
                bpy.data.objects.remove(child, do_unlink=True)
        bpy.data.objects.remove(camera, do_unlink=True)
    for sun in cardSuns(scene):
        bpy.data.objects.remove(sun, do_unlink=True)
    return count


def frameNode(nodes, label, colour, members):
    frame = nodes.new(type="NodeFrame")
    frame.label = label
    frame.use_custom_color = True
    frame.color = colour
    for node in members:
        node.parent = frame
    return frame


def buildCompositor(group, scene, scale=1.0):
    """Rebuild the card compositor graph inside `group`.

    The chain from the v0.9.x card .blend files: rescale, colour adjust, sharpen.
    `scale` is what the rescale Transform is set to - 1/supersampling, so the
    render comes back out at card size and the sharpen after it therefore bites
    at final card pixel size, which is what gives those cards their look.

    The old "Border Size" frame - an Image node holding a fully transparent 48x66
    reference (assets/Empty Preview.png), an Alpha Over and a Mix - is not
    reproduced, which is why that image is bundled but unused. It carried nothing
    visual; it existed purely to force the compositor canvas down to card size,
    and in Blender 5 no node can do that any more (Transform, Alpha Over and Crop
    all hand back an image the size of the render). saveCard cuts the card out of
    the middle of the full-size frame instead, from the card size directly, so
    the border it produces is exact whatever the card is set to.
    """
    nodes = group.nodes
    new_link = group.links.new
    nodes.clear()
    group.interface.clear()
    group.interface.new_socket(name="Image", in_out='OUTPUT', socket_type='NodeSocketColor')

    render_input = nodes.new(type="CompositorNodeRLayers")
    render_input.location = (-1350, 342)
    render_input.scene = scene

    # Rescale: smooth, then take the render down to card size
    blur = nodes.new(type="CompositorNodeBilateralblur")
    blur.name = BLUR_NODE
    blur.location = (-1150, 342)
    # the old node's iterations/sigma_color/sigma_space settings became these two
    # sockets in Blender 5
    blur.inputs['Size'].default_value = 5
    blur.inputs['Threshold'].default_value = 1.0
    rescale = nodes.new(type="CompositorNodeTransform")
    rescale.name = RESCALE_NODE
    rescale.label = "Rescale"
    rescale.location = (-950, 342)
    rescale.inputs['X'].default_value = 0.0
    rescale.inputs['Y'].default_value = 0.0
    rescale.inputs['Angle'].default_value = 0.0
    rescale.inputs['Scale'].default_value = scale
    # Nearest, as the old files had it: the card is 48 pixels across and a
    # filtered downscale turns the armour detail into mush
    rescale.inputs['Interpolation'].default_value = 'Nearest'
    new_link(blur.inputs['Image'], render_input.outputs['Image'])
    new_link(rescale.inputs['Image'], blur.outputs['Image'])
    frameNode(nodes, "rescale", (0.458027, 0.608, 0.308053), [blur, rescale])

    # Colour adjust. Brightness/Contrast is bracketed by the two Alpha Convert
    # nodes so it works on straight alpha - on premultiplied pixels it drags the
    # colour of the transparent background into the silhouette's edge.
    to_straight = nodes.new(type="CompositorNodePremulKey")
    to_straight.location = (-750, 342)
    to_straight.inputs['Type'].default_value = 'To Straight'
    brightness = nodes.new(type="CompositorNodeBrightContrast")
    brightness.location = (-550, 342)
    brightness.inputs['Brightness'].default_value = 0
    brightness.inputs['Contrast'].default_value = 0
    to_premul = nodes.new(type="CompositorNodePremulKey")
    to_premul.location = (-350, 342)
    to_premul.inputs['Type'].default_value = 'To Premultiplied'
    # Blender 5 has no CompositorNodeGamma; the shader Gamma node works in a
    # compositor tree and is what the UI offers now
    gamma = nodes.new(type="ShaderNodeGamma")
    gamma.location = (-150, 342)
    gamma.inputs['Gamma'].default_value = 1
    exposure = nodes.new(type="CompositorNodeExposure")
    exposure.location = (50, 342)
    exposure.inputs['Exposure'].default_value = 0
    rgb_curve = nodes.new(type="CompositorNodeCurveRGB")
    rgb_curve.location = (250, 342)
    rgb_curve.mapping.tone = 'STANDARD'
    new_link(to_straight.inputs['Image'], rescale.outputs['Image'])
    new_link(brightness.inputs['Image'], to_straight.outputs['Image'])
    new_link(to_premul.inputs['Image'], brightness.outputs['Image'])
    new_link(gamma.inputs['Color'], to_premul.outputs['Image'])
    new_link(exposure.inputs['Image'], gamma.outputs['Color'])
    new_link(rgb_curve.inputs['Image'], exposure.outputs['Image'])
    frameNode(nodes, "Colour Adjust", (0.320128, 0.33139, 0.608),
              [to_straight, brightness, to_premul, gamma, exposure, rgb_curve])

    # Sharpen
    sharpen = nodes.new(type="CompositorNodeFilter")
    sharpen.location = (550, 342)
    # filter_type is a menu socket now, and its identifiers are the UI names
    sharpen.inputs['Type'].default_value = 'Diamond Sharpen'
    sharpen.inputs['Factor'].default_value = 0.2
    hue = nodes.new(type="CompositorNodeHueSat")
    hue.location = (750, 342)
    new_link(sharpen.inputs['Image'], rgb_curve.outputs['Image'])
    new_link(hue.inputs['Image'], sharpen.outputs['Image'])
    frameNode(nodes, "Sharpen", (0.452784, 0.645006, 0.653327), [sharpen, hue])

    # Final + Preview
    group_output = nodes.new(type="NodeGroupOutput")
    group_output.location = (1000, 342)
    viewer = nodes.new(type="CompositorNodeViewer")
    viewer.location = (1000, 222)
    new_link(group_output.inputs[0], hue.outputs['Image'])
    new_link(viewer.inputs['Image'], hue.outputs['Image'])
    frameNode(nodes, "Final + Preview", (0.3, 0.3, 0.3), [group_output, viewer])
    return group


#   --------  #
#   Line art  #
#   --------  #

# The tag holds the name of the collection the outline object covers.
LINE_ART_TAG = "med2_card_line_art"
LINE_ART_SUFFIX = " Line Art"
# Outline thickness in finished-card pixels. Measured off unit_card_sample.blend
# rather than guessed: that file's stroke is 0.0055 world units wide in a frame
# 1.21424 units across, i.e. 0.453% of the frame, which on a 66 pixel tall card
# is 0.30 of a pixel.
LINE_ART_THICKNESS = 0.30


def lineArtRadius(thickness, ortho_scale, card_size):
    """Modifier radius that draws a `thickness`-pixel line on the finished card.

    Two things about Grease Pencil v3 that the old formula here got wrong, both
    checked against unit_card_sample.blend:

    - `modifier.radius` is the whole stroke width, not half of it. Line Art
      writes radius/2 into each point and a point's radius is half its stroke,
      so the width comes back out as `radius`. There is no 0.5 to apply.
    - `ortho_scale` frames the LONGER side of the render, so a card pixel is
      ortho_scale/max(width, height) world units - not ortho_scale/width. On a
      48x64 card the old divisor was out by 64/48.
    """
    if card_size <= 0:
        return LINE_ART_THICKNESS
    return thickness * (ortho_scale/card_size)


def lineArtObjects(scene):
    return [obj for obj in scene.objects if obj.type == 'GREASEPENCIL' and LINE_ART_TAG in obj]


def lineArtObjectFor(scene, collection):
    for obj in lineArtObjects(scene):
        if obj.get(LINE_ART_TAG) == collection.name:
            return obj
    return None


# Pushes the strokes towards the camera so they are not z-fighting the surface
# they were traced from, which is what makes an outline show up in patches.
LINE_ART_DEPTH_OFFSET = 0.05
# Line art is computed inside the camera frame; a margin keeps the edges clean.
LINE_ART_OVERSCAN = 0.1


def applyLineArtSettings(modifier, layer_name, material, radius, collection, camera=None):
    """Replicates the working setup from the user's unit_card_sample.blend.

    Read straight off that file's modifier. The settings this replaced came from
    unit_card_blendfile.blend, which turned out not to be a card setup at all -
    its Line Art pointed at a collection holding nothing but the grease pencil
    object itself, so its flags had never actually drawn a unit.

    `camera` is accepted for callers that still pass one, and deliberately
    ignored - see below.
    """
    modifier.source_type = 'COLLECTION'
    modifier.source_collection = collection
    modifier.target_layer = layer_name
    modifier.target_material = material
    modifier.radius = radius
    modifier.opacity = 1.0
    modifier.overscan = LINE_ART_OVERSCAN
    modifier.stroke_depth_offset = LINE_ART_DEPTH_OFFSET
    # Follow the scene camera, exactly as the sample file does, and never pin a
    # custom one. Pinning was the bug: one outline object covers a whole
    # collection, so it could only ever be pinned to one unit's card camera,
    # while the renderer swaps scene.camera to a different card camera for every
    # unit in that collection. Line Art then computes the strokes from a camera
    # the render is not using, and because the card cameras are only ~0.9 units
    # wide and sit one per unit along X, every unit except the pinned one falls
    # outside that frame and gets no outline at all.
    modifier.use_custom_camera = False
    modifier.source_camera = None
    modifier.use_offset_towards_custom_camera = False
    # Edge types, as in the sample file: contour with no silhouette filtering,
    # plus material borders, edge marks and loose edges. 'INDIVIDUAL' filtering
    # was the other half of the patchy outline - it keeps only the edges that
    # silhouette an object on its own, which on a unit built from twenty
    # separate armour pieces throws most of the contour away.
    modifier.use_contour = True
    modifier.silhouette_filtering = 'NONE'
    modifier.use_crease = False
    modifier.crease_threshold = math.radians(180)
    modifier.use_intersection = False
    # material borders are what draw the panel lines inside the armour
    modifier.use_material = True
    modifier.use_edge_mark = True
    modifier.use_loose = True
    modifier.use_light_contour = False
    modifier.use_shadow = False
    modifier.use_overlap_edge_type_support = False
    # Geometry processing - all off in the sample. Back face culling in
    # particular costs strokes on these models, which carry their own dedicated
    # backface meshes (bodyback__body_backface and friends).
    modifier.use_edge_overlap = False
    modifier.use_object_instances = False
    modifier.use_clip_plane_boundaries = False
    modifier.use_crease_on_smooth = False
    modifier.use_crease_on_sharp = False
    modifier.use_back_face_culling = False
    modifier.use_face_mark_keep_contour = True
    # inert while the output vertex group is empty, but it is what the reference
    # file has, and Collection Line Art creates it the other way round
    modifier.use_output_vertex_group_match_by_name = False


def targetCollections(targets, scene):
    """The collections the card targets live in, in order, without duplicates."""
    collections = []
    for _unit_id, _faction, model in targets:
        for collection in (model.users_collection or (scene.collection,)):
            if collection not in collections:
                collections.append(collection)
    return collections


def lineArtRadiusFor(scene, thickness=None):
    settings = scene.med2_toolkit_cards
    card_width, card_height = cardResolution(settings)
    if thickness is None:
        thickness = settings.line_art_thickness
    # the ortho scale frames the longer side, so that is the side a card pixel
    # is measured against
    return lineArtRadius(thickness, settings.card_zoom, max(card_width, card_height))


def setupLineArtFor(context, collection, radius, camera=None):
    """Create (or refresh) the Line Art grease pencil covering one collection.
    Returns (object, created).

    New objects come from Blender's own Add > Grease Pencil > Collection Line
    Art, which builds the layer, the black material, the modifier and the
    Collection source in one go - it works on the ACTIVE collection, so that is
    switched around the call and put back afterwards. Only the settings that
    differ from Blender's defaults are then overridden.
    """
    scene = context.scene
    gpencil = lineArtObjectFor(scene, collection)
    created = False
    if gpencil is None:
        view_layer = context.view_layer
        previous_layer = view_layer.active_layer_collection
        layer_collection = recurLayerCollection(view_layer.layer_collection, collection.name)
        if layer_collection is None:
            return None, False
        view_layer.active_layer_collection = layer_collection
        previous_objects = set(bpy.data.objects)
        try:
            bpy.ops.object.grease_pencil_add(type='LINEART_COLLECTION', location=(0, 0, 0))
        except RuntimeError:
            return None, False
        finally:
            view_layer.active_layer_collection = previous_layer
        gpencil = next((obj for obj in bpy.data.objects if obj not in previous_objects), None)
        if gpencil is None:
            return None, False
        gpencil.name = collection.name + LINE_ART_SUFFIX
        gpencil.data.name = gpencil.name
        created = True
    gpencil[LINE_ART_TAG] = collection.name
    # 2D depth order draws the strokes in stroke order rather than depth-testing
    # them against the mesh they were traced from, which is what keeps an outline
    # whole. Show In Front is OFF in the sample file - the depth offset already
    # lifts the strokes clear of the surface, and drawing them in front as well
    # only lets an outline bleed through the geometry that should hide it.
    gpencil.show_in_front = False
    gpencil.data.stroke_depth_order = '2D'
    # it outlines this collection, so it belongs in it - Collection Line Art
    # already put it there, but an object that predates a re-organised scene
    # might have drifted
    for existing in list(gpencil.users_collection):
        if existing is not collection:
            existing.objects.unlink(gpencil)
    if gpencil.name not in collection.objects:
        collection.objects.link(gpencil)

    material = gpencil.data.materials[0] if gpencil.data.materials else None
    if material is None:
        material = bpy.data.materials.new("Card Outline")
        bpy.data.materials.create_gpencil_data(material)
        gpencil.data.materials.append(material)
    material.grease_pencil.color = (0.0, 0.0, 0.0, 1.0)
    if not gpencil.data.layers:
        gpencil.data.layers.new("Lines")

    modifier = next((m for m in gpencil.modifiers if m.type == 'LINEART'), None)
    if modifier is None:
        modifier = gpencil.modifiers.new("Line Art", 'LINEART')
    applyLineArtSettings(modifier, gpencil.data.layers[0].name, material, radius, collection, camera)
    return gpencil, created


def setupLineArt(context, targets, thickness=None):
    """One Line Art object per collection the card targets sit in, each set to
    Collection source so it only outlines its own unit. Returns results."""
    scene = context.scene
    if thickness is None:
        thickness = scene.med2_toolkit_cards.line_art_thickness
    radius = lineArtRadiusFor(scene, thickness)
    collections = targetCollections(targets, scene)
    if not collections:
        return [('WARNING', "No units to outline - tick some entries or select an armature")]
    created = 0
    refreshed = 0
    for collection in collections:
        # no camera: every outline follows scene.camera, which the renderer
        # already swaps to the right card camera for each unit it renders
        gpencil, is_new = setupLineArtFor(context, collection, radius)
        if gpencil is None:
            return [('ERROR', "Could not create the line art object for '%s'" % collection.name)]
        if is_new:
            created += 1
        else:
            refreshed += 1
    return [
        ('INFO', "Line art: %d outline object(s) created, %d refreshed, one per collection" % (created, refreshed)),
        ('INFO', "%.2f card pixel(s) thick (radius %.4f), contour + material borders + edge marks + loose edges"
                 % (thickness, radius)),
        ('INFO', "Outlines follow the scene camera, so one outline object covers every unit in its collection"),
    ]


def refreshLineArt(context):
    """Re-derive every outline's radius from the current card size and zoom.

    Also unpins any outline left pinned to a card camera by an older toolkit.
    Those outlines only ever drew the one unit their camera framed, so a scene
    saved before the fix would keep rendering blank outlines until it was set up
    again from scratch - repairing them here means a Refresh is enough.
    """
    radius = lineArtRadiusFor(context.scene)
    for gpencil in lineArtObjects(context.scene):
        gpencil.show_in_front = False
        for modifier in gpencil.modifiers:
            if modifier.type == 'LINEART':
                modifier.radius = radius
                if modifier.use_custom_camera:
                    modifier.use_custom_camera = False
                    modifier.source_camera = None


def removeLineArt(scene):
    """Delete every card line art object. Returns how many went."""
    doomed = lineArtObjects(scene)
    for gpencil in doomed:
        bpy.data.objects.remove(gpencil, do_unlink=True)
    return len(doomed)


def rescaleNode(group):
    """The rescale Transform of a card compositor group, or None."""
    if group is None:
        return None
    node = group.nodes.get(RESCALE_NODE)
    if node is not None and node.bl_idname == 'CompositorNodeTransform':
        return node
    return next((node for node in group.nodes if node.bl_idname == 'CompositorNodeTransform'), None)


def setRescale(scene, scale):
    """Point the scene's rescale Transform at `scale` and hand back what it was
    on before, so a caller can put it back. None when there is nothing to set -
    no card compositor, or one somebody has taken the Transform out of.

    The full-size and HD passes use this to switch the rescale off: both want the
    render at its own resolution, and the card chain would otherwise shrink them
    to card size inside a full-size frame just as it does for the card itself.
    """
    node = rescaleNode(scene.compositing_node_group)
    if node is None:
        return None
    previous = node.inputs['Scale'].default_value
    node.inputs['Scale'].default_value = scale
    return previous


def blurNode(group):
    """The smoothing Bilateral Blur of a card compositor group, or None."""
    if group is None:
        return None
    node = group.nodes.get(BLUR_NODE)
    if node is not None and node.bl_idname == 'CompositorNodeBilateralblur':
        return node
    return next((node for node in group.nodes if node.bl_idname == 'CompositorNodeBilateralblur'), None)


def setBlur(scene, enabled):
    """Switch the smoothing blur on or off, handing back how it was. None when
    there is no blur node to switch.

    Muting rather than unlinking, so the graph the user sees is the graph that
    ran and nothing has to be rewired back afterwards.
    """
    node = blurNode(scene.compositing_node_group)
    if node is None:
        return None
    previous = not node.mute
    node.mute = not enabled
    return previous


def setupCompositor(context, rebuild=False):
    scene = context.scene
    results = []
    # applyRenderSettings retunes this straight afterwards; building with it
    # already right keeps a freshly made group from flashing up at 1:1
    scale = 1.0/max(1, scene.med2_toolkit_cards.supersample)
    group = bpy.data.node_groups.get(COMPOSITOR_NAME)
    if group is None:
        group = bpy.data.node_groups.new(COMPOSITOR_NAME, 'CompositorNodeTree')
        buildCompositor(group, scene, scale)
        results.append(('INFO', "Created the '%s' compositor group" % COMPOSITOR_NAME))
    elif rebuild:
        buildCompositor(group, scene, scale)
        results.append(('INFO', "Rebuilt the '%s' compositor group, discarding tweaks" % COMPOSITOR_NAME))
    elif group.get(COMPOSITOR_VERSION_TAG, 0) != COMPOSITOR_VERSION:
        # a group built by an older toolkit: rebuild it rather than leave the
        # scene quietly running the previous node chain
        buildCompositor(group, scene, scale)
        results.append(('WARNING', "Rebuilt the '%s' compositor group - it was built by an older "
                                   "version of the toolkit, so any tweaks to it are gone" % COMPOSITOR_NAME))
    else:
        results.append(('INFO', "Reusing the existing '%s' compositor group" % COMPOSITOR_NAME))
    group[COMPOSITOR_VERSION_TAG] = COMPOSITOR_VERSION
    scene.compositing_node_group = group
    return group, results


def applyRenderSettings(context):
    """Push the card settings onto the scene. Returns (width, height, supersample)."""
    scene = context.scene
    settings = scene.med2_toolkit_cards
    width, height = cardResolution(settings)
    supersample = max(1, settings.supersample)
    scene.render.resolution_x = width * supersample
    scene.render.resolution_y = height * supersample
    scene.render.resolution_percentage = 100
    # the compositor does the downscale, so it has to follow the supersampling
    setRescale(scene, 1.0/supersample)
    scene.render.film_transparent = True
    scene.render.use_stamp = False
    scene.render.image_settings.file_format = 'TARGA'
    scene.render.image_settings.color_mode = 'RGBA'
    try:
        scene.eevee.taa_render_samples = settings.render_samples
    except AttributeError:
        pass
    # the line art radius is derived from the card size and zoom, both of which
    # can have moved since the outline objects were made
    refreshLineArt(context)
    return width, height, supersample


def setupCardScene(context, rebuild=False, targets=None):
    """Compositor, render settings and the line art outlines. Cameras are made
    per unit by createCardCameras, so this stays independent of what is in the
    scene - bar the outlines, which need to know which collections to cover."""
    settings = context.scene.med2_toolkit_cards
    results = []
    _group, compositor_results = setupCompositor(context, rebuild)
    results.extend(compositor_results)
    width, height, supersample = applyRenderSettings(context)
    if supersample > 1:
        results.append(('INFO', "Rendering %dx%d and scaling down to %dx%d" % (width*supersample, height*supersample, width, height)))
    else:
        results.append(('INFO', "Rendering %dx%d" % (width, height)))
    if settings.save_full_size:
        results.append(('INFO', "Full-size renders also written into each card folder's '%s' subfolder" % FULL_SIZE_FOLDER))
    if settings.add_line_art:
        if targets:
            results.extend(setupLineArt(context, targets))
    else:
        removed = removeLineArt(context.scene)
        if removed:
            results.append(('INFO', "Removed %d line art outline object(s)" % removed))
    return results


def createCardCameras(context, targets, add_sun=True, light_strength=SUN_STRENGTH,
                      ortho_scale=CAMERA_ORTHO_SCALE, control_rig_type=None,
                      light_type='SUN', lift_sunken=True):
    """Give every (unit_id, faction, object) in `targets` its own card camera.
    Also lays down the compositor and render settings, so this one button is
    enough to go from imported units to renderable cards.

    `control_rig_type` additionally builds each unit's IK controller, since a
    card is a single frame and units almost always want posing before it - and
    the bundled pose library only works through that controller. On a mount or a
    siege engine that means one controller per rider or crew member, built in the
    same pass; the mount or engine itself is left alone, since no bone of it is
    on a human controller. One camera still covers the whole unit.
    """
    # no targets here: the outlines are built at the end instead, once every unit
    # is in the collection each outline covers
    results = setupCardScene(context)
    created = 0
    refreshed = 0
    rigged = 0
    already_rigged = 0
    skipped_rigs = []
    lifted = []
    if lift_sunken:
        # the bounds are read off the evaluated objects, so anything moved or
        # posed since the last redraw has to be solved for first
        context.view_layer.update()
    for unit_id, faction, model in targets:
        if lift_sunken:
            moved = liftSunkenUnit(context, model)
            if moved:
                lifted.append((unit_id, moved))
        _camera, is_new = createCardCamera(context, unit_id, faction, model, add_sun, light_strength,
                                           ortho_scale, light_type)
        if is_new:
            created += 1
        else:
            refreshed += 1
        if control_rig_type is None or model.type != 'ARMATURE':
            continue
        built, skipped, existing, rig_results = createGroupControlRigs(context, model, control_rig_type)
        rigged += built
        already_rigged += existing
        skipped_rigs.extend(skipped)
        # only the failures are worth surfacing per unit; one line per rig would
        # bury the camera summary on a faction-sized import
        results.extend(rig_results)
    results.append(('INFO', "Created %d camera(s), refreshed %d" % (created, refreshed)))
    if lifted:
        preview = ", ".join("%s +%.2f" % entry for entry in lifted[:4]) + (", ..." if len(lifted) > 4 else "")
        results.append(('WARNING', "Set %d unit(s) that were standing in the ground down on it: %s"
                        % (len(lifted), preview)))
    if add_sun:
        label = dict(CARD_LIGHT_TYPES[i][:2] for i in range(len(CARD_LIGHT_TYPES))).get(light_type, light_type)
        results.append(('INFO', "Each camera carries a %.1f strength %s light aimed the same way"
                                % (light_strength, label.lower())))
    if control_rig_type is not None:
        results.append(('INFO', "Built %d control rig(s), %d armature(s) already had one" % (rigged, already_rigged)))
        if skipped_rigs:
            preview = ", ".join(skipped_rigs[:4]) + (", ..." if len(skipped_rigs) > 4 else "")
            results.append(('INFO', "No controller for %d mount/engine armature(s) - none of their bones "
                                    "are on a Medieval 2 human controller: %s" % (len(skipped_rigs), preview)))
    if context.scene.med2_toolkit_cards.add_line_art:
        results.extend(setupLineArt(context, targets))
    return results


#   -----------  #
#   Render pass  #
#   -----------  #

def unitCardIndex():
    """{EDU dictionary id: unit entry} taken from the generated unit dictionary.
    The imported models list only stores the dictionary id, but the card and info
    directories live on the unit entry."""
    unit_dictionary = readJsonCached(script_folder/('text/unit_dictionary.json'))
    index = {}
    for unit in unit_dictionary.values():
        unit_id = unit.get('ID', '')
        if unit_id and unit_id not in index:
            index[unit_id] = unit
    return index


def buildRenderQueue(context):
    """One entry per card camera in the scene, plus notes about anything skipped."""
    scene = context.scene
    settings = scene.med2_toolkit_cards
    subfolder, pattern, dir_key = cardOutputParts(settings)
    output_folder = bpy.path.abspath(scene.med2_toolkit_reader.directory_unit_cards)
    index = unitCardIndex()
    entries = []
    results = []
    seen = set()
    # cameras outlive the ticks that made them, so a scene carrying a faction's
    # worth of cameras would otherwise re-render the lot every time. Only the
    # ticked units are carded, and ticking nothing still means no filter
    allowed = tickedFamilies(scene)
    unticked = 0
    for camera in cardCameras(scene):
        unit_id = camera.get(CAMERA_TAG, "")
        if not unit_id:
            continue
        if unit_id in seen:
            results.append(('INFO', "Skipped a second camera for '%s'" % unit_id))
            continue
        faction = camera.get(FACTION_TAG, "") or settings.card_faction
        target = cameraTarget(scene, camera)
        if allowed is not None and target is not None and target not in allowed:
            unticked += 1
            continue
        if target is None and settings.isolate_unit:
            results.append(('WARNING', "Could not tell which rig '%s' belongs to - there is nothing to "
                                       "isolate, so its card may come out empty" % unit_id))
        unit = index.get(unit_id)
        # the pin is respelled for this card type: mercenaries are units\mercs but
        # unit_info\merc, and a pin made under the other card type holds the other name
        directories = normalizeMercFolders(cardFolders(target), subfolder)
        if directories:
            results.append(('INFO', "'%s' is pinned to %s" % (unit_id, ', '.join(directories))))
        else:
            directories = defaultCardFolders(unit, faction, dir_key, subfolder)
            if unit is None:
                # a camera made for a rig that is not an EDU unit - a custom
                # armature, or the mod data was re-read since
                results.append(('INFO', "'%s' is not an EDU unit - filing it under %s"
                                        % (unit_id, ', '.join(directories))))
            elif len(directories) > 1:
                results.append(('INFO', "'%s' is owned by %d factions - its card goes to %s"
                                        % (unit_id, len(directories), ', '.join(directories))))
        seen.add(unit_id)
        card_folders = [os.path.join(output_folder, subfolder, directory) for directory in directories]
        entries.append({
            'id': unit_id,
            'camera': camera,
            'target': target,
            'path': os.path.join(card_folders[0], pattern % unit_id),
            # a unit owned by several factions needs the same card in each of
            # their folders, so the extras are copies of the first write
            'extra_paths': [os.path.join(folder, pattern % unit_id) for folder in card_folders[1:]],
            # a pass of its own with the compositor's rescale switched off, so
            # this is the card render at full size - lossless PNG, so it can be
            # re-scaled or edited
            'full_path': os.path.join(card_folders[0], FULL_SIZE_FOLDER, "%s.png" % unit_id) if settings.save_full_size else None,
            # the HD pass. Only ever written once, however many faction folders
            # the card itself goes to - the game never reads it
            'hd_path': os.path.join(card_folders[0], HD_FOLDER, "%s.png" % unit_id) if settings.save_hd else None,
        })
    if unticked:
        results.append(('INFO', "Skipped %d unticked unit(s) - tick them in Card Units to render them" % unticked))
    if not entries:
        if unticked:
            results.append(('ERROR', "None of the %d card camera(s) belong to a ticked unit - tick the units "
                                     "to render in Card Units" % unticked))
        else:
            results.append(('ERROR', "No card cameras in the scene - use Create Card Cameras first"))
    return entries, results


def saveFullSize(context, render_result, full_path):
    """Write the render untouched, at whatever resolution it came out at, as an
    uncompressed PNG. Returns None on success or a reason string."""
    scene = context.scene
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
    except OSError as error:
        return "Could not create the full-size folder: %s" % error
    settings = scene.render.image_settings
    previous = (settings.file_format, settings.color_mode, settings.color_depth, settings.compression)
    settings.file_format = 'PNG'
    settings.color_mode = 'RGBA'
    settings.color_depth = '16'
    settings.compression = 0
    try:
        render_result.save_render(filepath=full_path, scene=scene)
    except RuntimeError as error:
        return "Could not write the full-size render: %s" % error
    finally:
        settings.file_format, settings.color_mode, settings.color_depth, settings.compression = previous
    return None


def saveFullSizePass(context, full_path):
    """Render the current camera once more with the rescale off, and save that.

    The camera, the lighting and the visibility are whatever renderCard has
    already set up - this only borrows the scene for one extra render. The blur
    stays on, unlike the HD pass: this is meant to be the card render before it
    was scaled down, not a cleaner picture of the unit.
    """
    scene = context.scene
    previous_rescale = setRescale(scene, 1.0)
    try:
        bpy.ops.render.render(write_still=False)
        render_result = bpy.data.images.get('Render Result')
        if render_result is None:
            return "Blender produced no full-size render"
        return saveFullSize(context, render_result, full_path)
    finally:
        if previous_rescale is not None:
            setRescale(scene, previous_rescale)


def saveCard(context, target_path, width, height, supersample, full_path=None):
    """Write the finished render to `target_path`, cutting the card out of it
    first when the render was supersampled. Returns None or a reason string.

    The compositor has already taken the image down to card size by then - what
    it cannot do is shrink the canvas with it, so the card sits in the middle of
    a frame that is still the full render resolution and everything around it is
    transparent. That middle is what gets written.
    """
    scene = context.scene
    render_result = bpy.data.images.get('Render Result')
    if render_result is None:
        return "Blender produced no render result"
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
    except OSError as error:
        return "Could not create the output folder: %s" % error
    if full_path:
        # written first, so a failure to scale down still leaves the render on disk
        reason = saveFullSize(context, render_result, full_path)
        if reason is not None:
            return reason
    if supersample <= 1:
        render_result.save_render(filepath=target_path, scene=scene)
        return None

    # Round-trip through a linear EXR rather than reading the render result
    # directly - Render Result exposes no pixels. EXR also skips the view
    # transform, so the crop below happens on scene-linear values and the
    # transform is applied exactly once, when the card itself is saved.
    settings = scene.render.image_settings
    previous = (settings.file_format, settings.color_mode, settings.color_depth)
    temp_path = os.path.join(bpy.app.tempdir, 'med2_card_supersample.exr')
    settings.file_format = 'OPEN_EXR'
    settings.color_mode = 'RGBA'
    settings.color_depth = '32'
    try:
        render_result.save_render(filepath=temp_path, scene=scene)
    finally:
        settings.file_format, settings.color_mode, settings.color_depth = previous

    source = bpy.data.images.load(temp_path)
    try:
        source_width, source_height = source.size
        if source_width != width*supersample or source_height != height*supersample:
            return "Render is %dx%d, expected %dx%d" % (source_width, source_height, width*supersample, height*supersample)
        pixels = np.empty(source_width*source_height*4, dtype=np.float32)
        source.pixels.foreach_get(pixels)
        pixels = pixels.reshape(source_height, source_width, 4)
        # the Transform scales about the middle of the canvas, so the card is the
        # middle of the frame - the same block the old Border Size frame's 48x66
        # reference image used to cut out
        left = (source_width - width)//2
        bottom = (source_height - height)//2
        card_pixels = np.ascontiguousarray(pixels[bottom:bottom+height, left:left+width, :])
        card = bpy.data.images.new("med2_card_output", width, height, alpha=True, float_buffer=True)
        try:
            card.colorspace_settings.name = source.colorspace_settings.name
            card.pixels.foreach_set(card_pixels.ravel())
            card.save_render(filepath=target_path, scene=scene)
        finally:
            bpy.data.images.remove(card)
    finally:
        bpy.data.images.remove(source)
    return None


def isolateSun(scene, unit_id):
    """Only the current unit's sun should light the render - a sun is infinite,
    so every other card's sun would stack on top of it."""
    previous = {}
    for sun in cardSuns(scene):
        previous[sun.name] = sun.hide_render
        sun.hide_render = sun.get(SUN_TAG, "") != unit_id
    return previous


def restoreSuns(scene, previous):
    for name, hidden in previous.items():
        sun = bpy.data.objects.get(name)
        if sun is not None:
            sun.hide_render = hidden


#   ---------------  #
#   Unit isolation   #
#   ---------------  #

def unitFamily(target):
    """The objects that make up one unit: every armature of it, everything
    parented under those and the control rigs driving them. The rig itself draws
    nothing - the meshes are its children, and the controller is its parent.

    A mount or a siege engine is several armatures, so the walk starts from all
    of them rather than from the one the camera happens to name. Walking the
    mount's children would cover its riders while none of them has a controller,
    but the moment one does the rider hangs off that controller instead - and a
    card with the rider missing off the horse is the whole reason this is a group
    rather than a parent.
    """
    family = set()
    parts = groupParts(target) or [target]
    stack = list(parts)
    while stack:
        obj = stack.pop()
        if obj in family:
            continue
        family.add(obj)
        stack.extend(obj.children)
    for part in parts:
        controller = controlRigOf(part)
        if controller is not None:
            family.add(controller)
    return family


def partFamily(part):
    """One armature of a unit on its own: itself, the meshes hanging off it and
    its own controller - but not the other armatures of the same unit.

    They have to be cut out explicitly, because a rider is parented under the
    mount (and, once it has one, under a controller that is itself parented
    under the mount), so the plain child walk would drag the whole unit back in.
    """
    others = set()
    for member in groupParts(part):
        if member is part:
            continue
        others.add(member)
        controller = controlRigOf(member)
        if controller is not None:
            others.add(controller)
    family = set()
    stack = [part]
    while stack:
        obj = stack.pop()
        if obj in family or obj in others:
            continue
        family.add(obj)
        stack.extend(obj.children)
    controller = controlRigOf(part)
    if controller is not None:
        family.add(controller)
    return family


def unitBounds(context, target):
    """(lowest z, highest z) of everything a unit draws, in world space, or None
    when it has no geometry to measure.

    The evaluated objects are measured, not the originals: a skinned mesh's own
    bounding box is its undeformed one, and a unit that has already been posed
    would report where it used to be.
    """
    depsgraph = context.evaluated_depsgraph_get()
    lowest = None
    highest = None
    for obj in unitFamily(target):
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            continue
        evaluated = obj.evaluated_get(depsgraph)
        matrix = evaluated.matrix_world
        for corner in evaluated.bound_box:
            z = (matrix @ Vector(corner)).z
            if lowest is None or z < lowest:
                lowest = z
            if highest is None or z > highest:
                highest = z
    if lowest is None:
        return None
    return lowest, highest


def liftSunkenUnit(context, target):
    """Set a unit standing in the ground down on it: raise it by exactly how far
    its lowest point is below z=0, so its feet land on the floor.

    The card camera is a fixed pose, so a unit whose feet are below the floor is
    framed low and loses its head off the top of the card. Only a genuine
    straddle is touched - some of the unit under the floor, most of it above -
    so a unit deliberately parked somewhere else in the scene is left alone.
    Returns the distance moved, 0.0 when nothing was.
    """
    bounds = unitBounds(context, target)
    if bounds is None:
        return 0.0
    lowest, highest = bounds
    if highest <= 0 or lowest > -SUNK_DEPTH:
        return 0.0
    height = highest - lowest
    if height <= 0 or (-lowest)/height > MAX_SUNK_SHARE:
        return 0.0
    # the controller is the unit's parent, so moving the rig underneath it would
    # leave the two disagreeing about where the unit is - and on a mount it is
    # the mount that has to move, or its riders stay where they were
    root = groupRoot(target) or target
    root = controlRigOf(root) or root
    matrix = root.matrix_world.copy()
    matrix.translation.z += -lowest
    root.matrix_world = matrix
    return -lowest


def listedEntries(scene):
    """[(entry, object)] for the imported models list, skipping entries whose
    object has gone. An entry can point at a lone mesh rather than a rig, which
    is why this is not just a walk over the scene's armatures."""
    entries = []
    for item in scene.med2_toolkit_import_list:
        model = bpy.data.objects.get(item.object_name) if item.object_name else None
        if model is None:
            model = bpy.data.objects.get(item.name)
        if model is not None:
            entries.append((item, model))
    return entries


def listedModels(scene, ticked_only=False):
    """The models the imported models list points at. `ticked_only` narrows it to
    the ones ticked in the Card Units list - the same entries the card tools
    already act on."""
    return {model for item, model in listedEntries(scene)
            if not (ticked_only and not item.use)}


def tickedParts(scene, target):
    """The armatures of a multi-part unit whose sub-entries are ticked.

    This is what the 'part' isolation scope renders: untick a mount's rider and
    the card shows the horse on its own, untick the mount and it shows the rider
    on its own. A unit that is a single armature has no parts to choose between,
    and a unit with every part unticked falls back to the whole thing - an empty
    card is never what was meant.
    """
    parts = groupParts(target)
    if len(parts) < 2:
        return [target]
    ticked = {model for item, model in listedEntries(scene) if item.use}
    chosen = [part for part in parts if part in ticked]
    return chosen or parts


def cardFamily(scene, target, scope='unit'):
    """What isolation keeps on screen for one card.

    'unit' is the whole thing - a mount with everyone riding it. 'part' narrows
    it to the armatures ticked in the imported models list, so one rider, or the
    mount by itself, can be carded without deleting anything.
    """
    if target is None:
        return set()
    if scope != 'part':
        return unitFamily(target)
    family = set()
    for part in tickedParts(scene, target):
        family |= partFamily(part)
    return family


def tickedFamilies(scene):
    """Every object belonging to a unit ticked in the Card Units list, or None
    when nothing is ticked at all - the same "no ticks means no filter" rule
    cardTargets uses. A control rig and the meshes come out of the ticked rig's
    own family, so they are covered without being roots of their own."""
    ticked = listedModels(scene, ticked_only=True)
    if not ticked:
        return None
    allowed = set()
    for model in ticked:
        allowed.update(unitFamily(model))
    return allowed


def visibleObjects(context):
    """Everything the viewport is currently showing. visible_get folds in the eye,
    the monitor toggle and the collections above the object, so a unit hidden any
    of those three ways counts as invisible here."""
    view_layer = context.view_layer
    visible = set()
    for obj in view_layer.objects:
        try:
            if obj.visible_get(view_layer=view_layer):
                visible.add(obj)
        except RuntimeError:
            # an object that is not in this view layer cannot be asked
            continue
    return visible


def parentCollections(scene):
    """{collection name: [collections it is linked into]}."""
    parents = {}
    for parent in list(bpy.data.collections) + [scene.collection]:
        for child in parent.children:
            parents.setdefault(child.name, []).append(parent)
    return parents


def collectionChain(scene, collections):
    """`collections` plus every collection above them. A collection hidden for
    render hides everything inside it, so the unit's whole chain has to be
    checked, not just the collection it sits in."""
    parents = parentCollections(scene)
    chain = []
    stack = list(collections)
    while stack:
        collection = stack.pop()
        if collection in chain:
            continue
        chain.append(collection)
        stack.extend(parents.get(collection.name, []))
    return chain


def isolateUnit(context, camera, target, visible_only=False, family=None):
    """Switch off everything the card should not show, and switch the unit on.

    Every card camera looks at the same scene, so a neighbouring unit reaching
    into the frame, a stray import or an old mesh all land on the card. For the
    length of one render only the unit's own objects stay renderable: its rig and
    meshes, the camera, the camera's sun and the outline covering its collection.
    Anything the unit needs that was switched off by hand is switched back on,
    including the render toggle on the collections it lives in.

    `visible_only` narrows that to the VISIBLE part of the unit and switches the
    rest of the scene off in the viewport as well as for the render, so what is
    left standing there is the one armature being carded. Nothing hidden is put
    back: a variation mesh, a shield or a helmet switched off by hand stays off,
    which is what the card wants - `hideVariations` hides the spare heads and
    weapons with the eye AND `hide_render`, and the default mode's "switch the
    unit back on" undoes exactly that. The camera and the light it carries are
    the only things ever forced on, without which the render is black. It is all
    put back before the next camera, the same as the default mode.

    `family` is what counts as "the unit" - cardFamily works it out from the
    isolation scope, so a mount can be kept whole or narrowed to the one
    armature of it being carded. Left out, it is the whole unit.

    Returns the state restoreVisibility puts back.
    """
    scene = context.scene
    # the camera and the light hanging off it are what makes a card render at
    # all, so they are switched on in either mode
    essential = {camera}
    essential.update(camera.children)
    if family is None:
        family = unitFamily(target) if target is not None else set()
    if visible_only:
        # only what the viewport is actually showing of that unit
        keep = (family & visibleObjects(context)) | essential
        # and only the essentials are switched back on; everything the user hid
        # by hand is left hidden
        force_on = essential
    else:
        keep = family | essential
        force_on = keep

    kept_collections = set()
    for obj in force_on:
        kept_collections.update(obj.users_collection)
    kept_names = {collection.name for collection in kept_collections}
    # the outline is its own object, tagged with the collection it traces
    for gpencil in lineArtObjects(scene):
        if gpencil.get(LINE_ART_TAG, "") in kept_names:
            keep.add(gpencil)

    objects = {}
    viewport = {}
    for obj in scene.objects:
        hidden = obj not in keep
        if not hidden and obj not in force_on:
            continue
        if obj.hide_render != hidden:
            objects[obj.name] = obj.hide_render
            obj.hide_render = hidden
        if not visible_only:
            continue
        # switch it off in the viewport too, so the unit really is left standing
        # there on its own while its card renders rather than only on the render
        try:
            if obj.hide_get() != hidden:
                viewport[obj.name] = obj.hide_get()
                obj.hide_set(hidden)
        except RuntimeError:
            # an object outside this view layer has no eye to toggle
            pass

    collections = []
    excluded = []
    master = context.view_layer.layer_collection
    for collection in collectionChain(scene, kept_collections):
        if collection.hide_render:
            collection.hide_render = False
            collections.append(collection.name)
        layer = recurLayerCollection(master, collection.name)
        # an excluded collection is not evaluated at all, and the master one's
        # checkbox is read-only
        if layer is not None and layer is not master and layer.exclude:
            layer.exclude = False
            excluded.append(collection.name)
    return {'objects': objects, 'viewport': viewport, 'collections': collections, 'excluded': excluded}


def restoreVisibility(context, state):
    """Put back everything isolateUnit switched, so the next camera starts from
    the scene the user actually built."""
    scene = context.scene
    for name, hidden in state['objects'].items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            obj.hide_render = hidden
    for name, hidden in state.get('viewport', {}).items():
        obj = bpy.data.objects.get(name)
        if obj is not None:
            try:
                obj.hide_set(hidden)
            except RuntimeError:
                pass
    master = context.view_layer.layer_collection
    for name in state['excluded']:
        layer = recurLayerCollection(master, name)
        if layer is not None and layer is not master:
            layer.exclude = True
    for name in state['collections']:
        collection = bpy.data.collections.get(name)
        if collection is None and scene.collection.name == name:
            collection = scene.collection
        if collection is not None:
            collection.hide_render = True


def copyCard(source_path, paths):
    """Drop the finished card into the other folders it was pinned to. Returns
    None or a reason string."""
    for path in paths or ():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(source_path, path)
        except OSError as error:
            return "Could not copy the card to %s: %s" % (os.path.dirname(path), error)
    return None


def saveHDRender(context, camera, hd_path, width, height, ortho_scale):
    """Render the same camera again at HD size and save it as a PNG.

    A second pass rather than a scale-up of the card render: the card is 48x64
    and no amount of resampling puts detail back. The camera's ortho scale is
    widened for the pass and put back afterwards, for the HD sizes that frame a
    different shape than the card does - see hdOrthoScale. The compositor's
    rescale is switched off for the pass as well, since this render is wanted at
    its own resolution rather than shrunk to card size - and so is the smoothing
    blur, which is there to keep the card's nearest-neighbour downscale from
    crawling and at HD size only costs detail.
    """
    scene = context.scene
    render = scene.render
    previous = (render.resolution_x, render.resolution_y)
    previous_scale = camera.data.ortho_scale if camera is not None else None
    previous_rescale = setRescale(scene, 1.0)
    previous_blur = setBlur(scene, False)
    render.resolution_x = width
    render.resolution_y = height
    if camera is not None:
        camera.data.ortho_scale = ortho_scale
    try:
        context.view_layer.update()
        bpy.ops.render.render(write_still=False)
        render_result = bpy.data.images.get('Render Result')
        if render_result is None:
            return "Blender produced no HD render"
        return saveFullSize(context, render_result, hd_path)
    finally:
        render.resolution_x, render.resolution_y = previous
        if camera is not None and previous_scale is not None:
            camera.data.ortho_scale = previous_scale
        if previous_rescale is not None:
            setRescale(scene, previous_rescale)
        if previous_blur is not None:
            setBlur(scene, previous_blur)


def renderCard(context, entry, width, height, supersample):
    """Render one unit through its own camera. Returns None or a reason string."""
    scene = context.scene
    settings = scene.med2_toolkit_cards
    camera = entry['camera']
    if camera.name not in scene.objects:
        return "Its camera was deleted"
    target = entry.get('target')
    # what "the unit" means for this card: the whole mount and its riders, or
    # only the parts of it ticked in the imported models list
    family = cardFamily(scene, target, settings.isolate_scope)
    if settings.isolate_unit and settings.isolate_visible_only and target is not None:
        # nothing hidden is put back in this mode, so a unit switched off by hand
        # would quietly write an empty card
        if not (family & visibleObjects(context)):
            return "It is hidden in the viewport, and Visible only renders nothing that is hidden"
    previous_camera = scene.camera
    previous_suns = isolateSun(scene, entry['id'])
    # nested inside the sun pass on purpose: it stores whatever isolateSun left
    # behind and hands it straight back, so restoreSuns still has the last word
    isolated = isolateUnit(context, camera, target, settings.isolate_visible_only,
                           family) if settings.isolate_unit else None
    scene.camera = camera
    try:
        context.view_layer.update()
        # The full-size image needs a pass of its own now that the compositor
        # does the downscale: the card render no longer holds a full-size picture
        # to pull out of, only a card-sized one in a full-size frame. Only when
        # there is no supersampling are the two the same render.
        full_path = entry.get('full_path')
        if full_path and supersample > 1:
            reason = saveFullSizePass(context, full_path)
            if reason is not None:
                return reason
            full_path = None
        bpy.ops.render.render(write_still=False)
        reason = saveCard(context, entry['path'], width, height, supersample, full_path)
        if reason is not None:
            return reason
        reason = copyCard(entry['path'], entry.get('extra_paths'))
        if reason is not None:
            return reason
        if entry.get('hd_path'):
            hd_width, hd_height = hdResolution(settings)
            return saveHDRender(context, camera, entry['hd_path'], hd_width, hd_height,
                                hdOrthoScale(settings, hd_width, hd_height))
        return None
    finally:
        scene.camera = previous_camera
        if isolated is not None:
            restoreVisibility(context, isolated)
        restoreSuns(scene, previous_suns)


def renderedPaths(entry):
    """Every file one card render writes, most interesting first. The extra
    copies in other faction folders are the same picture again, so they are left
    out - showing them would just pad the image list."""
    paths = [entry.get('path'), entry.get('hd_path'), entry.get('full_path')]
    return [path for path in paths if path]


def fitImageToArea(area):
    """Zoom an image editor so the card fills it.

    A 48x64 card opens at 1:1 - a postage stamp in the middle of a whole window.
    `image.view_all(fit_view=True)` is the View > Frame All item, and it needs a
    WINDOW region of that area overridden in, not just the area. It is run off a
    timer because a freshly retyped (or brand new) area has no usable region size
    until it has drawn once, and zooming to a zero-sized region does nothing.
    """
    def run():
        try:
            window = next((w for w in bpy.context.window_manager.windows
                           if area in list(w.screen.areas)), None)
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if window is None or region is None:
                return None
            if region.width <= 1 or region.height <= 1:
                return 0.05
            with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                bpy.ops.image.view_all(fit_view=True)
        except (RuntimeError, ReferenceError, StopIteration):
            pass
        return None
    bpy.app.timers.register(run, first_interval=0.05)


def openRendersWindow(context, paths):
    """Load every rendered card and show them in a new Image Editor window.

    Blender shows one image per editor, so they all go into `bpy.data.images`
    and the window opens on the first - the editor's browse dropdown is then the
    way through the rest. Returns a (level, message) pair."""
    images = []
    failed = []
    for path in dict.fromkeys(paths):
        if not os.path.isfile(path):
            continue
        try:
            image = bpy.data.images.load(path, check_existing=True)
            image.reload()          # a re-render of a card already loaded once
        except RuntimeError as error:
            failed.append("%s (%s)" % (os.path.basename(path), error))
            continue
        images.append(image)
    if not images:
        return ('WARNING', "No rendered files found to open"
                + (": " + "; ".join(failed) if failed else ""))
    if bpy.app.background or context.window is None:
        return ('INFO', "%d render(s) loaded into the image list" % len(images))

    window_manager = context.window_manager
    # A second render should refill the window the first one opened rather than
    # stack another one up, so look for an image editor in a side window first.
    # windows[0] is the main window - never take that one over.
    reused = next((area for window in list(window_manager.windows)[1:]
                   for area in window.screen.areas if area.type == 'IMAGE_EDITOR'), None)
    if reused is not None:
        reused.spaces.active.image = images[0]
        fitImageToArea(reused)
        return ('INFO', "Showed %d render(s) in the open image window - use the image dropdown "
                "there to flip through them" % len(images))

    before = len(window_manager.windows)
    # window_new duplicates the area it is called from, so it needs one to
    # duplicate - the sidebar this runs from lives in a VIEW_3D
    area = next((a for a in context.window.screen.areas if a.type == 'VIEW_3D'),
                context.window.screen.areas[0] if context.window.screen.areas else None)
    if area is not None:
        try:
            with context.temp_override(window=context.window, area=area):
                bpy.ops.wm.window_new()
        except RuntimeError as error:
            return ('WARNING', "%d render(s) loaded into the image list, but a new window "
                    "could not be opened: %s" % (len(images), error))
    if len(window_manager.windows) <= before:
        return ('WARNING', "%d render(s) loaded into the image list, but no new window opened"
                % len(images))

    window = window_manager.windows[-1]
    areas = [a for a in window.screen.areas if a.type != 'STATUSBAR']
    if not areas:
        return ('WARNING', "%d render(s) loaded into the image list" % len(images))
    target = max(areas, key=lambda a: a.width * a.height)
    target.type = 'IMAGE_EDITOR'
    target.spaces.active.image = images[0]
    fitImageToArea(target)
    return ('INFO', "Opened %d render(s) in a new window - use the image dropdown there to "
            "flip through them" % len(images))


def shuffleImportedVariations(context, hideVariations):
    """Re-roll the variations of every rig in the imported models list. Cards are
    single frames, so a model still showing all of its variation meshes at once
    renders as a pile of overlapping heads and weapons."""
    rigs = []
    for item in context.scene.med2_toolkit_import_list:
        model = bpy.data.objects.get(item.object_name) if item.object_name else None
        if model is None:
            model = bpy.data.objects.get(item.name)
        if model is not None and model not in rigs:
            rigs.append(model)
    if not rigs:
        return 0
    bpy.ops.object.select_all(action='DESELECT')
    for rig in rigs:
        rig.select_set(True)
    context.view_layer.objects.active = rigs[0]
    hideVariations()
    return len(rigs)
