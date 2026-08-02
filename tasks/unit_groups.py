"""Multi-armature units: a mount with its riders, a siege engine with its crew.

A mounted unit does not import as one armature. `unitImporter` brings the mount
in as the root and one further armature per crew member, parented under it - so
one "unit" is two, three or six rigs that everything downstream then has to
treat as a single thing: one entry in the imported models list, one card camera,
one isolation pass, but a control rig each.

Parenting on its own cannot carry that, because `createControlRig` parents a rig
UNDER its controller - giving a rider a controller lifts it straight out of the
mount's child tree. So the members are tagged as well: every object of a unit
carries the same GROUP_TAG id, the root carries ROOT_TAG too, and those survive
renaming, re-parenting, appending and saving. Untagged units (anything imported
before this existed, or built by hand) still resolve through the parenting, so
nothing has to be re-imported to benefit.
"""

import bpy
import uuid

from .control_rig import (controlRigMatchCount, controlRigOf, createControlRig,
                          isControlRig)

# Shared by every object of one unit - the mount and each of its riders.
GROUP_TAG = "med2_unit_group"
# On the root alone: the mount, or the engine.
ROOT_TAG = "med2_unit_group_root"
# What this armature is within the unit: "Mount", "Rider 1", "Engine", "Crew 2".
ROLE_TAG = "med2_unit_role"
# Import order, so the parts list back in the order the importer built them.
ORDER_TAG = "med2_unit_order"


def groupId(obj):
    return str(obj.get(GROUP_TAG, "")) if obj is not None else ""


def isGroupRoot(obj):
    return obj is not None and bool(obj.get(ROOT_TAG, False))


def unitRole(obj):
    return str(obj.get(ROLE_TAG, "")) if obj is not None else ""


def deriveRole(root, part, index):
    """A label for an untagged part: whatever its name adds to the root's.

    The importer names a mount's riders `<unit> Rider 1`, `<unit> Rider 2`, so
    trimming the root's name off leaves exactly the part name it would have been
    tagged with had it been imported by a toolkit that knew about groups.
    """
    name = part.name
    if root is not None and name.startswith(root.name):
        trimmed = name[len(root.name):].strip(" .-_")
        if trimmed:
            return trimmed
    return name or "Part %d" % index


def tagGroup(root, parts, root_role="Mount"):
    """Tie a root armature and its crew together. `parts` is [(object, role)].

    Returns the group id, which is what the import list entries store to find
    each other again.
    """
    if root is None:
        return ""
    group = groupId(root) or uuid.uuid4().hex[:12]
    root[GROUP_TAG] = group
    root[ROOT_TAG] = True
    root[ROLE_TAG] = root_role
    root[ORDER_TAG] = 0
    for index, (part, role) in enumerate(parts, start=1):
        if part is None or part is root:
            continue
        part[GROUP_TAG] = group
        part[ROLE_TAG] = role
        part[ORDER_TAG] = index
        if ROOT_TAG in part:
            del part[ROOT_TAG]
    return group


def taggedMembers(group):
    """Every object carrying a group id, root first then import order."""
    if not group:
        return []
    members = [obj for obj in bpy.data.objects if groupId(obj) == group]
    members.sort(key=lambda obj: (0 if isGroupRoot(obj) else 1,
                                  int(obj.get(ORDER_TAG, 0) or 0), obj.name))
    return members


# Both of the lookups below are called from panel draw() code, which Blender
# runs several times per redraw on a list that can hold a whole faction. They
# therefore answer from the PARENTING - a walk over one object's parents or
# children - and only fall back to taggedMembers, which reads every object in
# the file, when the parenting has genuinely been taken apart by hand.

def groupRoot(obj):
    """The armature a unit hangs off - the mount or the engine - or `obj` itself.

    The walk up steps over any control rig on the way: a controller is the rig's
    PARENT, so a plain walk would hand back the controller instead of the unit.
    """
    if obj is None:
        return None
    if isGroupRoot(obj):
        return obj
    root = obj
    parent = root.parent
    while parent is not None and parent.type == 'ARMATURE':
        if isControlRig(parent):
            parent = parent.parent
            continue
        root = parent
        parent = root.parent
    group = groupId(obj)
    if not group or groupId(root) == group:
        return root
    # tagged, but nothing above it carries the same id: a part somebody has
    # re-parented out of its unit
    for member in taggedMembers(group):
        if isGroupRoot(member):
            return member
    return root


def groupParts(obj):
    """Every armature that makes up one unit, root first.

    A single-armature unit is a group of one, so no caller has to special-case
    it. The crew are the armature children of the root and - once they have
    controllers of their own - the armature grandchildren through those, which
    is why the walk steps through a control rig instead of stopping at it.
    """
    root = groupRoot(obj)
    if root is None:
        return []
    parts = [root]
    for child in root.children:
        if child.type != 'ARMATURE':
            continue
        if isControlRig(child):
            parts.extend(rig for rig in child.children
                         if rig.type == 'ARMATURE' and not isControlRig(rig) and rig not in parts)
        elif child not in parts:
            parts.append(child)
    if len(parts) == 1 and isGroupRoot(root):
        # tagged as carrying a crew, but nothing is parented under it any more -
        # a rider moved out by hand. The tags are the only way back, and this is
        # the one path that pays for a scan of the whole file.
        members = [member for member in taggedMembers(groupId(root)) if member.type == 'ARMATURE']
        if members:
            return members
    crew = sorted(parts[1:], key=lambda part: (int(part.get(ORDER_TAG, 0) or 0), part.name))
    return [root] + crew


def isMultiPart(obj):
    return len(groupParts(obj)) > 1


def adoptGroup(root):
    """Tag an untagged multi-part unit so its parts survive being given control
    rigs. Returns the group id, or "" when there is nothing to group."""
    parts = groupParts(root)
    if len(parts) < 2:
        return groupId(root)
    root = parts[0]
    if groupId(root) and isGroupRoot(root):
        return groupId(root)
    labelled = [(part, unitRole(part) or deriveRole(root, part, index))
                for index, part in enumerate(parts[1:], start=1)]
    return tagGroup(root, labelled, unitRole(root) or "Mount")


#   -----------------------  #
#   Control rigs for a unit   #
#   -----------------------  #

def createGroupControlRigs(context, target, rig_type):
    """Build an IK controller for every human armature of a unit, in one pass.

    A mounted unit is a horse carrying one or more riders, and only the riders
    are Medieval 2 human skeletons - so a member sharing no bone name with the
    controller layout is left alone rather than given a controller that would
    drive nothing. (A unit that is a single armature is still built whatever it
    matches: the user picked that rig by hand, and createControlRig's own error
    is the answer they want.)

    Each part's controller is then re-homed under the unit's root, because
    createControlRig parents the rig UNDER its controller and would otherwise
    lift the rider clean off its mount.

    Returns (built, skipped names, already rigged, results).
    """
    root = groupRoot(target)
    parts = groupParts(target)
    if len(parts) > 1:
        # the tags have to be down before the parts get controllers, or the
        # re-parenting below is the last anything sees of the group
        adoptGroup(root)
        parts = groupParts(target)
        root = groupRoot(target)
    built = 0
    skipped = []
    already = 0
    results = []
    for member in parts:
        if member is None or member.type != 'ARMATURE':
            continue
        if controlRigOf(member) is not None:
            already += 1
            continue
        if len(parts) > 1 and controlRigMatchCount(member, rig_type) == 0:
            skipped.append(member.name)
            continue
        world = member.matrix_world.copy()
        controller, rig_results = createControlRig(context, member, rig_type)
        results.extend(entry for entry in rig_results if entry[0] != 'INFO')
        if controller is None:
            continue
        built += 1
        if member is root or root is None:
            continue
        # A rider's local transform is an offset from the mount, so once
        # createControlRig has re-parented it the old local transform would be
        # read as a world position and the rider would jump to it. The
        # controller is brand new, so its own world matrix has to be solved
        # before the rider can be put back onto it.
        context.view_layer.update()
        member.matrix_world = world
        controller.parent = root
        controller.matrix_parent_inverse = root.matrix_world.inverted()
    return built, skipped, already, results
