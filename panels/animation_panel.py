"""Native game animation browser, shared by battle and strat rigs."""
import math

import bpy
from bpy.props import CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from ..m2formats.skelslots import FAMILIES
from ..tasks import animation_browser as browser, animation_engine as engine
from ..tasks.pose_library import activeArmature
from .strat_import_panel import dataRoot
from .unit_export_panel import showResultsPopup


class MED_2_TOOLKIT_Animation_Name(bpy.types.PropertyGroup):
    name: StringProperty()


class MED_2_TOOLKIT_Animation_Item(bpy.types.PropertyGroup):
    name: StringProperty()
    path: StringProperty()
    slot: IntProperty(default=-1)
    family: StringProperty()
    frames: IntProperty()
    duration: FloatProperty()
    error: StringProperty()
    source_kind: StringProperty()


class MED_2_TOOLKIT_Animation_Browser(bpy.types.PropertyGroup):
    skeletons: CollectionProperty(type=MED_2_TOOLKIT_Animation_Name)
    actions: CollectionProperty(type=MED_2_TOOLKIT_Animation_Item)
    skeleton: StringProperty(name='Skeleton')
    loaded_skeleton: StringProperty()
    data_root: StringProperty()
    active_index: IntProperty(default=0)
    search: StringProperty(name='Search', description='Filter actions by name or file path')
    family: EnumProperty(name='Family', items=[('all', 'All families', '')] +
                         [(key, name, '') for key, name, _ in FAMILIES])


def catalogueCurrent(context):
    settings = context.scene.med2_toolkit_animations
    root = dataRoot(context)
    return root is not None and str(root) == settings.data_root


def selectedAction(context):
    settings = context.scene.med2_toolkit_animations
    if (catalogueCurrent(context) and settings.skeleton == settings.loaded_skeleton
            and 0 <= settings.active_index < len(settings.actions)):
        return settings.actions[settings.active_index]
    return None


def reportResults(operator, context, title, reports):
    for level, message in reports:
        operator.report({level}, message)
    if any(level != 'INFO' for level, _ in reports):
        showResultsPopup(context, title, reports)


class MED_2_TOOLKIT_OT_Animation_Refresh(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.animation_refresh'
    bl_label = 'Refresh Skeletons'
    bl_description = 'Read animation skeletons from the selected mod and its vanilla fallback'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            root = dataRoot(context)
            if root is None:
                raise ValueError('Select a mod data folder in Paths first')
            names = browser.skeletonNames(root)
            if not names:
                raise ValueError('No animation skeletons found in the selected mod or vanilla data')
        except (OSError, ValueError, engine.casanim.AnimError) as error:
            reportResults(self, context, 'Animations', [('ERROR', str(error))])
            return {'CANCELLED'}
        settings = context.scene.med2_toolkit_animations
        settings.skeletons.clear()
        for name in names:
            settings.skeletons.add().name = name
        settings.actions.clear()
        settings.loaded_skeleton = ''
        settings.data_root = str(root)
        desired = browser.suggestedSkeleton(activeArmature(context)) or settings.skeleton
        settings.skeleton = next((name for name in names if name.casefold() == desired.casefold()), names[0])
        self.report({'INFO'}, 'Loaded %d skeletons' % len(names))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Animation_Load(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.animation_load'
    bl_label = 'Load Actions'
    bl_description = 'List actions grouped by family, with source frame counts and durations'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return catalogueCurrent(context) and bool(context.scene.med2_toolkit_animations.skeleton)

    def execute(self, context):
        settings = context.scene.med2_toolkit_animations
        try:
            rows = browser.actionRows(dataRoot(context), settings.skeleton)
        except (OSError, ValueError, engine.casanim.AnimError) as error:
            reportResults(self, context, 'Animations', [('ERROR', str(error))])
            return {'CANCELLED'}
        settings.actions.clear()
        for row in rows:
            item = settings.actions.add()
            for key, value in row.items():
                setattr(item, key, value)
        settings.loaded_skeleton = settings.skeleton
        settings.active_index = 0
        reports = [('WARNING', '%s: %s' % (row['name'], row['error'])) for row in rows if row['error']]
        reports.append(('INFO', 'Loaded %d actions for %s' % (len(rows), settings.skeleton)))
        reportResults(self, context, 'Animations', reports)
        return {'FINISHED'}


class MED_2_TOOLKIT_UL_Animations(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon='ERROR' if item.error else 'ACTION')
        layout.label(text='%d f / %.2f s' % (item.frames, item.duration))

    def filter_items(self, context, data, propname):
        terms = data.search.casefold().split()
        return [self.bitflag_filter_item if (data.family == 'all' or data.family == item.family)
                and all(term in (item.name + ' ' + item.path).casefold() for term in terms) else 0
                for item in getattr(data, propname)], []


class MED_2_TOOLKIT_OT_Animation_Play(bpy.types.Operator):
    bl_idname = 'medieval2toolkit.animation_play'
    bl_label = 'Build & Play'
    bl_description = 'Build or reuse an Action on the selected rig and play its preview range; existing Actions are retained'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'} and activeArmature(context) is not None and selectedAction(context) is not None

    def execute(self, context):
        settings = context.scene.med2_toolkit_animations
        rig, row = activeArmature(context), selectedAction(context)
        action, created = None, False
        previous = rig.animation_data.action if rig.animation_data else None
        try:
            if rig.library or rig.data.library:
                raise ValueError('Make the rig local before assigning an animation')
            data = rig.animation_data
            if data and (data.use_tweak_mode or data.action_blend_type != 'REPLACE' or data.action_influence != 1.0):
                raise ValueError('Exit NLA tweak mode and set Action blending to Replace at full influence before playback')
            fps = context.scene.render.fps / context.scene.render.fps_base
            reports, action, created = browser.cachedAction(rig, dataRoot(context), settings.skeleton, row, fps)
            engine.activateAnimationAction(rig, action)
        except (OSError, ValueError, RuntimeError, engine.casanim.AnimError) as error:
            if created and action is not None:
                bpy.data.actions.remove(action)
            reportResults(self, context, 'Animation playback', [('ERROR', str(error))])
            return {'CANCELLED'}
        if previous and previous != action and not previous.library:
            previous.use_fake_user = True
        rig.data.pose_position = 'POSE'
        scene = context.scene
        scene.use_preview_range = True
        scene.frame_preview_start = 1
        scene.frame_preview_end = max(1, math.ceil(action['med2_animation_end']))
        scene.frame_set(1)
        reports.append(('INFO', '%s: %s -> %s' % (rig.name, previous.name if previous else 'No Action', action.name)))
        if not bpy.app.background and context.screen and not context.screen.is_animation_playing:
            try:
                bpy.ops.screen.animation_play()
            except RuntimeError as error:
                reports.append(('WARNING', 'Action assigned; start timeline playback manually: %s' % error))
        reportResults(self, context, 'Animation playback', reports)
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Animations(bpy.types.Panel):
    bl_idname = 'MED_2_TOOLKIT_PT_Animations'
    bl_parent_id = 'MED_2_TOOLKIT_PT_Main_Panel'
    bl_label = 'Game Animations'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Medieval 2 Toolkit'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection in {'unit_import', 'unit_export', 'qol', 'strat'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_animations
        layout.operator('medieval2toolkit.animation_refresh', icon='FILE_REFRESH')
        if not catalogueCurrent(context):
            layout.label(text='Refresh skeletons for the selected mod', icon='INFO')
            return
        layout.prop_search(settings, 'skeleton', settings, 'skeletons')
        layout.operator('medieval2toolkit.animation_load', icon='ACTION')
        if settings.loaded_skeleton != settings.skeleton:
            return
        layout.prop(settings, 'family')
        layout.prop(settings, 'search', icon='VIEWZOOM', text='')
        layout.template_list('MED_2_TOOLKIT_UL_Animations', '', settings, 'actions', settings, 'active_index', rows=7)
        item = selectedAction(context)
        if item:
            layout.label(text=item.path.replace('\\', '/').rsplit('/', 1)[-1])
            layout.label(text='%s / %d source frames / %.2f s' % (item.source_kind or 'Unavailable', item.frames, item.duration))
            if item.error:
                layout.label(text=item.error, icon='ERROR')
        rig = activeArmature(context)
        layout.label(text='Rig: %s' % rig.name if rig else 'Select a battle or strat rig', icon='ARMATURE_DATA')
        layout.operator('medieval2toolkit.animation_play', icon='PLAY')
        if context.screen and context.screen.is_animation_playing:
            layout.operator('screen.animation_cancel', text='Stop', icon='PAUSE')


classes = [MED_2_TOOLKIT_Animation_Name, MED_2_TOOLKIT_Animation_Item, MED_2_TOOLKIT_Animation_Browser,
           MED_2_TOOLKIT_UL_Animations, MED_2_TOOLKIT_OT_Animation_Refresh, MED_2_TOOLKIT_OT_Animation_Load,
           MED_2_TOOLKIT_OT_Animation_Play]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.med2_toolkit_animations = PointerProperty(type=MED_2_TOOLKIT_Animation_Browser)


def unregister():
    del bpy.types.Scene.med2_toolkit_animations
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
