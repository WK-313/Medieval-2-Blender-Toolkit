import bpy
import json
from pathlib import Path
from bpy.props import BoolProperty, StringProperty, PointerProperty, CollectionProperty, EnumProperty
from ..directories import saveFolderPaths
from ..tasks.unit_exporter import exportArmatureGLB, exportToMeshIWTE, open_folder
from ..tasks.export_checks import runSelectCleanup, exportMeshes, uniqueMaterials, materialImages
from ..tasks.bmdb_writer import parseRelativeUnitPath, parseSpriteAndFooter

script_folder = Path(__file__).parent.parent

# Kept alive at module level: Blender requires dynamic EnumProperty item
# strings to stay referenced, otherwise they get garbage collected.
_material_items = []
_material_items_none = []

def exportSetMaterials(context):
    obj = context.object
    if not obj or obj.type != 'ARMATURE':
        return []
    return uniqueMaterials(exportMeshes(context, obj))

def materialItems(self, context):
    global _material_items
    items = [(m.name, m.name, '') for m in exportSetMaterials(context)]
    if not items:
        items = [('none', 'None', 'No materials found on the armature meshes')]
    _material_items = items
    return _material_items

def materialItemsNone(self, context):
    global _material_items_none
    items = [('none', 'None', 'No attach material')]
    items += [(m.name, m.name, '') for m in exportSetMaterials(context)]
    _material_items_none = items
    return _material_items_none


class MED_2_TOOLKIT_Export_Faction(bpy.types.PropertyGroup):
    name: StringProperty(name = "Faction", description = "Display name of the faction")
    faction_id: StringProperty(name = "Faction ID", description = "Internal faction id used in battle_models.modeldb")
    enabled: BoolProperty(name = "Owned", description = "Include this faction in the generated BMDB entry", default = False)


class MED_2_TOOLKIT_Unit_Export_Data(bpy.types.PropertyGroup):
    export_visible_only: BoolProperty(name = "Visible Only", description = "Only export visible mesh children of the armature", default = True)
    export_animations: BoolProperty(name = "Export Animations", description = "Bake actions into the GLB. Slow and unnecessary for .mesh conversion, and reimports with the rig posed", default = False)
    export_glb_name: StringProperty(name = "GLB Name", description = "Name of the exported GLB file and its output subfolder", default = "export")
    last_export_dir: StringProperty(default = "", options = {'HIDDEN'})
    last_exported_glb: StringProperty(default = "", options = {'HIDDEN'})
    material_main: EnumProperty(name = "Main Material", description = "Material treated as the unit's main texture", items = materialItems)
    material_attach: EnumProperty(name = "Attach Material", description = "Material treated as the attachment texture", items = materialItemsNone)
    out_main: StringProperty(name = "Main", description = "Output name for the main texture (no extension)")
    out_main_norm: StringProperty(name = "Main Normal", description = "Output name for the main normal map (no extension)")
    out_attach: StringProperty(name = "Attach", description = "Output name for the attachment texture (no extension)")
    out_attach_norm: StringProperty(name = "Attach Normal", description = "Output name for the attachment normal map (no extension)")
    gen_blank_normals: BoolProperty(name = "Generate Blank Normal Maps", description = "Copy a blank normal map of matching size from the addon's normals folder for materials without one", default = False)
    generate_bmdb: BoolProperty(name = "Generate BMDB Entry", description = "Write a battle_models.modeldb entry text file on export", default = False)
    bmdb_unit_path: StringProperty(name = "Unit Path", description = "Folder for the unit inside the mod's data folder; only the part after \\data\\ is used", subtype = 'DIR_PATH')
    bmdb_sprite: StringProperty(name = "Sprite", description = "Sprite path for the entry, e.g. unit_sprites/example_sprite.spr")
    bmdb_footer: StringProperty(name = "Footer", description = "Entry footer (mounts/weapons/animation block). Use \\n for line breaks")
    copy_from_unit: BoolProperty(name = "Copy sprite and animations from a unit", description = "Parse the sprite and footer from an existing unit in the mod's battle_models.modeldb", default = False)


class MED_2_TOOLKIT_OT_Select_Cleanup(bpy.types.Operator):
    bl_idname = "medieval2toolkit.select_cleanup"
    bl_label = "Select + Cleanup"
    bl_description = "Deselect everything, select the armature and its meshes, then run naming, material, weight, UV and texture checks."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        results = runSelectCleanup(context)
        worst = 'INFO'
        for level, message in results:
            self.report({level}, message)
            if level == 'ERROR' or (level == 'WARNING' and worst == 'INFO'):
                worst = level
        counts = {'INFO': 0, 'WARNING': 0, 'ERROR': 0}
        for level, message in results:
            counts[level] += 1
        if counts['ERROR'] or counts['WARNING']:
            self.report({worst}, "Cleanup: %d error(s), %d warning(s), %d note(s) - see Info log for details" % (counts['ERROR'], counts['WARNING'], counts['INFO']))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Factions_Refresh(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_factions_refresh"
    bl_label = "Refresh Factions"
    bl_description = "Load the faction list from the last Read Mod Data."

    def execute(self, context):
        factions_file = script_folder/'text'/'available_factions.json'
        try:
            with open(factions_file, 'r') as factions_input:
                factions = json.load(factions_input)
        except FileNotFoundError:
            factions = {}
        if not factions:
            self.report({'ERROR'}, "No factions found - run Read Mod Data first")
            return {'CANCELLED'}
        collection = context.scene.med2_toolkit_export_factions
        previous = {item.faction_id: item.enabled for item in collection}
        collection.clear()
        for display_name, faction_id in factions.items():
            item = collection.add()
            item.name = display_name
            item.faction_id = faction_id
            item.enabled = previous.get(faction_id, False)
        self.report({'INFO'}, "Loaded %d factions" % len(collection))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Factions_Set(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_factions_set"
    bl_label = "Select All / None"
    bl_description = "Enable or disable ownership for all factions at once."

    select: BoolProperty(default = True)

    def execute(self, context):
        for item in context.scene.med2_toolkit_export_factions:
            item.enabled = self.select
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Copy_Sprite_Footer(bpy.types.Operator):
    bl_idname = "medieval2toolkit.copy_sprite_footer"
    bl_label = "Copy Sprite and Footer"
    bl_description = "Parse the selected unit's sprite and footer from the mod's battle_models.modeldb into the fields below."

    def execute(self, context):
        reader = context.scene.med2_toolkit_reader
        if reader.mods_filtered != "custom":
            mod_folder = reader.mods_filtered
        else:
            mod_folder = reader.directory_mod_data
        try:
            unit_info = json.loads(context.scene.med2_toolkit_units.import_unit)
        except (ValueError, TypeError):
            self.report({'ERROR'}, "Select a unit first (run Read Mod Data if the list is empty)")
            return {'CANCELLED'}
        if not unit_info.get('Model'):
            self.report({'ERROR'}, "Selected unit has no models")
            return {'CANCELLED'}
        model_name = unit_info['Model'][0]
        sprite, footer, error = parseSpriteAndFooter(bpy.path.abspath(mod_folder), model_name)
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        export_data = context.scene.med2_toolkit_unit_export
        export_data.bmdb_sprite = sprite
        export_data.bmdb_footer = footer.replace("\n", "\\n")
        self.report({'INFO'}, "Copied from '%s': sprite %s, footer %d line(s)" % (model_name, sprite, footer.count("\n") + 1))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Unit_GLB(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_glb"
    bl_label = "Export GLB + Convert Textures"
    bl_description = "Export the selected armature and its meshes to GLB, convert textures to .texture files, and optionally write a BMDB entry."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.object
        return obj is not None and obj.type == 'ARMATURE'

    def execute(self, context):
        saveFolderPaths()
        result = exportArmatureGLB(context)
        if not result.startswith("Finished"):
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        if result == "Finished":
            self.report({'INFO'}, "Export complete")
        else:
            self.report({'WARNING'}, "Export complete, " + result[len("Finished, "):])
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh(bpy.types.Operator):
    bl_idname = "medieval2toolkit.export_unit_iwte_mesh"
    bl_label = "Export to Mesh (IWTE)"
    bl_description = "Send the last exported GLB to IWTE to convert it into a .mesh file."
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        saveFolderPaths()
        result = exportToMeshIWTE(context)
        if result != "Finished":
            self.report({'ERROR'}, result)
            return {'CANCELLED'}
        self.report({'INFO'}, "IWTE mesh export started")
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Open_Export_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.open_export_folder"
    bl_label = "Open Output Folder"
    bl_description = "Open the last unit export folder in the file explorer."

    def execute(self, context):
        open_folder(context.scene.med2_toolkit_unit_export.last_export_dir)
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Unit_Export(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Unit_Export"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Unit Export"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        export_data = context.scene.med2_toolkit_unit_export

        col = layout.column(align=True)
        col.prop(export_data, "export_visible_only")
        col.prop(export_data, "export_animations")
        col.prop(export_data, "export_glb_name")

        layout.operator("medieval2toolkit.select_cleanup", icon='CHECKMARK')
        layout.operator("medieval2toolkit.export_unit_glb", icon='EXPORT')

        if export_data.last_export_dir:
            layout.operator("medieval2toolkit.open_export_folder", icon='FILE_FOLDER')

        layout.separator()
        layout.label(text="IWTE")
        layout.operator("medieval2toolkit.export_unit_iwte_mesh", icon='MOD_ARMATURE')

        if context.mode != 'OBJECT':
            layout.enabled = False


class MED_2_TOOLKIT_PT_Export_Materials(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Export_Materials"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Materials + Textures"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        export_data = context.scene.med2_toolkit_unit_export

        obj = context.object
        if not obj or obj.type != 'ARMATURE':
            layout.label(text="Select an armature to list materials", icon='INFO')
            return

        materials = exportSetMaterials(context)
        if len(materials) > 2:
            layout.label(text="More than 2 materials found (%d)" % len(materials), icon='ERROR')

        col = layout.column(align=True)
        col.prop(export_data, "material_main", text="Main")
        main_mat = bpy.data.materials.get(export_data.material_main)
        if main_mat:
            col.prop(main_mat, "name", text="Rename", icon='MATERIAL')
        col.separator()
        col.prop(export_data, "material_attach", text="Attach")
        attach_mat = bpy.data.materials.get(export_data.material_attach) if export_data.material_attach != 'none' else None
        if attach_mat:
            col.prop(attach_mat, "name", text="Rename", icon='MATERIAL')

        main_diff, main_norm = materialImages(main_mat) if main_mat else (None, None)
        attach_diff, attach_norm = materialImages(attach_mat) if attach_mat else (None, None)

        layout.separator()
        layout.label(text="Output Names:")
        grid = layout.column(align=True)

        def image_row(label, image, prop_name):
            row = grid.row(align=True)
            split = row.split(factor=0.45, align=True)
            split.label(text="%s: %s" % (label, image.name if image else "missing"), icon='IMAGE_DATA' if image else 'X')
            split.prop(export_data, prop_name, text="")

        image_row("Main", main_diff, "out_main")
        image_row("Main Normal", main_norm, "out_main_norm")
        if attach_mat:
            image_row("Attach", attach_diff, "out_attach")
            image_row("Attach Normal", attach_norm, "out_attach_norm")

        if (main_mat and not main_norm) or (attach_mat and not attach_norm):
            layout.prop(export_data, "gen_blank_normals")


class MED_2_TOOLKIT_PT_Export_BMDB(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Export_BMDB"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "BMDB Entry"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_export'

    def draw(self, context):
        layout = self.layout
        export_data = context.scene.med2_toolkit_unit_export
        reader = context.scene.med2_toolkit_reader

        layout.prop(export_data, "generate_bmdb")
        if not export_data.generate_bmdb:
            return

        col = layout.column(align=True)
        col.prop(reader, "directory_med2", text="Medieval 2")
        row = col.row(align=True)
        row.prop(reader, "mods_filtered", text="Mod")
        row.operator("medieval2toolkit.refresh_mods", icon = "FILE_REFRESH", text = "")
        if reader.mods_filtered == "custom":
            col.prop(reader, "directory_mod_data", text="Manual Path")
        col.operator("medieval2toolkit.reader", text="Read Mod Data")

        layout.separator()
        row = layout.row(align=True)
        row.label(text="Ownership:")
        row.operator("medieval2toolkit.export_factions_refresh", icon='FILE_REFRESH', text="")
        op = row.operator("medieval2toolkit.export_factions_set", text="All")
        op.select = True
        op = row.operator("medieval2toolkit.export_factions_set", text="None")
        op.select = False
        factions = context.scene.med2_toolkit_export_factions
        if not factions:
            layout.label(text="Press refresh after Read Mod Data", icon='INFO')
        else:
            grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
            for item in factions:
                grid.prop(item, "enabled", text=item.name)

        layout.separator()
        col = layout.column(align=True)
        col.prop(export_data, "bmdb_unit_path", text="Unit Path")
        relative = parseRelativeUnitPath(export_data.bmdb_unit_path) if export_data.bmdb_unit_path else ""
        if relative:
            col.label(text="Entry path: %s" % relative, icon='FILE_FOLDER')
        col.prop(export_data, "bmdb_sprite", text="Sprite")
        col.prop(export_data, "bmdb_footer", text="Footer")

        layout.prop(export_data, "copy_from_unit")
        if export_data.copy_from_unit:
            col = layout.column(align=True)
            col.prop(context.scene.med2_toolkit_units, "import_faction", text="Faction")
            col.prop(context.scene.med2_toolkit_units, "import_filter", text="Filter")
            col.prop(context.scene.med2_toolkit_units, "import_unit", text="Unit")
            col.operator("medieval2toolkit.copy_sprite_footer", icon='COPYDOWN')


classes = [
    MED_2_TOOLKIT_Export_Faction,
    MED_2_TOOLKIT_Unit_Export_Data,
    MED_2_TOOLKIT_OT_Select_Cleanup,
    MED_2_TOOLKIT_OT_Export_Factions_Refresh,
    MED_2_TOOLKIT_OT_Export_Factions_Set,
    MED_2_TOOLKIT_OT_Copy_Sprite_Footer,
    MED_2_TOOLKIT_OT_Export_Unit_GLB,
    MED_2_TOOLKIT_OT_Export_Unit_IWTE_Mesh,
    MED_2_TOOLKIT_OT_Open_Export_Folder,
    MED_2_TOOLKIT_PT_Unit_Export,
    MED_2_TOOLKIT_PT_Export_Materials,
    MED_2_TOOLKIT_PT_Export_BMDB,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_unit_export = PointerProperty(type=MED_2_TOOLKIT_Unit_Export_Data)
    bpy.types.Scene.med2_toolkit_export_factions = CollectionProperty(type=MED_2_TOOLKIT_Export_Faction)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_unit_export
    del bpy.types.Scene.med2_toolkit_export_factions
