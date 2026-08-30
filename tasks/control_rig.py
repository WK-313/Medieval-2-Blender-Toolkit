"""IK control rigs for Medieval 2 skeletons.

Port of the v0.9.20.4 toolkit's IK_2H.py / IK_Archer.py / IK_Dwarf.py plus
EDU_converter's `transfer_armature` and `create_controller`, which never made it
into the merged addon - the bundled pose library is almost entirely built for
these rigs (of the 231 pose assets, ~180 animate `IK Pelvis`, `IK frist  left`,
`Pole`, `Switch`, ... - bone names that exist on the controller and nowhere on a
Med2 skeleton), so without a controller most of the library applies to nothing.

The bone layout is data in control_rig_data.py; this module raises it and wires
up the constraints and drivers. Three changes to the original:

* The rig is built through bpy.data instead of `bpy.ops.object.armature_add`,
  so it does not depend on the current mode, selection or active collection.
* Bone collections are created explicitly, since a hand-built armature has none
  (the old code renamed the default collection `armature_add` had left behind).
* `linkToControlRig` only constrains a Med2 bone when the controller actually has
  a bone of that name. The old version constrained every non-weapon bone, which
  left dangling Copy Transforms constraints on rigs carrying bones the controller
  does not model (bone_weapon_group04 is the common one) - those show up as
  depsgraph "Failed to add relation" errors on every file load.
"""

import bpy
import math
from mathutils import Matrix

from .control_rig_data import COLLECTIONS, RIGS
from .recurlayercollection import collectionsOf, linkBeside

# (identifier, label, description). The identifiers are the old toolkit's, so a
# user following the old workflow picks the same entry by the same name.
CONTROL_RIG_TYPES = [
    ('infantry', "IK_Infantry", "Standard human skeleton: the 2H/1H/spear/polearm rig"),
    ('archer', "IK_Archer", "Bowman skeleton - the Pole bone is replaced by IK Bow String"),
    ('dwarf', "IK_Dwarf", "Short skeleton used by dwarves and hobbits"),
]

# Marks a controller and records which layout it was built from.
RIG_TAG = "med2_control_rig"

CONTROLLER_SUFFIX = " Controller"

# Bones that must keep following the Med2 animation rather than the controller,
# same rule the old transfer_armature used.
WEAPON_BONE_MARKERS = ("weapon", "Weapon")


def setRigHidden(armature, hidden):
    """Show or hide a Med2 skeleton in the viewport. Its meshes are children of
    the object, not of its data, so hiding the armature leaves the unit itself
    on screen. Returns True when the eye was actually toggled - an object that
    is not in the current view layer has none, and that is not an error."""
    if armature is None:
        return False
    try:
        armature.hide_set(hidden)
    except RuntimeError:
        return False
    return True


def rigTypeLabel(rig_type):
    for identifier, label, _description in CONTROL_RIG_TYPES:
        if identifier == rig_type:
            return label
    return rig_type


#   ------------  #
#   Rig detection  #
#   ------------  #

def isControlRig(obj):
    return obj is not None and obj.type == 'ARMATURE' and RIG_TAG in obj


def controlRigOf(armature):
    """The controller driving `armature`, or None. The controller is the rig's
    parent, which is how create_controller has always hooked the two together."""
    if armature is None:
        return None
    if isControlRig(armature):
        return armature
    parent = armature.parent
    if isControlRig(parent):
        return parent
    return None


def controlledRigs(controller):
    """The Med2 skeletons a controller drives."""
    if not isControlRig(controller):
        return []
    return [child for child in controller.children if child.type == 'ARMATURE']


def controlRigMatchCount(armature, rig_type):
    """How many of a skeleton's bones a controller layout actually models.

    Zero means a controller would drive nothing at all - a horse, a catapult or
    a ship shares no bone name with a Medieval 2 human skeleton. That is how the
    group pass in unit_groups tells a mount apart from the riders sitting on it
    without having to build a controller first to find out.
    """
    if armature is None or armature.type != 'ARMATURE' or rig_type not in RIGS:
        return 0
    layout = {bone[0] for bone in RIGS[rig_type]}
    return sum(1 for pose_bone in armature.pose.bones
               if pose_bone.name in layout
               and not any(marker in pose_bone.name for marker in WEAPON_BONE_MARKERS))


#   ---------  #
#   Rig build  #
#   ---------  #

def buildControlRig(context, name, location, rig_type, beside=None):
    """Create the IK controller armature itself, unparented and unconstrained.

    Built entirely through bpy.data so it works in any mode, including headless.
    `beside` is the object whose collections the controller should join, so a
    unit that lives in its own collection gets its controller there too.
    Returns the new armature object.
    """
    bones = RIGS[rig_type]
    armature_data = bpy.data.armatures.new(name)
    armature_data.display_type = 'STICK'
    controller = bpy.data.objects.new(name, armature_data)
    controller[RIG_TAG] = rig_type
    controller.show_in_front = True
    controller.location = location
    for collection in collectionsOf(beside, context):
        collection.objects.link(controller)

    for collection_name, visible in COLLECTIONS:
        collection = armature_data.collections.new(collection_name)
        collection.is_visible = visible

    previous_active = context.view_layer.objects.active
    previous_mode = previous_active.mode if previous_active is not None else 'OBJECT'
    if previous_active is not None and previous_active.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    context.view_layer.objects.active = controller
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        edit_bones = armature_data.edit_bones
        for bone_name, head, tail, roll, connect, parent, collection_name in bones:
            bone = edit_bones.new(bone_name)
            bone.head = head
            bone.tail = tail
            bone.roll = roll
            bone.use_connect = False
            if parent is not None:
                bone.parent = edit_bones[parent]
                bone.use_connect = connect
            if collection_name:
                armature_data.collections[collection_name].assign(bone)
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')
    if previous_active is not None:
        context.view_layer.objects.active = previous_active
        if previous_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=previous_mode)
            except RuntimeError:
                pass
    return controller


def switchDriver(controller, data_path):
    """Drive a constraint's influence off the Switch bone's Y position: pushing
    the Switch bone forward turns the constraint on. Straight from the original."""
    fcurve = controller.driver_add(data_path)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    driver.expression = "1 if (var > 0) else 0"
    variable = driver.variables.new()
    variable.name = "var"
    variable.type = 'TRANSFORMS'
    variable.targets[0].id = controller
    variable.targets[0].bone_target = "Switch"
    variable.targets[0].transform_type = 'LOC_Y'
    variable.targets[0].transform_space = 'TRANSFORM_SPACE'
    return fcurve


def addRigConstraints(controller, rig_type):
    """IK chains, limits and the Switch drivers. Identical between the infantry
    and dwarf layouts; the archer swaps the left-hand Pole block for one that
    pins the bow string to bone_sling."""
    pose_bones = controller.pose.bones

    for side, angle_bone, knee_bone in (("right", "IK angle right", "IK knee right"),
                                        ("left", "IK angle left", "IK knee left")):
        constraint = pose_bones['IK calf %s' % side].constraints.new('IK')
        constraint.target = controller
        constraint.subtarget = angle_bone
        constraint.pole_target = controller
        constraint.pole_subtarget = knee_bone
        constraint.chain_count = 2
        constraint.pole_angle = math.pi/2

    constraint = pose_bones['IK Torso'].constraints.new('IK')
    constraint.target = controller
    constraint.subtarget = "IK Torso Controller"
    constraint.chain_count = 2

    constraint = pose_bones['IK Torso'].constraints.new('COPY_ROTATION')
    constraint.target = controller
    constraint.subtarget = "IK Torso Controller"

    if rig_type == 'archer':
        # the bow string follows the sling bone instead of the missing Pole
        constraint = pose_bones['IK Bow String'].constraints.new('COPY_LOCATION')
        constraint.target = controller
        constraint.subtarget = "bone_sling"
        switchDriver(controller, 'pose.bones["IK Bow String"].constraints["Copy Location"].influence')
    else:
        constraint = pose_bones['IK frist  left'].constraints.new('COPY_LOCATION')
        constraint.target = controller
        constraint.subtarget = "Pole"
        constraint.head_tail = 1
        switchDriver(controller, 'pose.bones["IK frist  left"].constraints["Copy Location"].influence')

        constraint = pose_bones['IK frist  left'].constraints.new('COPY_ROTATION')
        constraint.target = controller
        constraint.subtarget = "Pole"
        switchDriver(controller, 'pose.bones["IK frist  left"].constraints["Copy Rotation"].influence')

    constraint = pose_bones['IK lower arm right'].constraints.new('IK')
    constraint.target = controller
    constraint.subtarget = "IK frist right"
    constraint.pole_target = controller
    constraint.pole_subtarget = "IK elbow right"
    constraint.chain_count = 2
    constraint.pole_angle = 0

    constraint = pose_bones['IK lower arm left'].constraints.new('IK')
    constraint.target = controller
    constraint.subtarget = "IK frist  left"
    constraint.pole_target = controller
    constraint.pole_subtarget = "IK elbow left"
    constraint.chain_count = 2
    constraint.pole_angle = math.pi

    constraint = pose_bones['IK Head'].constraints.new('LIMIT_ROTATION')
    constraint.use_limit_x = True
    constraint.min_x = -0.959931
    constraint.max_x = 0.436332
    constraint.use_limit_y = True
    constraint.min_y = -0.785398
    constraint.max_y = 0.785398
    constraint.use_limit_z = True
    constraint.min_z = -1.39626
    constraint.max_z = 1.39626
    constraint.owner_space = 'LOCAL'

    constraint = pose_bones['IK Torso Controller'].constraints.new('LIMIT_ROTATION')
    constraint.use_limit_x = True
    constraint.min_x = 0
    constraint.max_x = 0
    constraint.use_limit_y = True
    constraint.min_y = 0
    constraint.max_y = 0
    constraint.use_limit_z = True
    constraint.min_z = -math.pi/2
    constraint.max_z = math.pi/2
    constraint.owner_space = 'LOCAL'

    switch = pose_bones['Switch']
    switch.lock_location[0] = True
    switch.lock_location[2] = True
    constraint = switch.constraints.new('LIMIT_LOCATION')
    constraint.use_min_y = True
    constraint.use_max_y = True
    constraint.min_y = -0.05
    constraint.max_y = 0.05
    constraint.owner_space = 'LOCAL'


def linkToControlRig(armature, controller):
    """Give every Med2 bone a Copy Transforms constraint pointing at the
    controller's matching bone. Returns (linked, skipped weapon bones, bones the
    controller has no counterpart for)."""
    controller_bones = set(controller.pose.bones.keys())
    linked = 0
    weapons = 0
    unmatched = []
    for pose_bone in armature.pose.bones:
        if any(marker in pose_bone.name for marker in WEAPON_BONE_MARKERS):
            # weapon bones stay free so props can be posed by hand
            weapons += 1
            continue
        if pose_bone.name not in controller_bones:
            unmatched.append(pose_bone.name)
            continue
        if any(constraint.type == 'COPY_TRANSFORMS' and constraint.target == controller
               for constraint in pose_bone.constraints):
            continue
        constraint = pose_bone.constraints.new('COPY_TRANSFORMS')
        constraint.target = controller
        constraint.subtarget = pose_bone.name
        constraint.target_space = 'LOCAL_WITH_PARENT'
        constraint.owner_space = 'LOCAL_WITH_PARENT'
        linked += 1
    return linked, weapons, unmatched


def unlinkFromControlRig(armature, controller):
    """Strip the Copy Transforms constraints a controller put on a rig."""
    removed = 0
    for pose_bone in armature.pose.bones:
        for constraint in list(pose_bone.constraints):
            if constraint.type == 'COPY_TRANSFORMS' and constraint.target == controller:
                pose_bone.constraints.remove(constraint)
                removed += 1
    return removed


def createControlRig(context, armature, rig_type):
    """Build a controller for `armature`, constrain the rig to it and parent the
    rig under it. Returns (controller, results) - results being the usual
    (level, message) pairs the panels feed into their popups."""
    results = []
    if armature is None or armature.type != 'ARMATURE':
        return None, [('ERROR', "Select the unit's armature first")]
    existing = controlRigOf(armature)
    if existing is not None:
        return existing, [('WARNING', "'%s' already has the control rig '%s'" % (armature.name, existing.name))]
    if rig_type not in RIGS:
        return None, [('ERROR', "Unknown control rig type '%s'" % rig_type)]

    name = armature.name + CONTROLLER_SUFFIX
    controller = buildControlRig(context, name, armature.matrix_world.translation, rig_type, beside=armature)
    addRigConstraints(controller, rig_type)
    linked, weapons, unmatched = linkToControlRig(armature, controller)

    armature.parent = controller
    armature.matrix_parent_inverse = controller.matrix_world.inverted()

    # The Med2 skeleton is only driven from here on - every bone of it that the
    # controller models is constrained to the controller's - so it is in the way
    # of clicking the controller bones. Hide it; deleteControlRig brings it back.
    setRigHidden(armature, True)

    results.append(('INFO', "Built '%s' (%s) and linked %d bone(s)" % (controller.name, rigTypeLabel(rig_type), linked)))
    if weapons:
        results.append(('INFO', "Left %d weapon bone(s) free so props can still be posed by hand" % weapons))
    if unmatched:
        preview = ", ".join(unmatched[:4])
        if len(unmatched) > 4:
            preview += ", ..."
        results.append(('WARNING', "%d bone(s) have no counterpart on the controller and were left alone: %s"
                        % (len(unmatched), preview)))
    if linked == 0:
        results.append(('ERROR', "None of '%s' bones matched the controller - is it a Medieval 2 skeleton?" % armature.name))
    return controller, results


def deleteControlRig(controller):
    """Remove a controller, un-parenting and un-constraining its rigs first."""
    if not isControlRig(controller):
        return 0
    rigs = controlledRigs(controller)
    for rig in rigs:
        unlinkFromControlRig(rig, controller)
        world_matrix = rig.matrix_world.copy()
        rig.parent = None
        rig.matrix_parent_inverse = Matrix.Identity(4)
        rig.matrix_world = world_matrix
        # nothing drives it any more, so it is the thing to pose again
        setRigHidden(rig, False)
    bpy.data.objects.remove(controller, do_unlink=True)
    return len(rigs)
