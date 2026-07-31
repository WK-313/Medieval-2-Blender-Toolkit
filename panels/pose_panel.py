import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty

from ..tasks import pose_library
from ..tasks.control_rig import controlRigOf
from ..tasks.pose_library import (DEFAULT_CATALOG, LIBRARY_NAME, activeArmature, animationSummary,
                                  actionBoneNames, applyPoseAction, candidateArmatures, clearAnimation,
                                  closePoseBrowser, ensureAssetLibrary, libraryAvailable, openPoseBrowser,
                                  poseBrowserArea, poseCatalogs, poseTarget, refreshPoseBrowser,
                                  registeredLibrary, withAssetAction)
from ..tasks.texture_assets import texturesToAssets
from .unit_export_panel import SEVERITY_ORDER, showResultsPopup

# Same EnumProperty items-callback caveat as the other panels: hold the last
# returned items so Blender's pointers stay valid.
_catalog_enum_items = []


def catalogItems(self, context):
    """Pose catalogs for the dropdowns. An EnumProperty with a callback cannot
    declare a default, so the working catalog is listed first to become it."""
    global _catalog_enum_items
    items = [(path, path.split('/', 1)[-1] if '/' in path else path, path) for _uuid, path, _simple in poseCatalogs()]
    items.sort(key=lambda entry: entry[0] != DEFAULT_CATALOG)
    if not items:
        items = [(DEFAULT_CATALOG, DEFAULT_CATALOG, "")]
    _catalog_enum_items = items
    return _catalog_enum_items


def doubleClickChanged(self, context):
    overrideStockDoubleClick(self.override_double_click)


class MED_2_TOOLKIT_Pose_Data(bpy.types.PropertyGroup):
    override_double_click: BoolProperty(
        name = "Double-click applies poses",
        description = ("Let the toolkit handle double-clicks in the asset browser instead of Blender's own "
                       "pose library, so a pose can be applied from object mode, lands on the IK control rig "
                       "when that is what it was made for, and warns before overwriting an animation"),
        default = True,
        update = doubleClickChanged)
    open_browser_with_pose_mode: BoolProperty(
        name = "Open pose library",
        description = "Open the pose asset browser beside the viewport when entering pose mode",
        default = True)
    browser_catalog: EnumProperty(
        name = "Catalog",
        description = "Catalog the pose browser opens on",
        items = catalogItems)
    show_pose_buttons: BoolProperty(
        name = "Viewport buttons",
        description = "Show the pose buttons in the bottom-left corner of the viewport whenever an armature is selected",
        default = True)
    texture_folder: StringProperty(
        name = "Texture folder",
        description = "Folder of game textures to turn into asset-marked materials",
        subtype = "DIR_PATH")
    texture_mark_assets: BoolProperty(
        name = "Mark as assets",
        description = "Mark the generated materials as assets and build their previews",
        default = True)


def reportResults(operator, context, title, results):
    results = sorted(results, key=lambda result: SEVERITY_ORDER.get(result[0], 2))
    for level, message in results:
        operator.report({level}, message)
    showResultsPopup(context, title, results)


class MED_2_TOOLKIT_OT_Register_Pose_Library(bpy.types.Operator):
    bl_idname = "medieval2toolkit.register_pose_library"
    bl_label = "Register Pose Library"
    bl_description = "Point a user asset library at the pose assets bundled with the addon."
    bl_options = {"REGISTER"}

    def execute(self, context):
        level, message = ensureAssetLibrary()
        self.report({level}, message)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Toggle_Pose_Mode(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_pose_mode"
    bl_label = "Toggle Pose Mode"
    bl_description = "Switch the selected armature between object and pose mode, opening the pose library on the way in."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeArmature(context) is not None and context.mode in {'OBJECT', 'POSE'}

    @classmethod
    def description(cls, context, properties):
        if context.mode == 'POSE':
            return "Leave pose mode and go back to object mode."
        return "Put the selected armature into pose mode and open the pose library beside the viewport."

    def execute(self, context):
        armature = activeArmature(context)
        if armature is None:
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}
        leaving = context.mode == 'POSE'
        if not leaving and context.view_layer.objects.active is not armature:
            # mode_set acts on the active object, and "an armature is selected"
            # does not mean it is the active one
            armature.select_set(True)
            context.view_layer.objects.active = armature
        try:
            bpy.ops.object.mode_set(mode='OBJECT' if leaving else 'POSE')
        except RuntimeError as error:
            self.report({'ERROR'}, "Could not switch mode: %s" % error)
            return {'CANCELLED'}
        if leaving:
            self.report({'INFO'}, "Back in object mode")
            return {'FINISHED'}
        if context.scene.med2_toolkit_poses.open_browser_with_pose_mode:
            _area, message = openPoseBrowser(context, context.scene.med2_toolkit_poses.browser_catalog)
            self.report({'INFO'}, "Pose mode: %s" % message)
        else:
            self.report({'INFO'}, "Pose mode")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Toggle_Pose_Browser(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_pose_browser"
    bl_label = "Pose Library"
    bl_description = ("Open or close the pose asset browser beside the viewport. With an armature selected, "
                      "double-clicking a pose applies it - in object mode too.")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return libraryAvailable()

    def execute(self, context):
        if poseBrowserArea(context) is not None:
            if closePoseBrowser(context):
                self.report({'INFO'}, "Closed the pose library")
            else:
                self.report({'WARNING'}, "That asset browser was not opened by the toolkit - close it yourself")
            return {'FINISHED'}
        if registeredLibrary() is None:
            ensureAssetLibrary()
        _area, message = openPoseBrowser(context, context.scene.med2_toolkit_poses.browser_catalog)
        self.report({'INFO'}, message)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Create_Pose_Asset(bpy.types.Operator):
    bl_idname = "medieval2toolkit.create_pose_asset"
    bl_label = "Create Pose Asset"
    bl_description = ("Save the current pose of the selected bones into the bundled pose library, "
                      "under a catalog you pick.")
    bl_options = {"REGISTER", "UNDO"}

    pose_name: StringProperty(name = "Pose name", description = "Name the pose is saved under", default = "New Pose")
    catalog: EnumProperty(name = "Catalog", description = "Existing catalog to file the pose under", items = catalogItems)
    sub_catalog: StringProperty(name = "New sub-catalog", description = "Optional new catalog created underneath the one above, e.g. a new weapon type", default = "")
    selected_only: BoolProperty(name = "Selected bones only", description = "Save only the selected bones. Untick to select every bone first", default = True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'POSE' and libraryAvailable()

    def invoke(self, context, event):
        armature = activeArmature(context)
        if armature is not None:
            self.pose_name = armature.name.replace('_', ' ').title() + " Pose"
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "pose_name")
        layout.prop(self, "catalog")
        layout.prop(self, "sub_catalog")
        layout.prop(self, "selected_only")
        catalog_path = self.catalogPath()
        layout.label(text="Saves into: %s" % catalog_path, icon='ASSET_MANAGER')
        layout.label(text="Library: %s" % LIBRARY_NAME, icon='FILE_FOLDER')

    def catalogPath(self):
        catalog_path = self.catalog
        if self.sub_catalog.strip():
            catalog_path = catalog_path + '/' + self.sub_catalog.strip().strip('/')
        return catalog_path

    def execute(self, context):
        if not self.pose_name.strip():
            self.report({'ERROR'}, "Give the pose a name")
            return {'CANCELLED'}
        if registeredLibrary() is None:
            ensureAssetLibrary()
        if not self.selected_only:
            bpy.ops.pose.select_all(action='SELECT')
        elif not context.selected_pose_bones:
            self.report({'ERROR'}, "No bones selected - select the bones to save, or untick Selected bones only")
            return {'CANCELLED'}
        catalog_path = self.catalogPath()
        try:
            result = bpy.ops.poselib.create_pose_asset(
                pose_name = self.pose_name.strip(),
                asset_library_reference = LIBRARY_NAME,
                catalog_path = catalog_path,
            )
        except RuntimeError as error:
            self.report({'ERROR'}, "Blender could not save the pose: %s" % error)
            return {'CANCELLED'}
        if 'FINISHED' not in result:
            self.report({'ERROR'}, "Blender did not save the pose")
            return {'CANCELLED'}
        refreshPoseBrowser(context)
        results = [
            ('INFO', "Saved '%s' into %s" % (self.pose_name.strip(), catalog_path)),
            ('INFO', "Written to %s\\Saved\\Actions" % pose_library.libraryPath()),
        ]
        reportResults(self, context, "Pose asset created", results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Apply_Pose_Asset(bpy.types.Operator):
    bl_idname = "medieval2toolkit.apply_pose_asset"
    bl_label = "Apply Pose"
    bl_description = ("Apply the pose asset under the cursor to the selected rig. Works from object mode, "
                      "picks the IK control rig when the pose was made for one, and warns before "
                      "overwriting an existing animation.")
    bl_options = {"REGISTER", "UNDO"}

    clear_animation: BoolProperty(
        name = "Delete the animation",
        description = "Delete every keyframe of the actions driving this rig before applying the pose. Untick to leave the animation alone and cancel",
        default = True)

    @classmethod
    def poll(cls, context):
        return getattr(context, "asset", None) is not None

    def rigsWithAnimation(self, context):
        animated = []
        for rig in candidateArmatures(context):
            summary = animationSummary(rig)
            if summary is not None:
                animated.append((rig, summary))
        return animated

    def invoke(self, context, event):
        asset = getattr(context, "asset", None)
        if asset is None:
            self.report({'ERROR'}, "No pose asset under the cursor")
            return {'CANCELLED'}
        if asset.id_type != 'ACTION':
            self.report({'ERROR'}, "'%s' is not a pose" % asset.name)
            return {'CANCELLED'}
        if not candidateArmatures(context):
            self.report({'ERROR'}, "Select an armature to apply the pose to")
            return {'CANCELLED'}
        self._animated = self.rigsWithAnimation(context)
        if self._animated:
            self.clear_animation = True
            return context.window_manager.invoke_props_dialog(self, width=420)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="This rig is animated", icon='ERROR')
        for rig, (names, keyframes, bones) in getattr(self, "_animated", []):
            box.label(text="%s: %s" % (rig.name, ", ".join(names)), icon='ACTION')
            box.label(text="%d keyframe(s) across %d bone(s)" % (keyframes, len(bones)))
        column = layout.column()
        column.label(text="Applying a pose overwrites it. Every keyframe of")
        column.label(text="those actions will be deleted, then the pose applied.")
        layout.prop(self, "clear_animation")
        if not self.clear_animation:
            layout.label(text="Left unticked, nothing is changed.", icon='CANCEL')

    def execute(self, context):
        asset = getattr(context, "asset", None)
        if asset is None:
            self.report({'ERROR'}, "No pose asset under the cursor")
            return {'CANCELLED'}
        candidates = candidateArmatures(context)
        if not candidates:
            self.report({'ERROR'}, "Select an armature to apply the pose to")
            return {'CANCELLED'}
        animated = self.rigsWithAnimation(context)
        if animated and not self.clear_animation:
            self.report({'WARNING'}, "Left the animation alone - the pose was not applied")
            return {'CANCELLED'}

        results = []
        outcome = {}

        def apply(action):
            bone_names = actionBoneNames(action)
            if not bone_names:
                outcome['error'] = "'%s' animates no bones" % asset.name
                return
            target, matched, missing = poseTarget(candidates, bone_names)
            if not matched:
                outcome['error'] = ("'%s' poses bones none of the selected rigs have (%s). "
                                    "IK poses need the control rig - use Add Control Rig."
                                    % (asset.name, ", ".join(sorted(bone_names)[:3])))
                return
            if animated:
                for rig, _summary in animated:
                    cleared = clearAnimation(rig)
                    if cleared is not None:
                        names, keyframes, bones = cleared
                        results.append(('WARNING', "Deleted %d keyframe(s) from %s on '%s'"
                                        % (keyframes, ", ".join(names), rig.name)))
            applyPoseAction(target, action)
            outcome['target'] = target
            results.append(('INFO', "Applied '%s' to '%s' (%d bone(s))" % (asset.name, target.name, len(matched))))
            if missing:
                results.append(('INFO', "%d bone(s) in the pose are not on that rig and were ignored" % len(missing)))

        try:
            withAssetAction(asset, apply)
        except (OSError, RuntimeError) as error:
            self.report({'ERROR'}, "Could not load '%s': %s" % (asset.name, error))
            return {'CANCELLED'}

        if 'error' in outcome:
            self.report({'ERROR'}, outcome['error'])
            return {'CANCELLED'}
        if 'target' not in outcome:
            self.report({'ERROR'}, "Could not read '%s' out of the asset library" % asset.name)
            return {'CANCELLED'}
        for level, message in results:
            self.report({level}, message)
        return {'FINISHED'}


#   ------------------------  #
#   Asset browser double-click  #
#   ------------------------  #

# (keymap, keymap item) pairs this addon added, and the stock pose library
# double-click we mute while ours is in charge.
_keymaps = []
_stock_items = []
# set while the addon is registered, so a deferred keymap build that lands after
# a quick disable does not put an entry back
_keymap_wanted = False

ASSET_KEYMAP = "Asset Browser Main"


def stockDoubleClickItems():
    """Blender's own double-click-to-apply-pose keymap entries. Every keymap of
    that name is scanned rather than one looked up, since the name is not unique
    across space types."""
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is None:
        return []
    items = []
    for keymap in keyconfig.keymaps:
        if keymap.name != ASSET_KEYMAP:
            continue
        items.extend(item for item in keymap.keymap_items
                     if item.idname == "poselib.apply_pose_asset" and item.value == 'DOUBLE_CLICK')
    return items


def overrideStockDoubleClick(enable):
    """Mute (or restore) Blender's double-click handler.

    Both entries live in the same addon keymap, and the stock one was registered
    first, so it would always win the event. Muting rather than removing it keeps
    the change reversible - unregistering the toolkit puts it straight back.
    """
    global _stock_items
    if enable:
        for item in stockDoubleClickItems():
            if item.active:
                item.active = False
                _stock_items.append(item)
    else:
        for item in _stock_items:
            try:
                item.active = True
            except ReferenceError:
                pass
        _stock_items = []


def registerKeymap():
    global _keymap_wanted
    _keymap_wanted = True

    def run():
        if not _keymap_wanted:
            return None
        keyconfig = bpy.context.window_manager.keyconfigs.addon
        if keyconfig is None:
            # background Blender has no addon keyconfig
            return None
        keymap = keyconfig.keymaps.new(name=ASSET_KEYMAP, space_type='FILE_BROWSER')
        item = keymap.keymap_items.new("medieval2toolkit.apply_pose_asset", 'LEFTMOUSE', 'DOUBLE_CLICK')
        _keymaps.append((keymap, item))
        overrideStockDoubleClick(True)
        return None
    # same reason as registerLibraryDeferred: the core pose library addon has to
    # have registered its own keymap before we can mute it
    bpy.app.timers.register(run, first_interval=0)


def unregisterKeymap():
    global _keymap_wanted
    _keymap_wanted = False
    overrideStockDoubleClick(False)
    for keymap, item in _keymaps:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            pass
    _keymaps.clear()


class MED_2_TOOLKIT_OT_Textures_To_Assets(bpy.types.Operator):
    bl_idname = "medieval2toolkit.textures_to_assets"
    bl_label = "Convert Textures to Assets"
    bl_description = "Build one asset-marked material per texture in the folder, pairing each with its normal map."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.med2_toolkit_poses
        results = texturesToAssets(settings.texture_folder, settings.texture_mark_assets)
        reportResults(self, context, "Textures to assets", results)
        return {'FINISHED'}


#   ---------------------  #
#   Floating pose buttons   #
#   ---------------------  #

# Bottom-left corner of the viewport, in pixels, and the gap between buttons.
BUTTON_SIZE = 30
BUTTON_MARGIN_X = 90
BUTTON_MARGIN_Y = 36
BUTTON_GAP = 38


class MED_2_TOOLKIT_GGT_Pose_Buttons(bpy.types.GizmoGroup):
    """The little pose buttons in the bottom-left of the viewport. A gizmo group
    is the only way to put a clickable control loose in the 3D view - panels can
    only live in the sidebar or header."""
    bl_idname = "MED_2_TOOLKIT_GGT_Pose_Buttons"
    bl_label = "Medieval 2 Pose Buttons"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'PERSISTENT', 'SCALE'}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "med2_toolkit_poses", None)
        if settings is None or not settings.show_pose_buttons:
            return False
        if context.mode not in {'OBJECT', 'POSE'}:
            return False
        return activeArmature(context) is not None

    def makeButton(self, icon, operator):
        gizmo = self.gizmos.new("GIZMO_GT_button_2d")
        gizmo.icon = icon
        gizmo.draw_options = {'BACKDROP', 'OUTLINE'}
        gizmo.color = 0.0, 0.0, 0.0
        gizmo.alpha = 0.5
        gizmo.color_highlight = 0.8, 0.8, 0.8
        gizmo.alpha_highlight = 0.2
        gizmo.scale_basis = BUTTON_SIZE / 2
        gizmo.target_set_operator(operator)
        return gizmo

    def setup(self, context):
        self.mode_button = self.makeButton('POSE_HLT', "medieval2toolkit.toggle_pose_mode")
        self.browser_button = self.makeButton('ASSET_MANAGER', "medieval2toolkit.toggle_pose_browser")
        self.asset_button = self.makeButton('ADD', "medieval2toolkit.create_pose_asset")

    def draw_prepare(self, context):
        in_pose = context.mode == 'POSE'
        self.mode_button.icon = 'OBJECT_DATAMODE' if in_pose else 'POSE_HLT'
        # Create Pose Asset only means anything in pose mode; hiding rather than
        # removing keeps the gizmo group from being rebuilt on every mode switch
        self.asset_button.hide = not in_pose
        buttons = [self.mode_button, self.browser_button]
        if in_pose:
            buttons.append(self.asset_button)
        for index, gizmo in enumerate(buttons):
            gizmo.matrix_basis[0][3] = BUTTON_MARGIN_X + index * BUTTON_GAP
            gizmo.matrix_basis[1][3] = BUTTON_MARGIN_Y


class MED_2_TOOLKIT_PT_Poses(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Poses"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Poses"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_poses
        if not libraryAvailable():
            layout.label(text="No pose assets bundled with this install", icon='ERROR')
            return
        if registeredLibrary() is None:
            layout.operator("medieval2toolkit.register_pose_library", icon='ASSET_MANAGER')
        col = layout.column(align=True)
        col.prop(settings, "browser_catalog", text="")
        if context.mode == 'POSE':
            col.operator("medieval2toolkit.toggle_pose_mode", text="Leave Pose Mode", icon='OBJECT_DATAMODE')
        else:
            col.operator("medieval2toolkit.toggle_pose_mode", text="Enter Pose Mode", icon='POSE_HLT')
        open_text = "Close Pose Library" if poseBrowserArea(context) is not None else "Open Pose Library"
        col.operator("medieval2toolkit.toggle_pose_browser", text=open_text, icon='ASSET_MANAGER')
        col.operator("medieval2toolkit.create_pose_asset", icon='ADD')

        # Most of the library is written against the IK control rig's bones, so a
        # unit with no controller has nothing for those poses to move.
        armature = activeArmature(context)
        box = layout.box()
        if armature is None:
            box.label(text="Select a rig to pose", icon='INFO')
        elif controlRigOf(armature) is None:
            box.label(text="'%s' has no control rig" % armature.name, icon='ERROR')
            box.label(text="Most poses here move IK bones,")
            box.label(text="which only the control rig has.")
            box.operator("medieval2toolkit.create_control_rig", icon='CON_KINEMATIC')
        else:
            box.label(text="Control rig: %s" % controlRigOf(armature).name, icon='CON_KINEMATIC')

        layout.prop(settings, "override_double_click")
        layout.prop(settings, "open_browser_with_pose_mode")
        layout.prop(settings, "show_pose_buttons")
        # the library lives inside the addon folder, which a reinstall replaces
        box = layout.box()
        box.label(text="New poses save into the addon's", icon='ERROR')
        box.label(text="assets\\Saved folder - copy it out")
        box.label(text="before updating the toolkit.")


class MED_2_TOOLKIT_PT_Texture_Assets(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Texture_Assets"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Textures to Assets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_poses
        col = layout.column(align=True)
        col.prop(settings, "texture_folder", text="")
        col.prop(settings, "texture_mark_assets", text="Mark as assets", toggle=1)
        col.operator("medieval2toolkit.textures_to_assets", icon='TEXTURE')
        if context.mode != 'OBJECT':
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Pose_Data,
    MED_2_TOOLKIT_OT_Register_Pose_Library,
    MED_2_TOOLKIT_OT_Toggle_Pose_Mode,
    MED_2_TOOLKIT_OT_Toggle_Pose_Browser,
    MED_2_TOOLKIT_OT_Create_Pose_Asset,
    MED_2_TOOLKIT_OT_Apply_Pose_Asset,
    MED_2_TOOLKIT_OT_Textures_To_Assets,
    MED_2_TOOLKIT_GGT_Pose_Buttons,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_poses = PointerProperty(type=MED_2_TOOLKIT_Pose_Data)
    pose_library.registerLibraryDeferred()
    registerKeymap()

def unregister():
    unregisterKeymap()
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_poses
