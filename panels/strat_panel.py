"""The Strat workmode: a battle unit turned into a campaign map model.

The whole guide - combine the textures, strip the bones the strat skeleton has
not got, join, re-rig, one weight per vertex, remap the UVs, export, convert -
is two buttons here, or one if Build + Convert is used. tasks/strat_model.py
does the work; this file is the UI, the settings and the IWTE progress bar.
"""
import os
import time

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, PointerProperty,
                       StringProperty)

from ..directories import saveFolderPaths
from ..tasks.export_checks import activeExportArmature
from ..tasks.iwte_run import (IWTE_OUTPUT_TIMEOUT, finishIWTEJob, iwteOutputReady,
                              iwteProgress, redrawView3D, waitForIWTEJob)
from ..tasks.strat_model import (activeStratArmature, buildStratModel, checkCASTexture,
                                 exportStratCAS, exportStratGLB, installStratModel)
from ..tasks.unit_exporter import open_folder, selectedModFolder
from .unit_export_panel import showResultsPopup


def suggestedNames(context):
    """(model name, texture name) for the active rig. The unit export's own
    name is reused when it has one, so a unit exported as `harondor_mercs`
    becomes `harondor_mercs_strat` rather than `Armature.003_strat`."""
    armature = activeExportArmature(context)
    if armature is None:
        return '', ''
    export_data = getattr(armature, 'med2_toolkit_unit_export', None)
    base = (getattr(export_data, 'export_glb_name', '') or armature.name).strip()
    base = base.lower().replace(' ', '_')
    if base.startswith('armature_'):
        base = base[len('armature_'):]
    if not base.endswith('_strat'):
        base += '_strat'
    return base, base


class MED_2_TOOLKIT_Strat_Data(bpy.types.PropertyGroup):
    model_name: StringProperty(
        name = "Model name",
        description = "Name of the strat model. The .glb, the .cas and the output folder all take this name")
    texture_name: StringProperty(
        name = "Texture name",
        description = ("Name of the combined texture. The material, the image and the .tga on disk all take "
                       "this name, because the .cas records it and the campaign map crashes on load when it "
                       "does not match a file in the mod"))
    atlas_size: EnumProperty(
        name = "Atlas size",
        description = "Width of the combined texture. Each source texture gets a quarter of it",
        items = [('1024', "1024", "Each texture at 512"),
                 ('2048', "2048", "Each texture at 1024 - the size the guide recommends"),
                 ('4096', "4096", "Each texture at 2048")],
        default = '2048')
    atlas_layout: EnumProperty(
        name = "Layout",
        description = "How the main and attachment textures are laid out in the combined texture",
        items = [('square', "Square",
                  "A square texture with the two halves along the top and the bottom half unused. "
                  "The layout the strat model guide uses"),
                 ('wide', "Half Height",
                  "Half the height, main on the left and attachment on the right, nothing wasted. "
                  "Same resolution per texture in half the file size")],
        default = 'square')
    keep_source: BoolProperty(
        name = "Keep the battle model",
        description = ("Build on a copy in a new collection and leave the imported unit alone. "
                       "The build joins every mesh and throws bones away, so turning this off is destructive"),
        default = True)
    visible_only: BoolProperty(
        name = "Visible only",
        description = "Only include meshes that are visible, so hidden variants and armour upgrades stay out of the strat model",
        default = True)
    cas_format: EnumProperty(
        name = "Cas format",
        description = "Animation format IWTE writes the .cas in",
        items = [('m2', "M2", "Medieval 2"),
                 ('rr', "RR", "Rome Remastered"),
                 ('full', "Full", "Full format")],
        default = 'm2')
    skeleton_scale: FloatProperty(
        name = "Skeleton scale",
        description = ("Scale IWTE writes the skeleton back at. 1.0 for a model built from a battle unit, "
                       "which is what the strat skeleton is already at - only change this if the .cas a "
                       "model came from was extracted at another scale"),
        default = 1.0, min = 0.01, max = 10.0)
    install_directory: StringProperty(
        name = "Install to",
        description = "Folder in the mod the finished .cas and .tga are copied into",
        subtype = "DIR_PATH")

    last_build_dir: StringProperty(name = "Last build folder")
    last_texture: StringProperty(name = "Last combined texture")
    last_exported_glb: StringProperty(name = "Last exported GLB")
    last_cas: StringProperty(name = "Last converted cas")


#   ---------------  #
#   Build            #
#   ---------------  #

class MED_2_TOOLKIT_OT_Strat_Suggest_Names(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_suggest_names"
    bl_label = "Suggest Names"
    bl_description = "Fill the model and texture names in from the selected rig"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return activeExportArmature(context) is not None

    def execute(self, context):
        model, texture = suggestedNames(context)
        if not model:
            self.report({'ERROR'}, "Select the unit's armature first")
            return {'CANCELLED'}
        settings = context.scene.med2_toolkit_strat
        settings.model_name = model
        settings.texture_name = texture
        self.report({'INFO'}, "Named '%s'" % model)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Strat_Build(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_build"
    bl_label = "Create Strat Model"
    bl_description = ("Turn the selected battle unit into a strat model: combine the textures, fold the "
                      "weights of bones the strat skeleton has not got into their nearest parent, join every "
                      "mesh, re-rig it onto the strat skeleton with one bone per vertex, and remap the UVs")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and activeExportArmature(context) is not None

    def execute(self, context):
        saveFolderPaths()
        report, armature = buildStratModel(context)
        showResultsPopup(context, "Strat model build", report)
        if armature is None:
            self.report({'ERROR'}, report[0][1] if report else "Could not build the strat model")
            return {'CANCELLED'}
        warnings = [message for level, message in report if level == 'WARNING']
        if warnings:
            self.report({'WARNING'}, "Strat model built, but: " + "; ".join(warnings))
        else:
            self.report({'INFO'}, "Strat model built")
        return {'FINISHED'}


#   ---------------  #
#   Export           #
#   ---------------  #

class MED_2_TOOLKIT_OT_Strat_Export_GLB(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_export_glb"
    bl_label = "Export GLB"
    bl_description = "Write the strat model out as a GLB for IWTE to convert"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and activeStratArmature(context) is not None

    def execute(self, context):
        saveFolderPaths()
        error, path = exportStratGLB(context)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, "Exported %s" % os.path.basename(path))
        return {'FINISHED'}


# The one running IWTE conversion, read by the panel for its progress bar.
_iwte_job = None


class MED_2_TOOLKIT_OT_Strat_Convert_CAS(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_convert_cas"
    bl_label = "Convert to .cas (IWTE)"
    bl_description = ("Send the exported GLB to IWTE's extract_to_cas task - the same job as Model Files > "
                      "Cas Models > dae/ms3d to cas_mesh - and watch until the .cas is written")
    bl_options = {"REGISTER"}

    _timer = None

    @classmethod
    def poll(cls, context):
        return _iwte_job is None and bool(context.scene.med2_toolkit_strat.last_exported_glb)

    def execute(self, context):
        global _iwte_job
        saveFolderPaths()
        result = exportStratCAS(context)
        if isinstance(result, str):
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        _iwte_job = result
        if bpy.app.background or context.window is None:
            return self.finish(context, waitForIWTEJob(result))
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.2, window=context.window)
        wm.modal_handler_add(self)
        redrawView3D(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        job = _iwte_job
        context.window_manager.progress_update(int(iwteProgress(time.time() - job['start']) * 100))
        redrawView3D(context)
        if iwteOutputReady(job):
            return self.stop(context, True)
        if job['process'].poll() is None:
            return {'RUNNING_MODAL'}
        # process gone: IWTE writes the .cas late, so keep watching the folder
        if job.get('exit_time') is None:
            job['exit_time'] = time.time()
        if time.time() - job['exit_time'] < IWTE_OUTPUT_TIMEOUT:
            return {'RUNNING_MODAL'}
        return self.stop(context, False)

    def stop(self, context, success):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        result = self.finish(context, success)
        redrawView3D(context)
        return result

    def finish(self, context, success):
        global _iwte_job
        job = _iwte_job
        _iwte_job = None
        results = [finishIWTEJob(job, success)]
        if success:
            # the guide's "open the .cas and search for .tga" check, done here
            results.extend(checkCASTexture(context))
        level = 'ERROR' if any(entry[0] == 'ERROR' for entry in results) else 'INFO'
        showResultsPopup(context, "Strat conversion", results)
        self.report({level}, results[0][1])
        return {'FINISHED'} if success else {'CANCELLED'}


class MED_2_TOOLKIT_OT_Strat_Build_And_Convert(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_build_and_convert"
    bl_label = "Build + Convert"
    bl_description = ("The whole thing in one go: build the strat model, export the GLB and hand it to IWTE. "
                      "Stops and reports if the build finds something wrong")
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (_iwte_job is None and context.mode == 'OBJECT'
                and activeExportArmature(context) is not None)

    def execute(self, context):
        saveFolderPaths()
        report, armature = buildStratModel(context)
        if armature is None:
            showResultsPopup(context, "Strat model build", report)
            self.report({'ERROR'}, report[0][1] if report else "Could not build the strat model")
            return {'CANCELLED'}
        error, _path = exportStratGLB(context)
        if error:
            showResultsPopup(context, "Strat model build", report + [('ERROR', error)])
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        # the conversion reports on its own when it finishes, so the build's
        # findings are shown now rather than being lost behind it
        if any(level != 'INFO' for level, _ in report):
            showResultsPopup(context, "Strat model build", report)
        # INVOKE_DEFAULT so the conversion runs as its own modal operator with
        # its progress bar. Its RUNNING_MODAL is not passed on - this operator
        # has no modal() of its own to hand it to
        bpy.ops.medieval2toolkit.strat_convert_cas('INVOKE_DEFAULT')
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Strat_Check_CAS(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_check_cas"
    bl_label = "Check .cas Texture"
    bl_description = ("Read the texture name out of the converted .cas and compare it with the texture that "
                      "was written. A mismatch is what crashes the campaign map on load")
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.med2_toolkit_strat.last_cas)

    def execute(self, context):
        results = checkCASTexture(context)
        showResultsPopup(context, "Strat .cas texture", results)
        level = 'ERROR' if any(entry[0] == 'ERROR' for entry in results) else 'INFO'
        self.report({level}, results[0][1])
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Strat_Install(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_install"
    bl_label = "Copy to Mod"
    bl_description = "Copy the converted .cas and its .tga into the mod folder"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.med2_toolkit_strat.last_cas)

    def execute(self, context):
        results = installStratModel(context)
        showResultsPopup(context, "Strat install", results)
        level = 'ERROR' if any(entry[0] == 'ERROR' for entry in results) else 'INFO'
        self.report({level}, results[0][1])
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Strat_Open_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_open_folder"
    bl_label = "Open Output Folder"
    bl_description = "Open the folder the strat model was built into"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.med2_toolkit_strat.last_build_dir)

    def execute(self, context):
        open_folder(context.scene.med2_toolkit_strat.last_build_dir)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Strat_Guess_Install(bpy.types.Operator):
    bl_idname = "medieval2toolkit.strat_guess_install"
    bl_label = "Use Mod Folder"
    bl_description = "Point Install To at the selected mod's data folder"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        mod = bpy.path.abspath(selectedModFolder(context))
        if not mod or not os.path.isdir(mod):
            self.report({'ERROR'}, "No mod folder selected in Paths")
            return {'CANCELLED'}
        context.scene.med2_toolkit_strat.install_directory = mod
        self.report({'INFO'}, "Install folder set to %s" % mod)
        return {'FINISHED'}


#   ---------------  #
#   Panels           #
#   ---------------  #

class MED_2_TOOLKIT_PT_Strat_Build(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Strat_Build"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Strat Model"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'strat'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_strat
        armature = activeExportArmature(context)

        if armature is None:
            layout.label(text="Select the battle unit's armature", icon='INFO')
        else:
            # counted the way the build counts, so the number on screen is the
            # number of meshes that will actually be joined
            meshes = [obj for obj in armature.children_recursive
                      if obj.type == 'MESH' and (not settings.visible_only or obj.visible_get())]
            layout.label(text="%s - %d mesh(es)" % (armature.name, len(meshes)), icon='ARMATURE_DATA')

        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(settings, "model_name", text="Name")
        row.operator("medieval2toolkit.strat_suggest_names", icon='FILE_REFRESH', text="")
        col.prop(settings, "texture_name", text="Texture")

        col = layout.column(align=True)
        col.prop(settings, "atlas_size", text="Atlas")
        col.prop(settings, "atlas_layout", text="Layout")

        col = layout.column(align=True)
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.prop(settings, "keep_source", text="Keep Battle Model", toggle=1)
        grid.prop(settings, "visible_only", text="Visible Only", toggle=1)

        col = layout.column(align=True)
        col.scale_y = 1.2
        col.operator("medieval2toolkit.strat_build", icon='OUTLINER_OB_ARMATURE')
        col.operator("medieval2toolkit.strat_build_and_convert", icon='PLAY')

        if context.mode != 'OBJECT':
            layout.enabled = False


class MED_2_TOOLKIT_PT_Strat_Export(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Strat_Export"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Convert + Install"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'strat'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_strat

        col = layout.column(align=True)
        col.prop(settings, "cas_format", text="Format")
        col.prop(settings, "skeleton_scale", text="Skeleton Scale")

        col = layout.column(align=True)
        col.operator("medieval2toolkit.strat_export_glb", icon='EXPORT')
        if _iwte_job is not None:
            elapsed = time.time() - _iwte_job['start']
            verb = "Converting" if _iwte_job['process'].returncode is None else "Waiting for"
            col.progress(factor=iwteProgress(elapsed), type='BAR',
                         text="%s %s... %ds" % (verb, _iwte_job['output_name'], int(elapsed)))
        else:
            col.operator("medieval2toolkit.strat_convert_cas", icon='FILE_REFRESH')

        if settings.last_cas:
            box = layout.box()
            box.label(text=os.path.basename(settings.last_cas), icon='FILE_3D')
            box.operator("medieval2toolkit.strat_check_cas", icon='VIEWZOOM')
            row = box.row(align=True)
            row.prop(settings, "install_directory", text="")
            row.operator("medieval2toolkit.strat_guess_install", icon='FILE_FOLDER', text="")
            box.operator("medieval2toolkit.strat_install", icon='COPYDOWN')

        layout.operator("medieval2toolkit.strat_open_folder", icon='FILEBROWSER')
        layout.label(text="Then add a strat model entry in descr_character.txt", icon='INFO')

        if context.mode != 'OBJECT':
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Strat_Data,
    MED_2_TOOLKIT_OT_Strat_Suggest_Names,
    MED_2_TOOLKIT_OT_Strat_Build,
    MED_2_TOOLKIT_OT_Strat_Export_GLB,
    MED_2_TOOLKIT_OT_Strat_Convert_CAS,
    MED_2_TOOLKIT_OT_Strat_Build_And_Convert,
    MED_2_TOOLKIT_OT_Strat_Check_CAS,
    MED_2_TOOLKIT_OT_Strat_Install,
    MED_2_TOOLKIT_OT_Strat_Open_Folder,
    MED_2_TOOLKIT_OT_Strat_Guess_Install,
]


def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_strat = PointerProperty(type=MED_2_TOOLKIT_Strat_Data)


def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_strat
