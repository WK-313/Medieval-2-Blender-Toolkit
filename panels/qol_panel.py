import bpy
from bpy.props import BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from ..tasks.armature_tools import skeletonItems, parentToSkeleton
from ..tasks.control_rig import (CONTROL_RIG_TYPES, controlRigOf, controlledRigs, createControlRig,
                                 deleteControlRig, isControlRig)
from ..tasks.unit_groups import createGroupControlRigs, groupParts, groupRoot
from ..tasks.mesh_mirror import M2_SIDE_NAME, applyMirror, cutMirror, flipMirror
from ..tasks.paint_symmetry import PAINT_NAMES, paintRig, togglePaintSymmetry
from ..tasks.export_checks import (
    OPT_SUFFIX, DEFAULT_UV_NAME, cleanUVLayers, splitNumberSuffix, hasOptSuffix, addOptSuffix,
    removeOptSuffix, splitOptSuffix,
)

# Enum identifiers cannot safely carry spaces, so map them to the actual
# in-mesh prefix strings ("cannon ball0" really does contain a space).
PART_PREFIXES = [
    ('WEAPON0', 'Weapon0', 'weapon0'),
    ('WEAPON1', 'Weapon1', 'weapon1'),
    ('PRIMARYACTIVE0', 'PrimaryActive0', 'primaryactive0'),
    ('PRIMARYACTIVE1', 'PrimaryActive1', 'primaryactive1'),
    ('PRIMARYPASSIVE0', 'PrimaryPassive0', 'primarypassive0'),
    ('PRIMARYPASSIVE1', 'PrimaryPassive1', 'primarypassive1'),
    ('SECONDARYACTIVE0', 'SecondaryActive0', 'secondaryactive0'),
    ('SECONDARYACTIVE1', 'SecondaryActive1', 'secondaryactive1'),
    ('SECONDARYPASSIVE0', 'SecondaryPassive0', 'secondarypassive0'),
    ('SECONDARYPASSIVE1', 'SecondaryPassive1', 'secondarypassive1'),
    ('SHIELD0', 'Shield0', 'shield0'),
    ('SHIELD1', 'Shield1', 'shield1'),
    ('SHIELDACTIVE0', 'ShieldActive0', 'shieldactive0'),
    ('SHIELDACTIVE1', 'ShieldActive1', 'shieldactive1'),
    ('SHIELDPASSIVE0', 'ShieldPassive0', 'shieldpassive0'),
    ('SHIELDPASSIVE1', 'ShieldPassive1', 'shieldpassive1'),
    ('RAMROD0', 'Ramrod0', 'ramrod0'),
    ('CANNON_BALL0', 'Cannon Ball0', 'cannon ball0'),
    ('BALLISTA_ARROW0', 'Ballista Arrow0', 'ballista arrow0'),
]
PREFIX_LOOKUP = {identifier: prefix for identifier, _, prefix in PART_PREFIXES}


class MED_2_TOOLKIT_QOL_Data(bpy.types.PropertyGroup):
    vert_mapping: EnumProperty(
        name="Vertex Mapping",
        items=[
            ('NEAREST', "Nearest Vertex", ""),
            ('EDGEINTERP_NEAREST', "Nearest Edge Interpolated", ""),
            ('POLYINTERP_NEAREST', "Nearest Face Interpolated", ""),
        ],
        default='POLYINTERP_NEAREST'
    )
    clear_groups: BoolProperty(name = "Clear Existing Groups", default = True)
    mirror_axes: BoolVectorProperty(
        name="Mirror Axes", description="Local axes to cut and mirror; select one or more",
        size=3, subtype='XYZ', default=(True, False, False))
    mirror_weights: BoolProperty(
        name="Mirror Weights", default=True,
        description="Swap left/right bone groups on mirrored copies; disable to apply geometry with the source weights unchanged")
    mirror_ignore_items: BoolProperty(
        name="Ignore Primary/Secondary Weights", default=False,
        description="Preserve source weights on objects whose names start with primary or secondary; their geometry still mirrors")
    mirror_keep_y: EnumProperty(
        name="Y Side", items=[('NEGATIVE', "Keep -Y", "Rebuild +Y from -Y"),
                               ('POSITIVE', "Keep +Y", "Rebuild -Y from +Y")], default='NEGATIVE')
    mirror_keep_z: EnumProperty(
        name="Z Side", items=[('NEGATIVE', "Keep -Z", "Rebuild +Z from -Z"),
                               ('POSITIVE', "Keep +Z", "Rebuild -Z from +Z")], default='NEGATIVE')
    mirror_keep: EnumProperty(
        name="Keep Side",
        description="Which side of local X=0 Cut + Mirror keeps; the other side is deleted and rebuilt from it",
        items=[
            ('NEGATIVE', "Keep -X", "Delete everything at X>0 and mirror the -X half onto it"),
            ('POSITIVE', "Keep +X", "Delete everything at X<0 and mirror the +X half onto it"),
        ],
        default='NEGATIVE'
    )
    smooth_weights: BoolProperty(name = "Smooth Weights", description = "After the transfer, run Blender's vertex group smooth over every target mesh. The mapping leaves hard edges where it jumps from one source vertex to the next, and the smoothing softens them. Untick to keep the transferred weights exactly as they came across", default = True)
    smooth_repeat: IntProperty(name = "Smoothing", description = "How many smoothing passes to run on each target mesh. More passes spread the weights further; 5 is what the transfer used to do unconditionally", default = 5, min = 1, max = 100)
    smooth_factor: FloatProperty(name = "Strength", description = "How far each smoothing pass moves a weight towards its neighbours' average. 0.5 is Blender's own default", default = 0.5, min = 0.0, max = 1.0)
    skeleton: EnumProperty(name = "Skeleton", description = "Skeleton from the addon's armatures folder to parent selected meshes to", items = skeletonItems)
    rename_prefix: EnumProperty(name = "Part Prefix", description = "Prefix applied by Apply Prefix to Selected", items = [(i, label, '') for i, label, _ in PART_PREFIXES], default = 'PRIMARYACTIVE0')


class MED_2_TOOLKIT_OT_Weight_Transfer(bpy.types.Operator):
    """Transfer vertex weights from active to selected objects"""
    bl_idname = "medieval2toolkit.weight_transfer"
    bl_label = "Transfer Weights"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.med2_toolkit_qol

        source_obj = context.active_object
        if not source_obj or source_obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh")
            return {'CANCELLED'}

        selected_objs = [o for o in context.selected_objects if o.type == 'MESH' and o != source_obj]
        if not selected_objs:
            self.report({'WARNING'}, "No other mesh objects selected")
            return {'CANCELLED'}

        if settings.clear_groups:
            for obj in selected_objs:
                obj.vertex_groups.clear()

        orig_active = context.view_layer.objects.active
        orig_selected = context.selected_objects[:]

        for o in context.selected_objects:
            o.select_set(False)
        source_obj.select_set(True)
        for obj in selected_objs:
            obj.select_set(True)
        context.view_layer.objects.active = source_obj

        bpy.ops.object.data_transfer(
            data_type='VGROUP_WEIGHTS',
            vert_mapping=settings.vert_mapping,
            layers_select_src='ALL',
            layers_select_dst='NAME',
            mix_mode='REPLACE',
            mix_factor=1.0,
        )

        # soften the hard edges the mapping leaves behind
        if settings.smooth_weights:
            for obj in selected_objs:
                for o in context.selected_objects:
                    o.select_set(False)
                obj.select_set(True)
                context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.object.vertex_group_smooth(group_select_mode='ALL',
                                                   factor=settings.smooth_factor,
                                                   repeat=settings.smooth_repeat)
                bpy.ops.object.mode_set(mode='OBJECT')

        for o in context.selected_objects:
            o.select_set(False)
        for o in orig_selected:
            o.select_set(True)
        context.view_layer.objects.active = orig_active

        if settings.smooth_weights:
            smoothed = "smoothed %dx at strength %.2f" % (settings.smooth_repeat, settings.smooth_factor)
        else:
            smoothed = "no smoothing"
        self.report({'INFO'}, "Transferred weights to %d object(s) (%s): %s"
                    % (len(selected_objs), smoothed, ", ".join(obj.name for obj in selected_objs)))
        return {'FINISHED'}


class MirrorOperation:
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return (context.mode in {'OBJECT', 'EDIT_MESH'}
                and any(o.type == 'MESH' for o in context.selected_objects))

    def execute(self, context):
        from .unit_export_panel import showResultsPopup
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        # Meshes can be selected with no active object.
        original_mode = context.object.mode if context.object else 'OBJECT'
        reports = []
        completed = 0
        if original_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            for obj in meshes:
                try:
                    lines = self.mirrorMesh(context, obj)
                    reports.extend(('INFO', line) for line in lines)
                    completed += 1
                except (ValueError, RuntimeError) as exc:
                    reports.append(('ERROR', f'{obj.name}: {exc}'))
        finally:
            # Stay in Object mode after a change: finishing in Edit mode records
            # only an Edit-mode undo step, so Ctrl+Z would keep the modifier.
            if original_mode != 'OBJECT' and not completed:
                bpy.ops.object.mode_set(mode=original_mode)
        reports.sort(key=lambda item: item[0] != 'ERROR')
        showResultsPopup(context, self.bl_label, reports)
        self.report({'INFO'} if completed else {'WARNING'}, '; '.join(line for _, line in reports))
        return {'FINISHED'} if completed else {'CANCELLED'}


class MED_2_TOOLKIT_OT_Cut_Mirror(MirrorOperation, bpy.types.Operator):
    bl_idname = "medieval2toolkit.cut_mirror"
    bl_label = "Cut + Mirror"
    bl_description = "Bisect selected meshes on the selected local axes, keep the chosen sides and add a Mirror with clipping"

    def mirrorMesh(self, context, obj):
        settings = context.scene.med2_toolkit_qol
        sides = tuple(getattr(settings, prop) == 'POSITIVE'
                      for prop in ('mirror_keep', 'mirror_keep_y', 'mirror_keep_z'))
        return cutMirror(obj, axes=settings.mirror_axes, keep_sides=sides)


class MED_2_TOOLKIT_OT_Apply_Mirror(MirrorOperation, bpy.types.Operator):
    bl_idname = "medieval2toolkit.apply_mirror_weights"
    bl_label = "Apply Mirror + Weights"
    bl_description = "Apply the Cut + Mirror modifier; optionally swap left/right bone weights on mirrored copies"

    def mirrorMesh(self, context, obj):
        settings = context.scene.med2_toolkit_qol
        return applyMirror(context, obj, mirror_weights=settings.mirror_weights,
                           ignore_primary_secondary=settings.mirror_ignore_items)


class MED_2_TOOLKIT_OT_Flip_Mirror(MirrorOperation, bpy.types.Operator):
    bl_idname = "medieval2toolkit.flip_mirror"
    bl_label = "Mirror + Flip Weights"
    bl_description = "Reflect the whole mesh across local X=0 and swap left/right bone weights"

    def mirrorMesh(self, context, obj):
        return flipMirror(obj)


class MED_2_TOOLKIT_OT_Paint_Symmetry(bpy.types.Operator):
    bl_idname = "medieval2toolkit.paint_symmetry"
    bl_label = "Medieval II Paint Symmetry"
    bl_description = "Use Blender-compatible left/right names while painting and restore the game names before export"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        rig = paintRig(context.object)
        return (context.mode in {'OBJECT', 'PAINT_WEIGHT', 'POSE'} and rig is not None
                and (context.object.type == 'MESH' or PAINT_NAMES in rig.data))

    def execute(self, context):
        from .unit_export_panel import showResultsPopup
        rig = paintRig(context.object)
        restoring = PAINT_NAMES in rig.data
        try:
            lines = togglePaintSymmetry(rig, context.object)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        title = "Restore Medieval II Bone Names" if restoring else "Medieval II Paint Symmetry Enabled"
        showResultsPopup(context, title, [('INFO', line) for line in lines])
        self.report({'INFO'}, title)
        return {'FINISHED'}


def drawPaintSymmetry(self, context):
    rig = paintRig(context.object)
    if rig is None:
        return
    if PAINT_NAMES in rig.data:
        self.layout.operator("medieval2toolkit.paint_symmetry", text="Restore Medieval II Bone Names")
    elif context.object.type == 'MESH' and any(M2_SIDE_NAME.fullmatch(b.name) for b in rig.data.bones):
        self.layout.operator("medieval2toolkit.paint_symmetry", text="Enable Medieval II Paint Symmetry")


class MED_2_TOOLKIT_OT_Clean_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.clean_number_suffix"
    bl_label = "Clean Number Suffix"
    bl_description = "Remove the .001 style suffix from selected objects. If the base name is taken, the two objects swap names."
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cleaned = 0
        for obj in context.selected_objects:
            # Only the trailing .001 number is stripped; an intentional __opt
            # marker sits inside the base and is preserved untouched
            # (object__opt.001 -> object__opt).
            base, number = splitNumberSuffix(obj.name)
            if number:
                holder = bpy.data.objects.get(base)
                if holder and holder is not obj:
                    # Steal the base name; the previous holder takes our suffix
                    suffixed_name = obj.name
                    obj.name = base + ".__swap__"
                    holder.name = suffixed_name
                obj.name = base
                cleaned += 1
        self.report({'INFO'}, f"Cleaned names of {cleaned} object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_Bones_Upper_To_Lower(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_bones_upper_to_lower"
    bl_label = "Rename Bones _R/_L → _r/_l"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        arm = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0

        for bone in arm.edit_bones:
            name = bone.name

            if name.endswith("_RThigh"):
                new = name.replace("_RThigh", "_rthigh")
            elif name.endswith("_LThigh"):
                new = name.replace("_LThigh", "_lthigh")
            else:
                new = name.replace("_R", "_r").replace("_L", "_l")

            if new != name:
                bone.name = new
                count += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Renamed {count} bones")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_Bones_Lower_To_Upper(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_bones_lower_to_upper"
    bl_label = "Rename Bones _r/_l → _R/_L"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != "ARMATURE":
            self.report({'ERROR'}, "Select an armature first")
            return {'CANCELLED'}

        arm = obj.data
        bpy.ops.object.mode_set(mode='EDIT')
        count = 0

        for bone in arm.edit_bones:
            name = bone.name

            if name.endswith("_rthigh"):
                new = name.replace("_rthigh", "_RThigh")
            elif name.endswith("_lthigh"):
                new = name.replace("_lthigh", "_LThigh")
            else:
                new = name.replace("_r", "_R").replace("_l", "_L")

            if new != name:
                bone.name = new
                count += 1

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Renamed {count} bones")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Rename_To_Prefix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.rename_to_prefix"
    bl_label = "Apply Prefix"
    bl_options = {'REGISTER', 'UNDO'}

    swap: BoolProperty(default = False)

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    @classmethod
    def description(cls, context, properties):
        if properties.swap:
            return "x__y or x_y becomes <prefix>__y: the part before the first underscore is replaced with the chosen prefix"
        return "x becomes <prefix>__x: the whole current name is kept after the prefix"

    def execute(self, context):
        prefix = PREFIX_LOOKUP[context.scene.med2_toolkit_qol.rename_prefix]
        renamed = []
        for obj in context.selected_objects:
            name = obj.name
            # The trailing __opt marker (and any .001 number) is intentional:
            # set it aside so it isn't read as the prefix separator or collapsed
            # to a single underscore, then re-append it to the rebuilt name.
            core, opt, number = splitOptSuffix(name)
            if self.swap:
                if "__" in core:
                    suffix = core.split("__", 1)[1]
                elif "_" in core:
                    suffix = core.split("_", 1)[1]
                else:
                    suffix = core
            else:
                suffix = core
            # only the prefix separator may be a double underscore, so any
            # __ inside the kept part collapses to a single _
            suffix = suffix.replace("__", "_")
            new = "%s__%s%s%s" % (prefix, suffix, opt, number)
            if new != name:
                obj.name = new
                renamed.append("%s -> %s" % (name, obj.name))
        if renamed:
            self.report({'INFO'}, "Renamed %d object(s): %s" % (len(renamed), ", ".join(renamed)))
        else:
            self.report({'INFO'}, "No objects needed renaming")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Toggle_Opt_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_opt_suffix"
    bl_label = "Toggle __opt Suffix"
    bl_description = ("Add or remove the __opt optional-part marker on selected objects "
                      "(object <-> object__opt). It is inserted before any trailing number, "
                      "so object.001 becomes object__opt.001, and the cleanup tools leave it intact")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.selected_objects)

    def execute(self, context):
        renamed = []
        for obj in context.selected_objects:
            name = obj.name
            new = removeOptSuffix(name) if hasOptSuffix(name) else addOptSuffix(name)
            if new != name:
                obj.name = new
                renamed.append("%s -> %s" % (name, obj.name))
        if renamed:
            self.report({'INFO'}, "Toggled __opt on %d object(s): %s" % (len(renamed), ", ".join(renamed)))
        else:
            self.report({'INFO'}, "No objects needed changing")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Clean_UV_Layers(bpy.types.Operator):
    bl_idname = "medieval2toolkit.clean_uv_layers"
    bl_label = "Clean UV Maps"
    bl_description = ("Delete every UV map except the render one on each selected mesh - the layer with "
                      "the camera icon in the UV Maps list - and rename it to " + DEFAULT_UV_NAME + ", Blender's "
                      "default. A mesh carrying several UV maps exports all of "
                      "them into the GLB and IWTE reads whichever came first, so the unit can end up "
                      "textured off a map you were not looking at. Material UV Map nodes naming a layer "
                      "that goes are repointed at the survivor. The same tick box is on the export check")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        # late import: unit_export_panel is a sibling panel module, and only the
        # results popup is wanted from it
        from .unit_export_panel import SEVERITY_ORDER, showResultsPopup
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        results = cleanUVLayers(meshes)
        results = sorted(results, key=lambda r: SEVERITY_ORDER.get(r[0], 2))
        for level, message in results:
            self.report({level}, message)
        showResultsPopup(context, "Clean UV Maps: %d mesh(es)" % len(meshes), results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Recreate_Simplebake_UV(bpy.types.Operator):
    bl_idname = "medieval2toolkit.recreate_simplebake_uv"
    bl_label = "Recreate SimpleBake UV"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue

            uv_layers = obj.data.uv_layers

            existing = uv_layers.get("SimpleBake")
            if existing:
                uv_layers.remove(existing)

            new_uv = uv_layers.new(name="SimpleBake")
            uv_layers.active = new_uv
            count += 1

        self.report({'INFO'}, f"Recreated SimpleBake UV on {count} mesh object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Remove_Baked_Suffix(bpy.types.Operator):
    bl_idname = "medieval2toolkit.remove_baked_suffix"
    bl_label = "Remove _Baked Suffix"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.name.endswith("_Baked"):
                obj.name = obj.name[:-6]
                count += 1

        self.report({'INFO'}, f"Removed suffix from {count} object(s)")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_To_Skeleton(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_to_skeleton"
    bl_label = "Parent to Skeleton"
    bl_description = "Import the chosen skeleton and parent selected meshes to it, renaming vertex group _R/_L case to match the skeleton's bones. Selecting an armature re-rigs its meshes and removes the old skeleton."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=False)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Parented selection to skeleton")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_Sample_Weights(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_sample_weights"
    bl_label = "Rig with Sample Weights"
    bl_description = "Parent selected meshes to the skeleton and copy weights onto them from its sample body, then remove the sample meshes."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=True, delete_samples=True)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Rigged selection with sample weights")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Parent_Sample_Weights_Keep(bpy.types.Operator):
    bl_idname = "medieval2toolkit.parent_sample_weights_keep"
    bl_label = "Full Setup (Samples + Equipment)"
    bl_description = "Rig selected meshes with sample weights, keep the sample body for reference, and import the equipment props parented to the skeleton."
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and any(o.type in {'MESH', 'ARMATURE'} for o in context.selected_objects)

    def execute(self, context):
        result = parentToSkeleton(context, transfer_weights=True, delete_samples=False)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "Rigged selection; samples and equipment kept in scene")
        return {'FINISHED'}


def controlRigTargets(context):
    """Med2 skeletons in the selection that a controller could be built for."""
    targets = []
    for obj in context.selected_objects:
        rig = obj if obj.type == 'ARMATURE' else (obj.parent if obj.parent is not None and obj.parent.type == 'ARMATURE' else None)
        if rig is not None and not isControlRig(rig) and rig not in targets:
            targets.append(rig)
    active = context.active_object
    if not targets and active is not None and active.type == 'ARMATURE' and not isControlRig(active):
        targets.append(active)
    return targets


class MED_2_TOOLKIT_OT_Create_Control_Rig(bpy.types.Operator):
    bl_idname = "medieval2toolkit.create_control_rig"
    bl_label = "Add Control Rig"
    bl_description = ("Build the IK controller for the selected Medieval 2 skeleton and constrain the rig to it. "
                      "Most of the bundled pose library is written against this controller's bones")
    bl_options = {'REGISTER', 'UNDO'}

    rig_type: EnumProperty(name = "Control rig", description = "Which IK layout to build. Auto picks IK_Archer for bow skeletons and IK_Infantry otherwise", items = CONTROL_RIG_TYPES, default = 'auto')
    whole_unit: BoolProperty(
        name = "Whole unit",
        description = ("Build a controller for every rider or crew member of a mount or siege engine, not just the "
                       "armature that is selected. The mount or engine itself is skipped - none of its bones are on "
                       "a human controller - and each controller is kept parented under the unit so the riders stay "
                       "on it. Untick to build one for the selected armature alone"),
        default = True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and bool(controlRigTargets(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "rig_type")
        targets = self.rigTargets(context)
        layout.prop(self, "whole_unit")
        layout.label(text="Builds a controller for %d rig(s):" % len(targets), icon='CON_KINEMATIC')
        for rig in targets[:6]:
            layout.label(text=rig.name, icon='ARMATURE_DATA')
        if len(targets) > 6:
            layout.label(text="... and %d more" % (len(targets) - 6))

    def rigTargets(self, context):
        """What the dialog lists. With Whole unit on, a mount and any of its
        riders that are also selected collapse into the one unit."""
        targets = controlRigTargets(context)
        if not self.whole_unit:
            return targets
        roots = []
        for rig in targets:
            root = groupRoot(rig) or rig
            if root not in roots:
                roots.append(root)
        return roots

    def execute(self, context):
        targets = self.rigTargets(context)
        if not targets:
            self.report({'ERROR'}, "Select a Medieval 2 armature first")
            return {'CANCELLED'}
        built = 0
        already = 0
        skipped = []
        for rig in targets:
            if self.whole_unit:
                made, missed, had, results = createGroupControlRigs(context, rig, self.rig_type)
                built += made
                already += had
                skipped.extend(missed)
            else:
                controller, results = createControlRig(context, rig, self.rig_type)
                if controller is not None and not any(level == 'WARNING' and 'already has' in message
                                                      for level, message in results):
                    built += 1
            for level, message in results:
                self.report({level}, message)
        if skipped:
            self.report({'INFO'}, "No controller for %s - not a Medieval 2 human skeleton" % ", ".join(skipped))
        if built == 0:
            if already:
                self.report({'WARNING'}, "%d armature(s) already have a control rig" % already)
            return {'CANCELLED'}
        self.report({'INFO'}, "Built %d control rig(s)%s"
                    % (built, ", %d already had one" % already if already else ""))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Delete_Control_Rig(bpy.types.Operator):
    bl_idname = "medieval2toolkit.delete_control_rig"
    bl_label = "Remove Control Rig"
    bl_description = "Delete the control rig of the selection, un-parenting and un-constraining the skeletons it drives"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False
        return any(controlRigOf(obj) is not None for obj in context.selected_objects if obj.type == 'ARMATURE')

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        controllers = []
        for obj in context.selected_objects:
            if obj.type != 'ARMATURE':
                continue
            controller = controlRigOf(obj)
            if controller is not None and controller not in controllers:
                controllers.append(controller)
        freed = 0
        for controller in controllers:
            freed += deleteControlRig(controller)
        self.report({'INFO'}, "Removed %d control rig(s), freeing %d skeleton(s)" % (len(controllers), freed))
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Weight_Transfer(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Weight_Transfer"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Weight Transfer"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        box = layout.box()
        box.label(text="Mirror (local axes)")
        row = box.row(align=True)
        for index, axis in enumerate('XYZ'):
            row.prop(settings, "mirror_axes", index=index, text=axis, toggle=True)
        for index, prop in enumerate(('mirror_keep', 'mirror_keep_y', 'mirror_keep_z')):
            if settings.mirror_axes[index]:
                box.row().prop(settings, prop, expand=True)
        box.prop(settings, "mirror_weights")
        row = box.row()
        row.enabled = settings.mirror_weights
        row.prop(settings, "mirror_ignore_items")
        col = box.column(align=True)
        col.operator("medieval2toolkit.cut_mirror", icon='MOD_MIRROR')
        col.operator("medieval2toolkit.apply_mirror_weights",
                     text="Apply Mirror + Weights" if settings.mirror_weights else "Apply Mirror Only",
                     icon='CHECKMARK')
        box.operator("medieval2toolkit.flip_mirror", icon='MOD_MIRROR')
        drawPaintSymmetry(self, context)
        layout.operator("medieval2toolkit.weight_transfer", icon='MOD_DATA_TRANSFER')
        layout.prop(settings, "vert_mapping")
        layout.prop(settings, "clear_groups")
        layout.prop(settings, "smooth_weights")
        col = layout.column(align=True)
        col.enabled = settings.smooth_weights
        col.prop(settings, "smooth_repeat", text="Smoothing Passes")
        col.prop(settings, "smooth_factor", text="Strength")


class MED_2_TOOLKIT_PT_Armature(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Armature"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Armature"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        layout.prop(settings, "skeleton", text="Skeleton")
        col = layout.column(align=True)
        col.operator("medieval2toolkit.parent_to_skeleton", icon='ARMATURE_DATA')
        col.operator("medieval2toolkit.parent_sample_weights", icon='MOD_DATA_TRANSFER')
        col.operator("medieval2toolkit.parent_sample_weights_keep", icon='COMMUNITY')

        box = layout.box()
        box.label(text="IK Control Rig", icon='CON_KINEMATIC')
        existing = [controlRigOf(obj) for obj in context.selected_objects if obj.type == 'ARMATURE']
        existing = [rig for rig in existing if rig is not None]
        col = box.column(align=True)
        col.operator("medieval2toolkit.create_control_rig", icon='ADD')
        col.operator("medieval2toolkit.delete_control_rig", icon='TRASH')
        if existing:
            box.label(text="Selected: %s" % existing[0].name, icon='OUTLINER_OB_ARMATURE')
            box.label(text="Drives %d skeleton(s)" % len(controlledRigs(existing[0])))
        # a mount or a siege engine is several armatures, and Add Control Rig
        # covers all of them in one press
        parts = max([len(groupParts(obj)) for obj in context.selected_objects
                     if obj.type == 'ARMATURE' and not isControlRig(obj)] or [0])
        if parts > 1:
            box.label(text="Selected unit is %d armatures - one controller each" % parts, icon='GROUP')


class MED_2_TOOLKIT_PT_Rename_Tools(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Rename_Tools"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Rename Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_qol
        col = layout.column(align=True)
        col.operator("medieval2toolkit.clean_number_suffix", icon='FILE_REFRESH')
        col.operator("medieval2toolkit.rename_bones_upper_to_lower", icon='SORT_ASC')
        col.operator("medieval2toolkit.rename_bones_lower_to_upper", icon='SORT_DESC')
        layout.separator()
        col = layout.column(align=True)
        col.prop(settings, "rename_prefix", text="Prefix")
        op = col.operator("medieval2toolkit.rename_to_prefix", icon='ADD', text="Add Prefix (prefix__name)")
        op.swap = False
        op = col.operator("medieval2toolkit.rename_to_prefix", icon='ARROW_LEFTRIGHT', text="Swap Prefix (prefix__y)")
        op.swap = True
        col.operator("medieval2toolkit.toggle_opt_suffix", icon='CHECKBOX_HLT', text="Toggle __opt Suffix")


class MED_2_TOOLKIT_PT_QOL_Advanced(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_QOL_Advanced"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Advanced Tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("medieval2toolkit.clean_uv_layers", icon='GROUP_UVS')
        col.operator("medieval2toolkit.recreate_simplebake_uv", icon='UV')
        col.operator("medieval2toolkit.remove_baked_suffix", icon='X')


class MED_2_TOOLKIT_PT_Interface(bpy.types.Panel):
    """Addon-wide preferences, parked at the bottom of QOL because that is where
    the everyday settings live - the same properties are also in Blender's own
    Add-ons preferences."""
    bl_idname = "MED_2_TOOLKIT_PT_Interface"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Interface"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'qol'

    def draw(self, context):
        # imported here, not at module level: multi_panel imports this module for
        # its panel list, so the other direction has to stay a late import
        from .multi_panel import toolkitPreferences
        layout = self.layout
        preferences = toolkitPreferences(context)
        if preferences is None:
            layout.label(text="Add-on preferences are not available", icon='INFO')
            return
        layout.label(text="Panel layout:")
        layout.prop(preferences, "panel_layout", expand=True)
        layout.label(text="Kept in your Blender preferences,", icon='PREFERENCES')
        layout.label(text="so it holds for every .blend file.")


classes = [
    MED_2_TOOLKIT_QOL_Data,
    MED_2_TOOLKIT_OT_Cut_Mirror,
    MED_2_TOOLKIT_OT_Apply_Mirror,
    MED_2_TOOLKIT_OT_Flip_Mirror,
    MED_2_TOOLKIT_OT_Paint_Symmetry,
    MED_2_TOOLKIT_OT_Weight_Transfer,
    MED_2_TOOLKIT_OT_Clean_Suffix,
    MED_2_TOOLKIT_OT_Rename_Bones_Upper_To_Lower,
    MED_2_TOOLKIT_OT_Rename_Bones_Lower_To_Upper,
    MED_2_TOOLKIT_OT_Rename_To_Prefix,
    MED_2_TOOLKIT_OT_Toggle_Opt_Suffix,
    MED_2_TOOLKIT_OT_Clean_UV_Layers,
    MED_2_TOOLKIT_OT_Recreate_Simplebake_UV,
    MED_2_TOOLKIT_OT_Remove_Baked_Suffix,
    MED_2_TOOLKIT_OT_Parent_To_Skeleton,
    MED_2_TOOLKIT_OT_Parent_Sample_Weights,
    MED_2_TOOLKIT_OT_Parent_Sample_Weights_Keep,
    MED_2_TOOLKIT_OT_Create_Control_Rig,
    MED_2_TOOLKIT_OT_Delete_Control_Rig,
    ]

PAINT_SYMMETRY_PANELS = (
    'VIEW3D_PT_tools_weightpaint_symmetry',
    'VIEW3D_PT_tools_weightpaint_symmetry_for_topbar',
)


def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_qol = PointerProperty(type=MED_2_TOOLKIT_QOL_Data)
    for name in PAINT_SYMMETRY_PANELS:
        panel = getattr(bpy.types, name, None)
        if panel is not None:
            panel.append(drawPaintSymmetry)

def unregister():
    for name in PAINT_SYMMETRY_PANELS:
        panel = getattr(bpy.types, name, None)
        if panel is not None:
            panel.remove(drawPaintSymmetry)
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_qol
