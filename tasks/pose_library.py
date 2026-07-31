"""Bundled pose asset library: registration, catalog lookup, the asset browser
area the pose tools open alongside the viewport, and applying a pose asset to a
rig."""

import bpy
import re
from pathlib import Path

from .control_rig import controlRigOf, controlledRigs

script_folder = Path(__file__).parent.parent
ASSET_FOLDER = script_folder/'assets'
CATALOG_FILE = 'blender_assets.cats.txt'

LIBRARY_NAME = "Medieval 2 Poses"
# catalog the pose browser opens on, and the root every pose catalog lives under
DEFAULT_CATALOG = "Poses/IK Full"
CATALOG_ROOT = "Poses"

# Areas this addon split off, by as_pointer(). Only these get closed again -
# an asset browser the user opened themselves is left alone.
_opened_areas = set()


#   -------------------  #
#   Library registration  #
#   -------------------  #

def libraryPath():
    return str(ASSET_FOLDER)


def libraryAvailable():
    return (ASSET_FOLDER/CATALOG_FILE).exists()


def registeredLibrary():
    """The preferences entry for our library, if it is already there."""
    for library in bpy.context.preferences.filepaths.asset_libraries:
        if library.name == LIBRARY_NAME:
            return library
    return None


def ensureAssetLibrary():
    """Point a user asset library at the bundled pose assets. Idempotent, and
    safe to call again after the addon folder moves (a reinstall lands on a new
    path when Blender's version folder changes)."""
    if not libraryAvailable():
        return ('WARNING', "No pose assets bundled with the addon (%s is missing)" % ASSET_FOLDER)
    path = libraryPath()
    library = registeredLibrary()
    if library is None:
        library = bpy.context.preferences.filepaths.asset_libraries.new(name=LIBRARY_NAME, directory=path)
        return ('INFO', "Registered the '%s' asset library" % LIBRARY_NAME)
    if bpy.path.native_pathsep(library.path.rstrip('\\/')) != bpy.path.native_pathsep(path.rstrip('\\/')):
        library.path = path
        return ('INFO', "Repointed the '%s' asset library at %s" % (LIBRARY_NAME, path))
    return ('INFO', "The '%s' asset library is already registered" % LIBRARY_NAME)


def registerLibraryDeferred():
    """register() runs too early to touch preferences reliably, so the library
    is added on the first pass of the event loop instead."""
    def run():
        try:
            ensureAssetLibrary()
        except Exception as error:
            print("Medieval 2 Toolkit: could not register the pose asset library:", error)
        return None
    bpy.app.timers.register(run, first_interval=0)


#   --------  #
#   Catalogs  #
#   --------  #

def readCatalogs():
    """[(uuid, catalog path, simple name)] from the bundled catalog file, in
    file order. Blank/comment/VERSION lines are skipped."""
    catalog_path = ASSET_FOLDER/CATALOG_FILE
    catalogs = []
    try:
        with open(catalog_path, 'r', encoding='utf-8') as catalog_file:
            lines = catalog_file.readlines()
    except OSError:
        return catalogs
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('VERSION'):
            continue
        parts = line.split(':')
        if len(parts) < 2:
            continue
        catalogs.append((parts[0], parts[1], parts[2] if len(parts) > 2 else parts[1]))
    return catalogs


def poseCatalogs():
    """Catalogs under the Poses root - the ones a new pose can go into."""
    return [entry for entry in readCatalogs()
            if entry[1] == CATALOG_ROOT or entry[1].startswith(CATALOG_ROOT + '/')]


def catalogUUID(catalog_path):
    for uuid, path, _simple in readCatalogs():
        if path == catalog_path:
            return uuid
    return ""


#   ---------------------  #
#   Asset browser plumbing  #
#   ---------------------  #

def poseBrowserArea(context):
    """An open asset browser showing our library, or None."""
    screen = context.window.screen if context.window else None
    if screen is None:
        return None
    for area in screen.areas:
        if area.ui_type != 'ASSETS':
            continue
        params = area.spaces.active.params
        if params is not None and params.asset_library_reference == LIBRARY_NAME:
            return area
        if area.as_pointer() in _opened_areas:
            return area
    return None


def configureBrowser(area, catalog_path):
    """Point a freshly split asset browser at our library and catalog.

    `space.params` does not exist until the area has drawn once, so this is
    retried from a timer rather than run inline.
    """
    space = area.spaces.active

    def run():
        params = space.params
        if params is None:
            return 0.05
        try:
            params.asset_library_reference = LIBRARY_NAME
            if catalog_path:
                uuid = catalogUUID(catalog_path)
                if uuid:
                    params.catalog_id = uuid
        except (AttributeError, TypeError) as error:
            print("Medieval 2 Toolkit: could not set up the pose browser:", error)
            return None
        for window in bpy.context.window_manager.windows:
            if area in list(window.screen.areas):
                with bpy.context.temp_override(window=window, screen=window.screen, area=area):
                    bpy.ops.asset.library_refresh()
                break
        return None

    bpy.app.timers.register(run, first_interval=0.05)


def openPoseBrowser(context, catalog_path=DEFAULT_CATALOG, factor=0.3):
    """Split the current 3D viewport and turn the new area into an asset browser
    showing the pose library. Returns (area, message)."""
    existing = poseBrowserArea(context)
    if existing is not None:
        configureBrowser(existing, catalog_path)
        return existing, "Pose library browser is already open"
    if context.window is None:
        return None, "No window to split"
    screen = context.window.screen
    source = context.area if context.area is not None and context.area.type == 'VIEW_3D' else None
    if source is None:
        source = next((area for area in screen.areas if area.type == 'VIEW_3D'), None)
    if source is None:
        return None, "No 3D viewport to split"
    before = {area.as_pointer() for area in screen.areas}
    with context.temp_override(window=context.window, screen=screen, area=source):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=factor)
    new_area = next((area for area in screen.areas if area.as_pointer() not in before), None)
    if new_area is None:
        return None, "Blender did not split the viewport"
    # area_split puts the new area on the left, which is where the pose browser
    # belongs - the viewport keeps the larger right-hand share
    new_area.ui_type = 'ASSETS'
    _opened_areas.add(new_area.as_pointer())
    configureBrowser(new_area, catalog_path)
    return new_area, "Opened the pose library browser"


def closePoseBrowser(context):
    """Close the pose browser, but only one this addon opened."""
    area = poseBrowserArea(context)
    if area is None:
        return False
    if area.as_pointer() not in _opened_areas:
        # the user opened this one themselves; leave their layout alone
        return False
    _opened_areas.discard(area.as_pointer())
    with context.temp_override(window=context.window, screen=context.window.screen, area=area):
        bpy.ops.screen.area_close()
    return True


def refreshPoseBrowser(context):
    area = poseBrowserArea(context)
    if area is None:
        return
    with context.temp_override(window=context.window, screen=context.window.screen, area=area):
        bpy.ops.asset.library_refresh()


#   -------  --------  #
#   Armature resolution  #
#   -------  --------  #

def activeArmature(context):
    """The rig the pose buttons act on: the active object when it is an armature,
    otherwise a selected one, otherwise the armature a selected mesh is parented
    to."""
    active = context.active_object
    if active is not None and active.type == 'ARMATURE':
        return active
    for obj in context.selected_objects:
        if obj.type == 'ARMATURE':
            return obj
    for obj in context.selected_objects:
        if obj.parent is not None and obj.parent.type == 'ARMATURE':
            return obj.parent
    return None


def candidateArmatures(context):
    """Every rig a pose could reasonably land on, most likely first.

    Around three quarters of the bundled poses animate the IK control rig, not a
    Medieval 2 skeleton, so a selected unit has to offer its controller as well -
    and a selected controller has to offer the units it drives, for the handful
    of poses written against Med2 bone names.
    """
    candidates = []

    def add(obj):
        if obj is not None and obj.type == 'ARMATURE' and obj not in candidates:
            candidates.append(obj)

    ordered = []
    active = context.active_object
    if active is not None:
        ordered.append(active)
    ordered.extend(context.selected_objects)
    for obj in ordered:
        if obj.type == 'ARMATURE':
            add(obj)
        elif obj.parent is not None and obj.parent.type == 'ARMATURE':
            add(obj.parent)
    for rig in list(candidates):
        add(controlRigOf(rig))
        for driven in controlledRigs(rig):
            add(driven)
    return candidates


#   ------------  #
#   Pose applying  #
#   ------------  #

POSE_BONE_PATH = re.compile(r'pose\.bones\["([^"]+)"\]')


def actionFCurves(action):
    """Every fcurve of an action, whatever era it comes from.

    Only the layered API is walked for slotted actions: reading `Action.fcurves`
    on a slotted action that came out of `BlendData.temp_data()` takes Blender
    5.1 down with an access violation, so the legacy shim is only touched on
    actions that really are legacy.
    """
    if getattr(action, 'is_action_legacy', False):
        for fcurve in action.fcurves:
            yield fcurve
        return
    for layer in getattr(action, 'layers', ()):
        for strip in layer.strips:
            for channelbag in getattr(strip, 'channelbags', ()):
                for fcurve in channelbag.fcurves:
                    yield fcurve


def actionBoneNames(action):
    """The bones an action animates."""
    names = set()
    for fcurve in actionFCurves(action):
        match = POSE_BONE_PATH.match(fcurve.data_path)
        if match:
            names.add(match.group(1))
    return names


def poseTarget(candidates, bone_names):
    """Pick the rig a pose fits best: the one sharing the most bone names with
    it. Returns (armature, matched names, unmatched names)."""
    best = None
    best_matched = set()
    for armature in candidates:
        matched = bone_names & set(armature.pose.bones.keys())
        if best is None or len(matched) > len(best_matched):
            best, best_matched = armature, matched
    if best is None:
        return None, set(), bone_names
    return best, best_matched, bone_names - best_matched


def animatedActions(armature):
    """Actions driving a rig: the assigned one plus anything in its NLA."""
    animation = armature.animation_data
    if animation is None:
        return []
    actions = []
    if animation.action is not None:
        actions.append(animation.action)
    for track in animation.nla_tracks:
        for strip in track.strips:
            if strip.action is not None and strip.action not in actions:
                actions.append(strip.action)
    return actions


def keyframeCount(action):
    return sum(len(fcurve.keyframe_points) for fcurve in actionFCurves(action))


def animationSummary(armature):
    """(action names, keyframe total, animated bone names) for a rig, or None
    when it carries no animation."""
    actions = animatedActions(armature)
    if not actions:
        return None
    keyframes = 0
    bones = set()
    for action in actions:
        keyframes += keyframeCount(action)
        bones |= actionBoneNames(action)
    if keyframes == 0:
        return None
    return [action.name for action in actions], keyframes, bones


def clearAnimation(armature):
    """Strip every keyframe off the actions driving a rig, unassign them and
    return the pose bones they drove to rest.

    The keyframes really are deleted from the Action datablocks, not just
    unlinked - that is what "overwrite the animation" was asked for, and it is
    why the operator warns first.
    """
    summary = animationSummary(armature)
    if summary is None:
        return None
    names, keyframes, bones = summary
    for action in animatedActions(armature):
        if getattr(action, 'is_action_legacy', False):
            for fcurve in list(action.fcurves):
                action.fcurves.remove(fcurve)
        else:
            # dropping the layers takes every strip, channelbag and fcurve with
            # them, which is the only wipe that works on a slotted action
            for layer in list(action.layers):
                action.layers.remove(layer)
    armature.animation_data_clear()
    # bones the animation was driving would otherwise freeze at whatever the
    # current frame last evaluated to; the pose is applied on top of rest
    for bone_name in bones:
        pose_bone = armature.pose.bones.get(bone_name)
        if pose_bone is not None:
            pose_bone.matrix_basis.identity()
    return names, keyframes, len(bones)


def withAssetAction(asset, work):
    """Run `work(action)` on the Action an asset points at, loading it out of the
    library file when it does not already live in this blend."""
    local = asset.local_id
    if local is not None:
        return work(local)
    library_path = asset.full_library_path
    if not library_path:
        return None
    with bpy.types.BlendData.temp_data() as temp_data:
        with temp_data.libraries.load(library_path) as (_data_from, data_to):
            data_to.actions = [asset.name]
        if not data_to.actions or data_to.actions[0] is None:
            return None
        return work(data_to.actions[0])


def applyPoseAction(armature, action):
    """Set the rig's pose from an action. Works in object mode as well as pose
    mode, which is what makes double-clicking a pose useful without a mode
    switch first."""
    armature.pose.apply_pose_from_action(action)
