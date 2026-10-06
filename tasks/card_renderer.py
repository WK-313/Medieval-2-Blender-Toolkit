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

from mathutils import Euler, Vector

from ..directories import readJsonCached
from .control_rig import controlRigOf, controlledRigs, isControlRig
from .recurlayercollection import linkBeside, recurLayerCollection
from .tga_dds import gameTexturePath, viewablePath, writeTgaDds
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

# Perspective framing, read off gondor_infantry.blend and unit_card_blendfile.blend.
# Both are a 50mm lens on Blender's default 36mm sensor, and both stand about 1.39
# frame-heights back from the unit - which is exactly lens/sensor. So a perspective
# card camera placed `card_zoom * lens / sensor` from the framing pivot frames the
# same box an orthographic one frames at that zoom: the composition is unchanged and
# only the foreshortening is added.
CAMERA_LENS = 50.0
CAMERA_SENSOR = 36.0

CAMERA_PROJECTIONS = [
    ('ORTHO', "Orthographic", "No perspective at all - the unit is drawn flat on, which is how the "
                              "toolkit has always rendered cards. Zoom is the frame's width in world units"),
    ('PERSP', "Perspective", "A real lens, so the unit foreshortens slightly - the setup "
                             "gondor_infantry.blend and unit_card_blendfile.blend both use. Zoom keeps its "
                             "meaning: the camera moves back or in to frame the same box"),
]

# Distance along the camera's own view axis from CAMERA_LOCATION to the point the
# framing turns about. Solved from the pose above: it is where that axis crosses the
# unit's centreline (y = 0), around chest-to-head height. An orthographic camera does
# not care where along its axis it sits, a perspective one does, so both projections
# are placed by holding this pivot still and sliding the camera along the axis - which
# is what keeps the framing identical when the projection is switched.
CAMERA_PIVOT_DISTANCE = 2.6812

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
# The world point a camera's framing turns about, stored so the projection and the
# zoom can be changed later without having to find the unit again.
PIVOT_TAG = "med2_card_pivot"
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
# ...and POINT_STRENGTH is the figure for a lamp sitting ON the camera, which is where
# the rig used to put it. Moving the lamp back has to carry the exposure with it.
POINT_REFERENCE_DISTANCE = CAMERA_PIVOT_DISTANCE

CARD_LIGHT_TYPES = [
    ('SUN',   "Sun",   "Directional light. Parallel rays, so it lights the unit evenly however far back it is placed"),
    ('POINT', "Point", "Point lamp. Falls off with distance, so it picks out whatever is nearest - the lamp both reference card files use"),
]

# Where the lamp stands, relative to the point the camera is framing. Taken from the
# reference card files: unit_card_blendfile.blend and gondor_infantry.blend both park
# a point lamp about 5.8 units from the unit and roughly 22 degrees above the camera's
# axis, rather than on the camera itself. The swing round to the side is ours - both
# files leave it at zero - but a key light off the axis is what actually shapes a
# face, and it is one slider back to their setup.
LIGHT_DISTANCE = 6.0
LIGHT_ELEVATION = 25.0
LIGHT_AZIMUTH = 25.0
# Lamp radius, again off the reference files. A lamp with some size to it gives a
# shadow edge that is not a hard line.
LIGHT_RADIUS = 0.25


def defaultLightStrength(light_type, distance=None):
    """The strength a light type wants at `distance` from the unit.

    A point lamp is inverse-square, so the strength that reads correctly on the
    camera reads as near black six units back. POINT_STRENGTH is the on-camera
    figure, and this carries it out to wherever the lamp has been moved to.
    """
    if light_type != 'POINT':
        return SUN_STRENGTH
    if distance is None:
        distance = LIGHT_DISTANCE
    ratio = max(distance, 0.01)/POINT_REFERENCE_DISTANCE
    return round(POINT_STRENGTH*ratio*ratio, 1)


#   ---------------------  #
#   Camera and light rig   #
#   ---------------------  #

def cameraAxes(rotation=CAMERA_ROTATION):
    """(forward, right, up) of a card camera at `rotation`, in world space.
    Blender cameras look down their own -Z, with +X right and +Y up."""
    matrix = Euler(tuple(rotation), 'XYZ').to_matrix()
    return -matrix.col[2].normalized(), matrix.col[0].normalized(), matrix.col[1].normalized()


def framingDistance(settings):
    """How far a card camera stands from the point it is framing.

    Fixed for an orthographic camera - it frames the same box wherever it sits, so it
    stays where it has always been. A perspective one has to solve for it, and
    lens/sensor is the whole of that: the frame is `distance * sensor / lens` across.
    """
    if settings.camera_projection != 'PERSP':
        return CAMERA_PIVOT_DISTANCE
    return settings.card_zoom*max(settings.camera_lens, 0.1)/CAMERA_SENSOR


def cameraPivot(target_x):
    """The world point a unit standing at `target_x` is framed about."""
    forward = cameraAxes()[0]
    base = Vector((target_x + CAMERA_LOCATION[0], CAMERA_LOCATION[1], CAMERA_LOCATION[2]))
    return base + forward*CAMERA_PIVOT_DISTANCE


def storedPivot(camera):
    """The pivot a card camera was built around."""
    pivot = camera.get(PIVOT_TAG)
    if pivot is not None and len(pivot) == 3:
        return Vector(tuple(pivot))
    # a camera from before the pivot was stored is an orthographic one parked at
    # CAMERA_LOCATION, so its pivot is the standard distance down its own axis
    forward = cameraAxes(camera.rotation_euler)[0]
    return camera.matrix_world.translation + forward*CAMERA_PIVOT_DISTANCE


def placeCardCamera(camera, settings, pivot):
    """Put a card camera on `pivot` with the projection and zoom `settings` ask for.

    Returns how far from the pivot it ended up, which is what the lamp is then placed
    against.
    """
    distance = framingDistance(settings)
    camera.rotation_euler = CAMERA_ROTATION
    camera.location = pivot - cameraAxes()[0]*distance
    camera[PIVOT_TAG] = tuple(pivot)
    data = camera.data
    if settings.camera_projection == 'PERSP':
        data.type = 'PERSP'
        data.sensor_fit = 'AUTO'
        data.sensor_width = CAMERA_SENSOR
        data.lens = max(settings.camera_lens, 0.1)
    else:
        data.type = 'ORTHO'
        data.ortho_scale = settings.card_zoom
    return distance


def lightPlacement(settings, distance=None):
    """Where a card camera's lamp goes, in the camera's own space, and how it aims.

    The old rig parked the lamp on the camera. That lights a unit dead flat - every
    surface facing the lens gets the same amount, so nothing on the model reads as
    round and a 48x64 card comes out looking like a decal. Both reference card files
    stand the lamp well back and above the camera instead, which is what this is:
    back down the view axis by `light_distance` from the point being framed, then
    lifted by `light_elevation` and swung round by `light_azimuth`.

    Camera space rather than world space on purpose - the lamp is parented to the
    camera, so every unit in a faction-sized scene is lit identically however far
    along X it happens to stand.
    """
    if distance is None:
        distance = CAMERA_PIVOT_DISTANCE
    elevation = math.radians(settings.light_elevation)
    azimuth = math.radians(settings.light_azimuth)
    # +Z in camera space points back towards the camera, +Y is up and +X is right
    offset = Vector((math.cos(elevation)*math.sin(azimuth),
                     math.sin(elevation),
                     math.cos(elevation)*math.cos(azimuth)))*max(settings.light_distance, 0.0)
    location = Vector((0.0, 0.0, -distance)) + offset
    # a sun carries only a direction, so it has to be aimed back at what it lights
    if offset.length > 1e-6:
        rotation = (-offset).to_track_quat('-Z', 'Y').to_euler()
    else:
        rotation = Euler((0.0, 0.0, 0.0))
    return location, rotation


def cardLightOf(camera):
    """The lamp belonging to a card camera, or None."""
    return next((child for child in camera.children
                 if child.type == 'LIGHT' and SUN_TAG in child), None)


def placeCardLight(camera, settings, distance=None):
    """Move a card camera's lamp onto the placement `settings` describe."""
    light = cardLightOf(camera)
    if light is None:
        return None
    location, rotation = lightPlacement(settings, distance)
    # the lamp is placed in camera space, so a parent inverse left behind by somebody
    # re-parenting it by hand would put it somewhere else entirely
    light.matrix_parent_inverse.identity()
    light.location = location
    light.rotation_euler = rotation
    return light


def refreshCardCameras(scene, settings):
    """Re-place every card camera and its lamp from the panel's framing and light
    settings. This is what the live sliders drive - nothing is rebuilt, so a camera
    moved off its unit by hand keeps the pivot it was moved to."""
    for camera in cardCameras(scene):
        distance = placeCardCamera(camera, settings, storedPivot(camera))
        placeCardLight(camera, settings, distance)


#   ------------------  #
#   Render mode / look  #
#   ------------------  #

# Engine ids newest first: 4.2-4.5 called EEVEE Next BLENDER_EEVEE_NEXT, 5.x went back
# to BLENDER_EEVEE, and older builds carry legacy EEVEE under that same name.
# Whichever the running Blender accepts is the one used.
EEVEE_ENGINES = ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE')
WORKBENCH_ENGINE = 'BLENDER_WORKBENCH'

CARD_RENDER_MODES = [
    ('RENDERED', "Rendered", "EEVEE, with the unit's real materials, lighting and shadows - what both "
                             "reference card files render with"),
    ('SOLID', "Solid", "Workbench, the viewport's own Solid shading. Flat unlit texture colour by "
                       "default, so the card comes out the colours the .dds is and no lighting can "
                       "darken it. Far faster, and it needs no lamp at all"),
]

SOLID_LIGHTING = [
    ('FLAT', "Flat", "No shading whatsoever - the texture's own colours, straight through"),
    ('STUDIO', "Studio", "Workbench's built-in studio lights, so the unit still reads as solid"),
    ('MATCAP', "Matcap", "Workbench's matcap shading"),
]

SOLID_COLOURS = [
    ('TEXTURE', "Texture", "The unit's texture, which is what a card wants"),
    ('MATERIAL', "Material", "Each material's flat base colour"),
    ('OBJECT', "Object", "Each object's viewport display colour"),
    ('SINGLE', "Single", "One colour for everything - a silhouette"),
]

# Workbench's anti-aliasing is a fixed set of sample counts, best first.
SOLID_AA_STEPS = ('32', '16', '11', '8', '5')

VIEW_TRANSFORMS = [
    ('KEEP', "Scene default", "Leave the scene's own view transform alone"),
    ('Standard', "Standard", "No tone mapping: the card comes out the colours the texture is. The "
                             "safest choice for game UI art, which is composited over the game's own "
                             "interface rather than looked at as a photograph"),
    ('Filmic', "Filmic", "The transform gondor_infantry.blend and unit_card_blendfile.blend both "
                         "render through - softer highlights, slightly muted colour"),
    ('AgX', "AgX", "Blender 4.0+'s own default, and therefore what the toolkit rendered through "
                   "before this setting existed. Rolls highlights off hardest and desaturates most, "
                   "which on a 48x64 card reads as washed out"),
    ('Khronos PBR Neutral', "PBR Neutral", "Khronos' transform: keeps colour close to the texture and "
                                           "only rolls off the very brightest highlights"),
    ('Raw', "Raw", "No transform whatsoever"),
]

# Ambient occlusion distance both reference files use.
CARD_AO_DISTANCE = 2.0
# Flat grey world both reference files carry. Transparent film keeps it off the card
# itself, but it still lights the unit - it is the fill that stops the side facing
# away from the lamp going to pure black.
CARD_WORLD_AMBIENT = 0.05
CARD_WORLD_NAME = "Medieval 2 Cards"


def setRenderEngine(scene, candidates):
    """Point the scene at the first of `candidates` this Blender has, and hand back
    which one that was - or None if it has none of them."""
    for engine in candidates:
        try:
            scene.render.engine = engine
        except TypeError:
            continue
        return engine
    return None


def applyViewTransform(scene, name):
    """Set the scene's view transform. Returns None, or a reason it could not.

    Worth setting rather than leaving alone: Blender 4.0 changed the default from
    Filmic to AgX, and AgX desaturates hard. Both reference card files are Filmic, and
    neither was ever going to look like itself rendered through AgX.
    """
    if name == 'KEEP':
        return None
    try:
        scene.view_settings.view_transform = name
    except TypeError:
        return ("This Blender has no '%s' view transform, so the cards render through '%s'"
                % (name, scene.view_settings.view_transform))
    return None


def applyAmbientOcclusion(scene, enabled, distance=CARD_AO_DISTANCE):
    """Switch EEVEE's ambient occlusion on or off, whichever EEVEE this is.

    Both reference files render with it on at 2.0 - it is what puts the shadow under a
    helmet rim and inside a mail collar, and without it a unit at 48x64 flattens
    towards a silhouette. Legacy EEVEE calls it GTAO; EEVEE Next (4.2 onwards) folded
    it into Fast GI, which only runs as part of the ray tracing pass.
    """
    eevee = getattr(scene, 'eevee', None)
    if eevee is None:
        return None
    if hasattr(eevee, 'use_gtao'):
        eevee.use_gtao = enabled
        if enabled:
            eevee.gtao_distance = distance
        return 'gtao'
    if hasattr(eevee, 'use_fast_gi'):
        eevee.use_fast_gi = enabled
        if enabled:
            if hasattr(eevee, 'use_raytracing'):
                eevee.use_raytracing = True
            eevee.fast_gi_distance = distance
            try:
                eevee.fast_gi_method = 'AMBIENT_OCCLUSION_ONLY'
            except TypeError:
                pass
        return 'fast_gi'
    return None


def applyWorldAmbient(scene, level):
    """Give the scene a flat grey world at `level`. Returns None or a reason string.

    Never overwrites a world somebody has actually built: a Background colour driven by
    other nodes is left exactly as it is.
    """
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new(CARD_WORLD_NAME)
        scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    if tree is None:
        return "The scene's world has no node tree, so the card fill light was left alone"
    background = next((node for node in tree.nodes if node.bl_idname == 'ShaderNodeBackground'), None)
    if background is None:
        return "The scene's world has no Background node, so the card fill light was left alone"
    if background.inputs['Color'].is_linked:
        return ("The scene's world background is driven by other nodes, so the card fill light was "
                "left alone")
    background.inputs['Color'].default_value = (level, level, level, 1.0)
    background.inputs['Strength'].default_value = 1.0
    return None


def applySolidShading(scene, settings):
    """Set Workbench up for the Solid render mode. Returns the AA step it landed on."""
    shading = scene.display.shading
    shading.light = settings.solid_light
    shading.color_type = settings.solid_colour
    # a card is cut out of a transparent frame, so an outline drawn round the unit
    # would end up baked into it
    shading.show_object_outline = False
    shading.show_specular_highlight = settings.solid_light != 'FLAT'
    shading.show_shadows = False
    shading.show_cavity = False
    shading.show_xray = False
    samples = max(1, settings.render_samples)
    step = next((value for value in SOLID_AA_STEPS if int(value) <= samples), SOLID_AA_STEPS[-1])
    try:
        scene.display.render_aa = step
    except TypeError:
        pass
    return step


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
    # every card camera is aimed at its own unit's X, so the rig it frames is the one
    # nearest that X - this is what keeps a collection holding several units from
    # handing back the wrong one. Measured off the stored pivot rather than the
    # camera's own position, which a perspective camera slides along its view axis
    aimed_at = storedPivot(camera).x - cameraPivot(0.0).x
    return min(deform, key=lambda obj: abs(obj.matrix_world.translation.x - aimed_at))


def cameraIsVisible(camera):
    """Whether a card camera is one the user can still see.

    A camera switched off with the monitor icon or hidden in the view layer has
    been put away deliberately - which is exactly what isolating one unit out of
    fifty does - so it is not something to switch the viewport to. `visible_get`
    needs the object to be in the view layer, hence the guard.
    """
    if camera.hide_viewport:
        return False
    try:
        return camera.visible_get()
    except RuntimeError:
        return True


def cameraUnitRoot(obj):
    """The rig a card camera would have been made for, from anything belonging to
    the unit: the deform rig itself, a mesh under it, the control rig driving it,
    or one part of a mounted unit.

    Cameras are per UNIT, so a rider resolves to its mount and a crew member to
    its engine - the same rule cardTargets uses when the cameras are built.
    """
    if obj is None:
        return None
    rig = obj if obj.type == 'ARMATURE' else None
    parent = obj
    while rig is None and parent.parent is not None:
        parent = parent.parent
        if parent.type == 'ARMATURE':
            rig = parent
    if rig is None:
        return None
    if isControlRig(rig):
        # the controller drives the rig the meshes hang off; the camera was made
        # for that one, never for the controller
        driven = controlledRigs(rig)
        rig = driven[0] if driven else rig
    return groupRoot(rig) or rig


def cameraForObject(scene, obj):
    """The card camera framing whatever `obj` belongs to, or None."""
    rig = cameraUnitRoot(obj)
    if rig is None:
        return None
    cameras = cardCameras(scene)
    for camera in cameras:
        if camera.get(TARGET_TAG, "") == rig.name:
            return camera
    # cameras from before TARGET_TAG existed know only their unit id, so fall
    # back to the same collection-and-X walk the renderer uses
    for camera in cameras:
        if cameraTarget(scene, camera) == rig:
            return camera
    return None


def selectionCamera(context):
    """The card camera the viewport should be looking through for the current
    selection, or None to leave the scene camera alone.

    The ACTIVE object decides, with the rest of the selection behind it, so
    clicking a unit frames that unit instead of whichever camera happens to be
    first in the file - which is what made every unit past the first look
    off-centre. Selecting a card camera itself means "look through this one".

    Hidden cameras are never chosen: a working view is never taken away because
    the unit's own camera happens to be switched off. A hidden camera the scene
    is ALREADY looking through is the one exception - there is nothing to lose
    then, so the first visible card camera takes over.
    """
    scene = context.scene
    cameras = cardCameras(scene)
    if not cameras:
        return None
    ordered = []
    if context.object is not None:
        ordered.append(context.object)
    ordered.extend(obj for obj in context.selected_objects if obj != context.object)

    for obj in ordered:
        if obj.type == 'CAMERA':
            if CAMERA_TAG in obj and cameraIsVisible(obj):
                # selecting a card camera is asking to look through that one
                return obj
            break
        camera = cameraForObject(scene, obj)
        if camera is None:
            continue
        if cameraIsVisible(camera):
            return camera
        break

    # nothing selected offers a visible camera. Step in only when what the scene
    # is looking through has been hidden too, which is the case that leaves the
    # viewport framed on something the user cannot see
    current = scene.camera
    if current is not None and CAMERA_TAG in current and not cameraIsVisible(current):
        return next((camera for camera in cameras if cameraIsVisible(camera)), None)
    return None


def createCardCamera(context, unit_id, faction, target, settings, add_sun=True):
    """Build (or refresh) the camera - and its lamp - that frames one unit.

    Every camera is the same pose slid along X onto its unit, which is the framing
    the game's cards use. Each one keeps its own lamp so a single unit can be relit
    without touching the rest; the renderer hides all the other lamps while that unit
    is being rendered, because fifty of them stacked on one scene would blow every
    card out.

    Projection, zoom and where the lamp stands all come off `settings` - see
    placeCardCamera and placeCardLight, which are also what the panel's live sliders
    drive through refreshCardCameras.
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
    distance = placeCardCamera(camera, settings, cameraPivot(target.matrix_world.translation.x))
    # applied on a refresh too, not just on a new camera: one built under an
    # earlier card size is still carrying that size's guide alignment, and a
    # Refresh is how the user is expected to repair it
    applyCameraGuide(camera.data, cardResolution(context.scene.med2_toolkit_cards))
    camera.data.show_background_images = True

    sun = cardLightOf(camera)
    if add_sun:
        if sun is None:
            sun_data = bpy.data.lights.new(name + " Sun", type=settings.light_type)
            sun = bpy.data.objects.new(name + " Sun", sun_data)
            context.scene.collection.objects.link(sun)
            sun.parent = camera
        linkBeside(sun, target, context)
        sun[SUN_TAG] = unit_id
        sun.data.type = settings.light_type
        sun.data.energy = settings.sun_strength
        # a lamp with some size to it softens the shadow edge. Only the lamp types
        # that have a size carry the property at all
        if hasattr(sun.data, 'shadow_soft_size'):
            sun.data.shadow_soft_size = LIGHT_RADIUS
        # parented to the camera, so one placement lights every unit identically
        # however far along X that unit stands
        placeCardLight(camera, settings, distance)
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


def applyRenderSettings(context, results=None):
    """Push the card settings onto the scene. Returns (width, height, supersample).

    `results` collects anything worth telling the user about the render mode - which
    engine it landed on, a view transform this Blender does not have, a world it
    would not overwrite. Left out when the caller has nowhere to show them.
    """
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
    applyRenderMode(context, results)
    # the line art radius is derived from the card size and zoom, both of which
    # can have moved since the outline objects were made
    refreshLineArt(context)
    return width, height, supersample


def applyRenderMode(context, results=None):
    """Point the scene at the engine and the look the card settings ask for.

    Solid is Workbench and needs nothing else - no lamp, no world, no tone mapping
    worth speaking of. Rendered is EEVEE set up the way gondor_infantry.blend and
    unit_card_blendfile.blend are: ambient occlusion on, shadows on, a flat grey world
    for fill, and an explicitly chosen view transform rather than whatever this
    Blender happens to default to.
    """
    scene = context.scene
    settings = scene.med2_toolkit_cards
    collect = results if results is not None else []
    if settings.render_mode == 'SOLID':
        engine = setRenderEngine(scene, (WORKBENCH_ENGINE,))
        if engine is None:
            collect.append(('WARNING', "This Blender has no Workbench engine, so Solid mode could not "
                                       "be set - the cards render with whatever engine the scene is on"))
            return
        step = applySolidShading(scene, settings)
        light = dict((item[0], item[1]) for item in SOLID_LIGHTING).get(settings.solid_light, settings.solid_light)
        colour = dict((item[0], item[1]) for item in SOLID_COLOURS).get(settings.solid_colour, settings.solid_colour)
        collect.append(('INFO', "Solid mode: Workbench, %s lighting on %s colour, %s samples of "
                                "anti-aliasing" % (light.lower(), colour.lower(), step)))
        # Workbench does its own thing with colour, but the view transform still sits
        # on the end of it, so it is worth setting here too
        reason = applyViewTransform(scene, settings.view_transform)
        if reason is not None:
            collect.append(('WARNING', reason))
        return

    engine = setRenderEngine(scene, EEVEE_ENGINES)
    if engine is None:
        collect.append(('WARNING', "This Blender has no EEVEE engine, so the cards render with "
                                   "whatever engine the scene is on"))
    try:
        scene.eevee.taa_render_samples = settings.render_samples
    except AttributeError:
        pass
    if hasattr(getattr(scene, 'eevee', None), 'use_shadows'):
        scene.eevee.use_shadows = True
    elif hasattr(getattr(scene, 'eevee', None), 'use_soft_shadows'):
        scene.eevee.use_soft_shadows = True
    reason = applyViewTransform(scene, settings.view_transform)
    if reason is not None:
        collect.append(('WARNING', reason))
    elif settings.view_transform != 'KEEP':
        collect.append(('INFO', "Rendering through the %s view transform" % settings.view_transform))
    applyAmbientOcclusion(scene, settings.use_ambient_occlusion, settings.ao_distance)
    if settings.use_ambient_occlusion:
        collect.append(('INFO', "Ambient occlusion on at %.1f - the shadow under a helmet rim and "
                                "inside a collar, which is what keeps a 48x64 card from flattening"
                                % settings.ao_distance))
    if settings.use_world_ambient:
        reason = applyWorldAmbient(scene, settings.world_ambient)
        if reason is not None:
            collect.append(('WARNING', reason))
        else:
            collect.append(('INFO', "World fill light at %.3f grey - off the card itself, since the "
                                    "film is transparent, but it lifts the unlit side of the unit"
                                    % settings.world_ambient))


def setupCardScene(context, rebuild=False, targets=None):
    """Compositor, render settings and the line art outlines. Cameras are made
    per unit by createCardCameras, so this stays independent of what is in the
    scene - bar the outlines, which need to know which collections to cover."""
    settings = context.scene.med2_toolkit_cards
    results = []
    _group, compositor_results = setupCompositor(context, rebuild)
    results.extend(compositor_results)
    width, height, supersample = applyRenderSettings(context, results)
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


def createCardCameras(context, targets, settings, add_sun=True, control_rig_type=None,
                      lift_sunken=True):
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
        _camera, is_new = createCardCamera(context, unit_id, faction, model, settings, add_sun)
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
    projection = dict((item[0], item[1]) for item in CAMERA_PROJECTIONS).get(settings.camera_projection,
                                                                              settings.camera_projection)
    if settings.camera_projection == 'PERSP':
        results.append(('INFO', "%s cameras: %.0fmm lens, standing %.2f from the unit to frame %.2f"
                                % (projection, settings.camera_lens, framingDistance(settings),
                                   settings.card_zoom)))
    else:
        results.append(('INFO', "%s cameras framing %.2f world units" % (projection, settings.card_zoom)))
    if add_sun:
        label = dict((item[0], item[1]) for item in CARD_LIGHT_TYPES).get(settings.light_type,
                                                                          settings.light_type)
        results.append(('INFO', "Each camera carries a %.1f strength %s light %.1f back from the unit, "
                                "%.0f deg above the view axis and %.0f deg round to the side"
                                % (settings.sun_strength, label.lower(), settings.light_distance,
                                   settings.light_elevation, settings.light_azimuth)))
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
    dds = gameTexturePath(source_path)
    for path in paths or ():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            shutil.copyfile(source_path, path)
            if os.path.isfile(dds):
                shutil.copyfile(dds, gameTexturePath(path))
        except OSError as error:
            return "Could not copy the card to %s: %s" % (os.path.dirname(path), error)
    return None


def widenCamera(camera, frame_span, card_zoom):
    """Re-frame a card camera onto `frame_span` world units across its longer side,
    and hand back what to put it back to.

    An orthographic camera carries that number directly. A perspective one keeps its
    place and changes lens instead: moving it would change the foreshortening the card
    was composed with, and lens is exact anyway - the camera stands
    card_zoom*lens/sensor from the pivot, so framing `frame_span` from there wants
    lens*card_zoom/frame_span. On an HD size that frames the same shape as the card,
    frame_span equals card_zoom and neither is touched.
    """
    if camera is None or frame_span <= 0:
        return None
    data = camera.data
    if data.type == 'PERSP':
        previous = ('lens', data.lens)
        data.lens = data.lens*card_zoom/frame_span
        return previous
    previous = ('ortho_scale', data.ortho_scale)
    data.ortho_scale = frame_span
    return previous


def restoreCamera(camera, previous):
    """Put back what widenCamera changed."""
    if camera is None or previous is None:
        return
    setattr(camera.data, previous[0], previous[1])


def saveHDRender(context, camera, hd_path, width, height, frame_span):
    """Render the same camera again at HD size and save it as a PNG.

    A second pass rather than a scale-up of the card render: the card is 48x64 and no
    amount of resampling puts detail back. The camera is widened for the pass and put
    back afterwards, for the HD sizes that frame a different shape than the card does
    - see hdOrthoScale and widenCamera. The compositor's rescale is switched off for
    the pass as well, since this render is wanted at its own resolution rather than
    shrunk to card size - and so is the smoothing blur, which is there to keep the
    card's nearest-neighbour downscale from crawling and at HD size only costs detail.
    """
    scene = context.scene
    render = scene.render
    previous = (render.resolution_x, render.resolution_y)
    previous_framing = widenCamera(camera, frame_span, scene.med2_toolkit_cards.card_zoom)
    previous_rescale = setRescale(scene, 1.0)
    previous_blur = setBlur(scene, False)
    render.resolution_x = width
    render.resolution_y = height
    try:
        context.view_layer.update()
        bpy.ops.render.render(write_still=False)
        render_result = bpy.data.images.get('Render Result')
        if render_result is None:
            return "Blender produced no HD render"
        return saveFullSize(context, render_result, hd_path)
    finally:
        render.resolution_x, render.resolution_y = previous
        restoreCamera(camera, previous_framing)
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
        # the game reads <card>.tga.dds whenever it is there, so the card goes
        # out as that plus an empty .tga - the TGA Optimizer's layout. A failed
        # conversion leaves a full .tga, which the game reads just as well
        _dds, warning = writeTgaDds(entry['path'])
        if warning is not None:
            entry['warning'] = warning
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
    # the card's .tga is the empty placeholder once its .tga.dds is written
    paths = [viewablePath(entry['path']) if entry.get('path') else None, entry.get('hd_path'), entry.get('full_path')]
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
