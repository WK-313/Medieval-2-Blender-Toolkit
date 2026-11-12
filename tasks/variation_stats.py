"""Per-soldier counts next to Blender's Statistics overlay.

Blender's statistics add up every mesh in the scene, but an imported unit carries
all of its variations at once (every head, every helmet...) and the game only
ever builds a soldier from one mesh of each group. So for each selected unit
rig this draws the average soldier instead: every ``group__x`` mesh group counts
as the mean of its variations. The number in brackets is the same average over
the visible meshes only, so hiding a variation shows what the rest average to.

It is drawn bottom-left of the viewport, only while the Statistics overlay is on.
Blender's own statistics block has no fixed height to sit under, so it is not
placed there.
"""
import blf
import bpy

_handle = None
MAX_RIGS = 6


def heldItems(names, secondary):
    """The active/passive weapon and shield meshes a soldier does not hold - the
    same choice hideVariations() makes, so the counts match a shuffled unit."""
    shield, weapon = "shieldpassive", "secondaryactive"
    if secondary:
        if any("shieldpassive" in name for name in names):
            shield = "shieldactive"
        if any("secondaryactive" in name for name in names):
            weapon = "primaryactive"
    return shield, weapon


def meshCounts(obj):
    mesh = obj.data
    # each n-gon is n - 2 triangles, so the sum over faces is loops - 2 * faces
    return len(mesh.vertices), len(mesh.loops) - 2 * len(mesh.polygons)


def soldierStats(rig, secondary):
    """(groups, average verts, average tris, visible-average verts, visible-average tris)"""
    meshes = [obj for obj in rig.children if obj.type == 'MESH']
    skip = heldItems([obj.name for obj in meshes], secondary)
    groups = {}
    for obj in meshes:
        if any(item in obj.name for item in skip):
            continue
        groups.setdefault(obj.name.split("__")[0], []).append(obj)
    verts = tris = shown_verts = shown_tris = 0.0
    for members in groups.values():
        counts = [meshCounts(obj) for obj in members]
        verts += sum(c[0] for c in counts) / len(counts)
        tris += sum(c[1] for c in counts) / len(counts)
        shown = [c for obj, c in zip(members, counts) if obj.visible_get()]
        if shown:
            shown_verts += sum(c[0] for c in shown) / len(shown)
            shown_tris += sum(c[1] for c in shown) / len(shown)
    return len(groups), verts, tris, shown_verts, shown_tris


def selectedRigs(context):
    rigs = []
    for obj in context.selected_objects:
        rig = obj if obj.type == 'ARMATURE' else obj.parent
        if rig and rig.type == 'ARMATURE' and rig not in rigs and any(
                child.type == 'MESH' for child in rig.children):
            rigs.append(rig)
    return rigs


def statLines(context):
    secondary = context.scene.med2_toolkit_units.primary_secondary == "secondary"
    rigs = selectedRigs(context)
    lines = []
    for rig in rigs[:MAX_RIGS]:
        groups, verts, tris, shown_verts, shown_tris = soldierStats(rig, secondary)
        lines.append("%s - avg soldier (%d groups): Verts %s (%s)  Tris %s (%s)" % (
            rig.name, groups, "{:,.0f}".format(verts), "{:,.0f}".format(shown_verts),
            "{:,.0f}".format(tris), "{:,.0f}".format(shown_tris)))
    if len(rigs) > MAX_RIGS:
        lines.append("+%d more selected rigs" % (len(rigs) - MAX_RIGS))
    return lines


def draw():
    context = bpy.context
    space = context.space_data
    if not (space and space.overlay.show_overlays and space.overlay.show_stats):
        return
    lines = statLines(context)
    if not lines:
        return
    scale = context.preferences.system.ui_scale
    x = 14 * scale
    if context.preferences.system.use_region_overlap:
        for region in context.area.regions:
            if region.type == 'TOOLS' and region.width > 1:
                x += region.width
    font = 0
    blf.size(font, 11 * scale)
    blf.color(font, 1, 1, 1, 1)
    blf.enable(font, blf.SHADOW)
    blf.shadow(font, 5, 0, 0, 0, 1)
    blf.shadow_offset(font, 1, -1)
    step = 16 * scale
    # above the pose buttons pose_panel puts in the bottom-left corner
    y = 62 * scale
    for line in reversed(lines):
        blf.position(font, x, y, 0)
        blf.draw(font, line)
        y += step
    blf.disable(font, blf.SHADOW)


def register():
    global _handle
    if _handle is None:
        _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        _handle = None
