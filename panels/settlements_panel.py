"""The Settlements workmode: import a settlement's world and tidy its buildings.

The import half is the original: pick a folder and a pkg type, filter the
.worldpkgdesc list the mod scan produced, and hand the world to IWTE for
conversion when there is no .glb for it yet.

The building tools are the newer half. A settlement world is thousands of
objects, most of them copies of a handful of buildings placed at arbitrary
angles, so the two jobs worth automating are "which of these are the same
building" and "put this one back on the axis" - which is what the four
operators at the bottom do.
"""

import bpy
import os
from pathlib import Path
import json
from math import acos, radians
from bpy.props import StringProperty, CollectionProperty, IntProperty, EnumProperty, PointerProperty, BoolProperty, FloatProperty
from ..tasks.settlement_importer import settlementImporter
from ..tasks.task_writer import settlementTaskWriter
from..directories import saveFolderPaths, saveSettings


script_folder = Path(__file__).parent.parent

def selectedSettlement(context):
    """The highlighted list entry, or None when the list is empty or the index
    is stale - a filter change clears the list without the index following it."""
    settlements = context.scene.med2_toolkit_settlements_list
    index = context.scene.med2_toolkit_settlements_list_index
    if not settlements or index < 0:
        return None
    try:
        return settlements[index]
    except (IndexError, KeyError):
        return None

def sortFolders(self, context):
    with open(os.path.join(script_folder, "text", "settlement_folders.json"), 'r') as pkg_input:
        folders = json.load(pkg_input)
    folder_list = []
    for folder in folders:
        entry = (folder.lower(), folder.title(), "")
        folder_list.append(entry)
    entry = ("all", "All", "")
    folder_list.append(entry)
    return folder_list

def sortSettlements(self, context):
    with open(script_folder/('text/settlement_pkgs.json'), 'r') as import_settlements_input:
        settlements_dictionary = json.load(import_settlements_input)
    filter_folder = context.scene.med2_toolkit_settlements.settlement_folders
    filter_type = context.scene.med2_toolkit_settlements.pkg_types
    context.scene.med2_toolkit_settlements_list.clear()
    context.scene.med2_toolkit_settlements_list_index = 0
    for settlement in settlements_dictionary:
        settlement_entry = settlements_dictionary[settlement]
        # the folder is the full path the pkg was found at, and the filter is one
        # of its parts lowercased, so the match has to be case insensitive
        settlement_folder = str(settlement_entry.get("folder", "")).lower()
        type_matches = filter_type == 'all' or filter_type == settlement_entry.get("type", "")
        if not type_matches:
            continue
        if filter_folder != 'all' and filter_folder not in settlement_folder:
            continue
        item = context.scene.med2_toolkit_settlements_list.add()
        item.name = settlement.title()
        item.translation = settlement_entry["name"]
        item.folder = settlement_entry["folder"]
        item.world = settlement_entry["world"]
    snapToSearch(self, context)
    return{'FINISHED'}


def searchTerms(text):
    """The search box split into terms. Every term has to appear somewhere in
    the entry, so "fort north" finds both words in either field."""
    return [term for term in text.lower().split() if term]


def settlementMatches(item, terms):
    """Search the list name and the in-game name together - a settlement is
    known by either, and the list only shows the first."""
    haystack = ("%s %s" % (item.name, item.translation)).lower()
    return all(term in haystack for term in terms)


def snapToSearch(self, context):
    """Move the selection onto the first entry the search matches, so the
    fields and the Import button below the list never describe an entry the
    filter has hidden. The search filters the UIList rather than rebuilding
    the collection, so the index does not follow along by itself. Called on
    every keystroke and again after a rebuild, which parks the index on row 0
    regardless."""
    terms = searchTerms(context.scene.med2_toolkit_settlements.search)
    if not terms:
        return
    settlements = context.scene.med2_toolkit_settlements_list
    index = context.scene.med2_toolkit_settlements_list_index
    if 0 <= index < len(settlements) and settlementMatches(settlements[index], terms):
        return
    for position, settlement in enumerate(settlements):
        if settlementMatches(settlement, terms):
            context.scene.med2_toolkit_settlements_list_index = position
            return


#   ---------------  #
#   Building tools    #
#   ---------------  #

def marginCheck(value, base_value, pos_error, neg_error):
    """Are two measurements the same to within the error margin, both ways round."""
    if (value*pos_error >= base_value and value*neg_error <= base_value) and \
       (base_value*pos_error >= value and base_value*neg_error <= value):
        return True
    return False

def distanceCheck(location1, location2, margin):
    return abs(location1 - location2) <= margin

def buildingSignature(obj):
    """What a building is compared on: vertex count, surface area and height.

    Three cheap numbers rather than a mesh comparison. Two placements of the
    same building agree on all three however they are rotated or positioned,
    and two different buildings almost never do."""
    return (len(obj.data.vertices),
            sum(polygon.area for polygon in obj.data.polygons),
            obj.dimensions.z)

def signaturesMatch(first, second, pos_error, neg_error):
    return all(marginCheck(a, b, pos_error, neg_error) for a, b in zip(first, second))

def alignmentAngle(obj):
    """Z rotation that puts this building's walls back on the axis, or None.

    A wall is a face whose normal is horizontal, so the most common horizontal
    normal is the direction the building faces. Everything is folded into one
    90 degree quadrant - a building is square, so any of its four walls will do
    - and an angle past 45 degrees turns the short way instead."""
    polygons = [polygon for polygon in obj.data.polygons if abs(polygon.normal.z) < 1e-6]
    if not polygons:
        return None
    normals = [tuple(polygon.normal.normalized()) for polygon in polygons]
    dominant = max(set(normals), key=normals.count)
    # acos gives the angle off +X but never its sign, so the Y component supplies it
    angle = acos(dominant[0])*(-1 if dominant[1] >= 0 else 1) % radians(90)
    if angle > radians(45):
        angle -= radians(90)
    return angle


class MED_2_TOOLKIT_Settlement_Data(bpy.types.PropertyGroup):
    with open(script_folder/('text/menu_settings.json'), 'r') as settings_input:
            bool_settings = json.load(settings_input)
    use_existing_settlement: BoolProperty(name = "Use existing", description = "If on, use already converted files when importing settlements", default = bool_settings['use_existing_settlement'])
    # .get, not [...]: menu_settings.json is only written when it is missing, so an
    # install from before this setting existed still has a file without the key
    hide_complexes: BoolProperty(name = "Hide Complexes", description = "If on, hide the settlement's complex objects after importing it", default = bool_settings.get('hide_complexes', True))
    settlement_folders: EnumProperty(name = "Settlements", description = "List of settlement .worldpkgdesc files in the mod directory", items = sortFolders)
    # TEXTEDIT_UPDATE applies the value on every keystroke instead of waiting
    # for Return, which is what makes the list narrow as you type
    search: StringProperty(name = "Search", description = "Show only settlements whose name or in-game name contains what you type. Several words all have to match, in any order", default = "", options = {'TEXTEDIT_UPDATE'}, update = snapToSearch)
    pkg_types: EnumProperty(name = "Pkg Types", description = "PKG groups", items = [("settlement", "Settlement", ""), ("ambient", "Ambient", ""), ("ambientmisc", "Ambient Misc", ""), ("techtree", "Tech Tree", ""), ("rivercrossing", "River Crossing", ""), ("fieldfortification", "Field Fortification", ""), ("all", "All", "")])


class MED_2_TOOLKIT_PT_Settlements_Panel(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Settlements_Panel"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Settlements"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        if (context.scene.med2_toolkit_mode.mode_selection != 'settlements'):
            return False
        return True

    def draw(self, context):
        layout=self.layout
        layout.label(text = "W.I.P.")
        box = layout.box()
        col = box.column(align=True)
        grid = col.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
        grid.prop (context.scene.med2_toolkit_settlements, "use_existing_settlement", text="Use existing:", toggle = 1)
        grid.prop (context.scene.med2_toolkit_settlements, "hide_complexes", text="Hide Complexes:", toggle = 1)
        row = layout.row(align=True)
        row.prop(context.scene.med2_toolkit_settlements, "settlement_folders", text="Folder")
        row.prop(context.scene.med2_toolkit_settlements, "pkg_types", text="Type")
        row.operator("medieval2toolkit.sort_settlements", icon = "FILE_REFRESH", text = "")
        search = context.scene.med2_toolkit_settlements.search
        row = layout.row(align=True)
        row.prop(context.scene.med2_toolkit_settlements, "search", text="", icon="VIEWZOOM")
        if search:
            row.operator("medieval2toolkit.settlement_clear_search", icon = "X", text = "")
            terms = searchTerms(search)
            settlements = context.scene.med2_toolkit_settlements_list
            shown = sum(1 for settlement in settlements if settlementMatches(settlement, terms))
            layout.label(text="%d of %d settlements match" % (shown, len(settlements)),
                         icon='CHECKMARK' if shown else 'ERROR')
        col = layout.column()
        col.template_list("MED_2_TOOLKIT_UL_Settlement_List", "Settlements_list", context.scene, "med2_toolkit_settlements_list", context.scene, "med2_toolkit_settlements_list_index")
        settlement = selectedSettlement(context)
        if settlement is not None:
            col = layout.column(align=True)
            col.prop (settlement, "translation")
            col.prop (settlement, "world")
            col.prop (settlement, "folder")
        col = layout.column()
        col.operator("medieval2toolkit.import_settlement", text = "Import settlement")
        if(context.mode != 'OBJECT'):
            layout.enabled = False


class MED_2_TOOLKIT_PT_Settlement_Buildings(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Settlement_Buildings"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Buildings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'settlements'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator("medieval2toolkit.align_buildings", text = "Align Building")
        col.operator("medieval2toolkit.align_all_buildings", text = "Align All Buildings")
        col = layout.column(align=True)
        col.operator("medieval2toolkit.find_copied_buildings", text = "Find Building Copies")
        col.operator("medieval2toolkit.find_unique_buildings", text = "Find Unique Buildings")
        if(context.mode != 'OBJECT'):
            layout.enabled = False


class MED_2_TOOLKIT_OT_Find_Copied_Buildings(bpy.types.Operator):
    bl_idname = "medieval2toolkit.find_copied_buildings"
    bl_label = "Find Copied Buildings"
    bl_description = "Select every building in the scene that is a copy of the active one"
    bl_options = {'REGISTER', 'UNDO'}

    error_margin: FloatProperty(name = "Error Margin", description = "Percentage of difference allowed when searching for copied buildings", default = 2, min = 0, max = 100, subtype = 'PERCENTAGE', precision = 0)

    @classmethod
    def poll(cls, context):
        if len(context.selected_objects) == 0 or context.active_object is None:
            return False
        return context.active_object.select_get() and context.active_object.type == 'MESH'

    def draw(self, context):
        self.layout.prop(self, "error_margin", text="Error Margin:")

    def execute(self, context):
        if context.active_object is None or context.active_object.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first.")
            return{"CANCELLED"}
        pos_error = 1 + self.error_margin/100
        neg_error = 1 - self.error_margin/100
        base_object = context.active_object
        signature = buildingSignature(base_object)
        found = 0

        bpy.ops.object.select_all(action='DESELECT')
        base_object.select_set(True)
        context.view_layer.objects.active = base_object

        for obj in context.scene.objects:
            if obj == base_object or obj.type != 'MESH':
                continue
            if signaturesMatch(buildingSignature(obj), signature, pos_error, neg_error):
                obj.select_set(True)
                found += 1
        self.report({'INFO'}, "Found %d copies." % found)
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Find_Unique_Buildings(bpy.types.Operator):
    bl_idname = "medieval2toolkit.find_unique_buildings"
    bl_label = "Find Unique Buildings"
    bl_description = "Select one of every distinct building in the scene, ignoring the copies"
    bl_options = {'REGISTER', 'UNDO'}

    error_margin: FloatProperty(name = "Error Margin", description = "Percentage of difference allowed when searching for copied buildings", default = 2, min = 0, max = 100, subtype = 'PERCENTAGE', precision = 0)
    include_grouped: BoolProperty(name = "Compare Groups", description = "If on, compare a parented building's pieces as one building", default = True)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "error_margin", text="Error Margin:")
        layout.prop(self, "include_grouped", text="Compare Groups:")

    def execute(self, context):
        pos_error = 1 + self.error_margin/100
        neg_error = 1 - self.error_margin/100
        signatures = {}

        bpy.ops.object.select_all(action='DESELECT')

        for obj in context.scene.objects:
            if 'complex_' in obj.name.lower() or obj.type != 'MESH':
                continue
            signature = buildingSignature(obj)
            # a building split into pieces under one parent is one building, so its
            # pieces are summed into the parent's entry instead of counting apiece
            parent = obj.parent
            if self.include_grouped and parent is not None and 'complex_' not in parent.name.lower():
                if parent in signatures:
                    signatures[parent] = tuple(a + b for a, b in zip(signatures[parent], signature))
                    continue
                signatures[parent] = signature
                continue
            signatures[obj] = signature

        remaining = dict(signatures)
        unique = []
        for obj, signature in signatures.items():
            if obj not in remaining:
                continue
            remaining.pop(obj, None)
            for other, other_signature in signatures.items():
                if other not in remaining:
                    continue
                if signaturesMatch(other_signature, signature, pos_error, neg_error):
                    remaining.pop(other, None)
            unique.append(obj)

        for obj in unique:
            obj.select_set(True)
        if unique:
            context.view_layer.objects.active = unique[0]
        self.report({'INFO'}, "Found %d unique buildings." % len(unique))
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Align_Buildings(bpy.types.Operator):
    bl_idname = "medieval2toolkit.align_buildings"
    bl_label = "Align Buildings"
    bl_description = "Rotate the selected buildings so their walls line up with the axis"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def execute(self, context):
        # the whole selection is rotated together, so the angle is taken from the
        # first building that has walls to read it off - the rest of a group is
        # placed against that one and has to keep its relative angle
        for obj in context.selected_objects:
            if obj is None or obj.type != 'MESH':
                continue
            if obj.parent and 'complex_' not in obj.parent.name.lower():
                continue
            angle = alignmentAngle(obj)
            if angle is None:
                continue
            context.view_layer.objects.active = obj
            bpy.ops.transform.rotate(value=angle, orient_axis='Z', orient_type='GLOBAL')
            return{"FINISHED"}
        self.report({'WARNING'}, "No suitable polygons found for alignment.")
        return{"CANCELLED"}


class MED_2_TOOLKIT_OT_Align_All_Buildings(bpy.types.Operator):
    bl_idname = "medieval2toolkit.align_all_buildings"
    bl_label = "Align All Buildings"
    bl_description = "Group the selected buildings by position and align each group to the axis"
    bl_options = {'REGISTER', 'UNDO'}

    distance_margin: FloatProperty(name = "Distance Margin", description = "How close two buildings have to be to count as one group", default = 10.0, subtype = 'DISTANCE')

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.type == 'MESH'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "distance_margin", text="Distance Margin:")

    def execute(self, context):
        margin = self.distance_margin
        selected = {obj: tuple(obj.location[:2]) for obj in context.selected_objects if obj.type == 'MESH'}

        # buildings standing on top of each other are pieces of one building, so
        # they are aligned as a group off whichever piece has readable walls
        groups = []
        grouped = set()
        for obj, location in selected.items():
            if obj in grouped:
                continue
            group = [obj]
            grouped.add(obj)
            for other, other_location in selected.items():
                if other in grouped:
                    continue
                if distanceCheck(location[0], other_location[0], margin) and \
                   distanceCheck(location[1], other_location[1], margin):
                    group.append(other)
                    grouped.add(other)
            groups.append(group)

        for group in groups:
            bpy.ops.object.select_all(action='DESELECT')
            context.view_layer.objects.active = group[0]
            for obj in group:
                obj.select_set(True)
            bpy.ops.medieval2toolkit.align_buildings()
        self.report({'INFO'}, "Aligned %d groups." % len(groups))
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Sort_Settlements(bpy.types.Operator):
    bl_idname = "medieval2toolkit.sort_settlements"
    bl_label = "Sort Settlements"
    bl_description = "Filter the settlements into a list based on the selected folder."

    def execute(self, context):
        saveFolderPaths()
        saveSettings()
        sortSettlements(self, context)
        self.report({'INFO'}, "Updated settlement list.")
        return{"FINISHED"}


class MED_2_TOOLKIT_OT_Import_Settlement(bpy.types.Operator):
    bl_idname = "medieval2toolkit.import_settlement"
    bl_label = "Import Settlement"
    bl_description = "Import the selected settlement."

    @classmethod
    def poll(cls, context):
        return bool(context.scene.med2_toolkit_settlements_list) and \
               context.scene.med2_toolkit_settlements_list_index >= 0

    def execute(self, context):
        settlement = selectedSettlement(context)
        if settlement is None:
            self.report({'ERROR'}, "Select a settlement first.")
            return{"CANCELLED"}
        settlement_folder = str(bpy.context.scene.med2_toolkit_reader.directory_settlements)
        if not Path(settlement_folder).exists():
            self.report({'ERROR'}, "Settlement folder not found: %s" % settlement_folder)
            return{"CANCELLED"}
        name = settlement.name
        world = settlement.world
        saveFolderPaths()
        saveSettings()
        settlementTaskWriter()
        result = settlementImporter(settlement_folder, name, world)
        if result != 'Finished':
            self.report({'ERROR'}, result)
            return{"CANCELLED"}
        self.report({'INFO'}, "Finished importing settlement.")
        return{"FINISHED"}


class MED_2_TOOLKIT_Settlement_List_Items(bpy.types.PropertyGroup):
    name: StringProperty(name="Pkg", description="Pkg file name")
    world: StringProperty(name="World", description="World file")
    translation: StringProperty(name="Name", description="Name of the settlement")
    folder: StringProperty(name="Folder", description="Location of the settlement")


class MED_2_TOOLKIT_OT_Settlement_Clear_Search(bpy.types.Operator):
    bl_idname = "medieval2toolkit.settlement_clear_search"
    bl_label = "Clear Search"
    bl_description = "Empty the search box and show every settlement again"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        context.scene.med2_toolkit_settlements.search = ""
        return{"FINISHED"}


class MED_2_TOOLKIT_UL_Settlement_List(bpy.types.UIList):
    def filter_items(self, context, data, property):
        """Hide the rows the search box does not match. Returning empty lists
        means "no filtering, no reordering", which is the untouched list."""
        terms = searchTerms(context.scene.med2_toolkit_settlements.search)
        if not terms:
            return [], []
        settlements = getattr(data, property)
        return [self.bitflag_filter_item if settlementMatches(settlement, terms) else 0
                for settlement in settlements], []

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.label(text=item.name)
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text = "")


classes = [
    MED_2_TOOLKIT_Settlement_Data,
    MED_2_TOOLKIT_OT_Sort_Settlements,
    MED_2_TOOLKIT_OT_Import_Settlement,
    MED_2_TOOLKIT_Settlement_List_Items,
    MED_2_TOOLKIT_OT_Settlement_Clear_Search,
    MED_2_TOOLKIT_UL_Settlement_List,
    MED_2_TOOLKIT_OT_Find_Copied_Buildings,
    MED_2_TOOLKIT_OT_Find_Unique_Buildings,
    MED_2_TOOLKIT_OT_Align_Buildings,
    MED_2_TOOLKIT_OT_Align_All_Buildings,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_settlements = PointerProperty(type=MED_2_TOOLKIT_Settlement_Data)
    bpy.types.Scene.med2_toolkit_settlements_list = CollectionProperty(type = MED_2_TOOLKIT_Settlement_List_Items)
    bpy.types.Scene.med2_toolkit_settlements_list_index = IntProperty(name = "Index of the selected settlement", default = 0)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_settlements
    del bpy.types.Scene.med2_toolkit_settlements_list
    del bpy.types.Scene.med2_toolkit_settlements_list_index
