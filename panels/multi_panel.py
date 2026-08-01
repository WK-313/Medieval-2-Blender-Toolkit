"""The section strip and the panels it switches between.

Every tool panel used to be a real Blender sub-panel of the main panel, gated by
a poll() on the workmode enum. That works, but Blender always draws sub-panels
full width underneath their parent, so the workmode buttons could only ever be a
block of text above everything else.

UVPackmaster solves the same problem by not using sub-panels at all: its
UVPM4_PT_MultiPanels draws one row, puts a column of icon-only toggle operators
down the left of it and the selected section's panels down the right, and each
"panel" is an ordinary class it instantiates and calls draw() on itself. This is
the same thing, with the workmode enum as the selector.

Two things worth knowing:

- the strip scrolls with the panel, because it is part of the panel's layout.
  UVPackmaster's does too - there is no way to pin a widget inside a region from
  Python. What makes it feel fixed is that only one section draws at a time, so
  there is very little to scroll past.
- the embedded panels are never registered with Blender. They stay Panel
  subclasses so their poll/bl_label/bl_options still read naturally, but nothing
  registers them, which is why their headers are drawn by hand below.
"""

import bpy
from bpy.props import StringProperty

from .bmdb_panel import MED_2_TOOLKIT_PT_BMDB_Import
from .edu_panel import MED_2_TOOLKIT_PT_EDU_Import
from .mod_data import MED2_TOOLKIT_PT_Mod_Data
from .pose_panel import MED_2_TOOLKIT_PT_Poses, MED_2_TOOLKIT_PT_Texture_Assets
from .qol_panel import (MED_2_TOOLKIT_PT_Armature, MED_2_TOOLKIT_PT_QOL_Advanced,
                        MED_2_TOOLKIT_PT_Rename_Tools, MED_2_TOOLKIT_PT_Weight_Transfer)
from .settlements_panel import MED_2_TOOLKIT_PT_Settlements_Panel
from .unit_export_panel import (MED_2_TOOLKIT_PT_Export_BMDB, MED_2_TOOLKIT_PT_Export_Install,
                                MED_2_TOOLKIT_PT_Export_Materials, MED_2_TOOLKIT_PT_Export_Run,
                                MED_2_TOOLKIT_PT_Unit_Export)
from .unit_info_panel import (MED_2_TOOLKIT_PT_Card_Render, MED_2_TOOLKIT_PT_Card_Scene,
                              MED_2_TOOLKIT_PT_Unit_Info)


# (workmode value, name for the tooltip, icon) in the order the strip draws them.
# The EVENT_* icons are Blender's keyboard-key glyphs, which is what UVPackmaster
# uses for the same job - a plain letter reads better at strip width than any of
# the pictorial icons do.
SECTIONS = [
    ('unit_import', "Import",     'EVENT_I'),
    ('unit_export', "Export",     'EVENT_E'),
    ('settlements', "Settlement", 'EVENT_S'),
    ('qol',         "QOL",        'EVENT_Q'),
    ('unit_info',   "Unit Cards", 'EVENT_U'),
]

# Draw order within a section. Which section a panel belongs to is still its own
# poll()'s business, exactly as it was when these were sub-panels, so this is one
# flat list and the polls sort it out.
EMBEDDED_PANELS = [
    MED2_TOOLKIT_PT_Mod_Data,
    MED_2_TOOLKIT_PT_EDU_Import,
    MED_2_TOOLKIT_PT_BMDB_Import,
    MED_2_TOOLKIT_PT_Unit_Export,
    MED_2_TOOLKIT_PT_Export_Materials,
    MED_2_TOOLKIT_PT_Export_BMDB,
    MED_2_TOOLKIT_PT_Export_Run,
    MED_2_TOOLKIT_PT_Export_Install,
    MED_2_TOOLKIT_PT_Settlements_Panel,
    MED_2_TOOLKIT_PT_Weight_Transfer,
    MED_2_TOOLKIT_PT_Armature,
    MED_2_TOOLKIT_PT_Rename_Tools,
    MED_2_TOOLKIT_PT_QOL_Advanced,
    MED_2_TOOLKIT_PT_Poses,
    MED_2_TOOLKIT_PT_Texture_Assets,
    MED_2_TOOLKIT_PT_Unit_Info,
    MED_2_TOOLKIT_PT_Card_Scene,
    MED_2_TOOLKIT_PT_Card_Render,
]

# Written into the collapsed list the first time anything is toggled, so an empty
# string can keep meaning "never touched, use the panels' own DEFAULT_CLOSED".
INIT_MARKER = "#"


def panelId(panel):
    return getattr(panel, 'bl_idname', panel.__name__)


def defaultClosed():
    return {panelId(panel) for panel in EMBEDDED_PANELS
            if 'DEFAULT_CLOSED' in getattr(panel, 'bl_options', set())}


def collapsedPanels(scene):
    raw = scene.med2_toolkit_collapsed
    if not raw:
        return defaultClosed()
    return {name for name in raw.split(',') if name and name != INIT_MARKER}


def storeCollapsed(scene, names):
    scene.med2_toolkit_collapsed = ','.join([INIT_MARKER] + sorted(names))


class MED_2_TOOLKIT_OT_Toggle_Section_Panel(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_section_panel"
    bl_label = "Expand Panel"
    bl_description = "Expand or collapse this panel"
    bl_options = {'INTERNAL'}

    panel_id: StringProperty(name = "Panel", default = "")

    def execute(self, context):
        shut = collapsedPanels(context.scene)
        if self.panel_id in shut:
            shut.discard(self.panel_id)
        else:
            shut.add(self.panel_id)
        storeCollapsed(context.scene, shut)
        return {'FINISHED'}


class EmbeddedPanel:
    """Stands in for the Panel instance Blender would have made.

    Every embedded panel's draw() only ever touches self.layout - so handing it
    something that has one is the whole trick. Checked against all of them; if a
    panel ever needs more of the real Panel, it has to go back to being a
    registered sub-panel instead.
    """

    def __init__(self, layout):
        self.layout = layout


def drawSectionStrip(context, layout):
    """The column of letter buttons down the left, and the active section beside it."""
    scene = context.scene
    row = layout.row(align=False)

    strip = row.column(align=True)
    strip.scale_x = 1.15
    strip.scale_y = 1.15
    for identifier, _name, icon in SECTIONS:
        strip.prop_enum(scene.med2_toolkit_mode, "mode_selection", identifier, text="", icon=icon)

    body = row.column(align=False)
    shut = collapsedPanels(scene)
    drawn = 0
    for panel in EMBEDDED_PANELS:
        poll = getattr(panel, 'poll', None)
        if poll is not None and not poll(context):
            continue
        drawn += 1
        box = body.box()
        # HIDE_HEADER panels never had a header to collapse, so they keep drawing
        # straight into the box
        if 'HIDE_HEADER' in getattr(panel, 'bl_options', set()):
            panel.draw(EmbeddedPanel(box), context)
            continue
        identifier = panelId(panel)
        open_panel = identifier not in shut
        # left aligned in a row of its own, or the borderless button centres
        # itself across the box and stops reading as a panel header
        header = box.row(align=True)
        header.alignment = 'LEFT'
        toggle = header.operator("medieval2toolkit.toggle_section_panel",
                                 text=panel.bl_label,
                                 icon='TRIA_DOWN' if open_panel else 'TRIA_RIGHT',
                                 emboss=False)
        toggle.panel_id = identifier
        if open_panel:
            panel.draw(EmbeddedPanel(box), context)
    if not drawn:
        body.label(text="Nothing to show here yet", icon='INFO')


classes = [
    MED_2_TOOLKIT_OT_Toggle_Section_Panel,
]


def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_collapsed = StringProperty(
        name = "Collapsed panels",
        description = "Which embedded panels are folded shut, as a comma separated list of panel ids",
        default = "")


def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_collapsed
