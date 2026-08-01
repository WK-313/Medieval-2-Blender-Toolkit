import os
import json
import time
import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty,
                       IntProperty, PointerProperty, StringProperty)
from pathlib import Path

from ..directories import readJsonCached, saveFolderPaths, saveSettings
from ..tasks import card_renderer
from ..tasks.control_rig import CONTROL_RIG_TYPES, controlRigOf
from ..tasks.card_renderer import (CAMERA_ORTHO_SCALE, CARD_LIGHT_TYPES, CARD_TYPE_ITEMS, FULL_SIZE_FOLDER,
                                   HD_FOLDER, HD_PRESETS, LINE_ART_THICKNESS, MERC_FOLDER,
                                   SUN_STRENGTH, applyRenderSettings, buildRenderQueue, cardCameras, cardFolders,
                                   cardOutputParts, cardResolution, cardSuns, createCardCameras, defaultCardFolders,
                                   defaultLightStrength, deleteCardCameras, hdOrthoScale, hdResolution,
                                   lineArtObjects, openRendersWindow, renderCard, renderedPaths,
                                   setCardFolders, setupCardScene, shuffleImportedVariations,
                                   unitCardIndex)
from ..tasks.importer import hideVariations, postImport, unitChecker, unitImporter
from ..tasks.task_writer import engineTaskWriter, unitTaskWriter
from ..tasks.unit_exporter import open_folder
from .edu_panel import drawImportListFilters, sortFactions, unlistedArmatures
from .unit_export_panel import SEVERITY_ORDER, showResultsPopup

script_folder = Path(__file__).parent.parent

# Same EnumProperty callback caveat as edu_panel: Blender only keeps pointers to
# the strings an items callback returns, so they have to be kept alive here or
# the dropdown starts rendering blank entries.
_card_unit_enum_items = []

OWNERSHIP_FILTERS = [('ownership', 'Ownership', ''), ('era 0', 'Era 0', ''), ('era 1', 'Era 1', ''), ('era 2', 'Era 2', '')]


def cardUnits(self, context):
    """Units of the selected faction, filtered by ownership - the set the card
    import will bring in."""
    global _card_unit_enum_items
    unit_dictionary = readJsonCached(script_folder/('text/unit_dictionary.json'))
    settings = context.scene.med2_toolkit_cards
    faction_units = []
    for unit in unit_dictionary:
        if not settings.card_faction in unit_dictionary[unit]['Owners'][settings.card_filter]:
            continue
        faction_units.append((json.dumps(unit_dictionary[unit]), unit, ""))
    _card_unit_enum_items = faction_units
    return _card_unit_enum_items


def cardZoomChanged(self, context):
    """Keep every card camera on the same framing while it is driven from here.
    Individual cameras can still be tweaked afterwards - this only pushes when
    the panel value moves."""
    for camera in cardCameras(context.scene):
        camera.data.ortho_scale = self.card_zoom


def pushCardLight(scene):
    """Push the panel's light onto every card light already in the scene, so the
    settings are a live control rather than something only new cameras read."""
    settings = scene.med2_toolkit_cards
    for light in cardSuns(scene):
        light.data.type = settings.light_type
        light.data.energy = settings.sun_strength


def cardLightTypeChanged(self, context):
    """A sun at 500 blows every card out and a point lamp at 4 is black, so the
    strength follows the type onto that type's usual value. It stays editable
    afterwards - this only moves it when the type itself changes."""
    self.sun_strength = defaultLightStrength(self.light_type)
    pushCardLight(context.scene)


def cardLightChanged(self, context):
    pushCardLight(context.scene)


def cardTargets(context):
    """[(unit_id, faction, object)] the card tools act on: ticked entries in the
    imported models list, or - when nothing is ticked - the selected armatures.
    Returns (targets, description of where they came from)."""
    scene = context.scene
    settings = scene.med2_toolkit_cards
    targets = []
    seen = set()

    def add(unit_id, faction, model):
        if unit_id in seen:
            return
        seen.add(unit_id)
        targets.append((unit_id, faction or settings.card_faction, model))

    for item in scene.med2_toolkit_import_list:
        if not item.use:
            continue
        model = bpy.data.objects.get(item.object_name) if item.object_name else None
        if model is None:
            model = bpy.data.objects.get(item.name)
        if model is not None:
            add(item.id or item.name, item.faction, model)
    if targets:
        return targets, "ticked entries"

    # nothing ticked: fall back to the selection, looking each rig up in the list
    # so it still gets its unit id and faction where we know them
    by_object = {}
    for item in scene.med2_toolkit_import_list:
        if item.object_name:
            by_object.setdefault(item.object_name, item)
        by_object.setdefault(item.name, item)
    for obj in context.selected_objects:
        rig = obj if obj.type == 'ARMATURE' else None
        if rig is None and obj.parent is not None and obj.parent.type == 'ARMATURE':
            rig = obj.parent
        if rig is None and obj.name in by_object:
            # not a rig, but it is what an import list entry points at - a unit
            # whose model came in without an armature
            rig = obj
        if rig is None:
            continue
        item = by_object.get(rig.name)
        add(item.id or item.name if item else rig.name, item.faction if item else "", rig)
    return targets, "selected armatures"


class MED_2_TOOLKIT_Card_Data(bpy.types.PropertyGroup):
    card_type: EnumProperty(name = "Card type", description = "Which image the renderer writes, and where", items = CARD_TYPE_ITEMS)
    custom_size: BoolProperty(name = "Custom size", description = "Use a hand-picked card resolution instead of the card type's standard size", default = False)
    card_width: IntProperty(name = "Width", description = "Card width in pixels", default = 48, min = 1, soft_max = 512)
    card_height: IntProperty(name = "Height", description = "Card height in pixels", default = 66, min = 1, soft_max = 512)
    supersample: IntProperty(name = "Supersampling", description = ("Render this many times the card size. The compositor's rescale Transform takes it "
                                                                    "back down, so everything after it - the sharpen especially - still acts at final "
                                                                    "card pixel size. 10 is the 480x660 render the old card .blend files used"),
                             default = 10, min = 1, max = 16)
    render_samples: IntProperty(name = "Render samples", description = "EEVEE render samples used for the cards", default = 64, min = 1, soft_max = 512)
    save_full_size: BoolProperty(name = "Keep full-size render", description = ("Also save the render before the compositor scales it down to card size, as an "
                                                                                 "uncompressed PNG in a '%s' subfolder beside each card. It costs an extra "
                                                                                 "render pass per unit, with the rescale switched off" % FULL_SIZE_FOLDER),
                                 default = False)
    save_hd: BoolProperty(name = "Keep HD render", description = ("Render each unit a second time at HD resolution and save that as a PNG in an '%s' "
                                                                   "subfolder beside its card. The rescale and the smoothing blur are switched off for "
                                                                   "the pass, and the camera is widened so nothing the card shows falls outside the "
                                                                   "frame. It doubles the render time" % HD_FOLDER),
                          default = False)
    hd_preset: EnumProperty(name = "HD size", description = "Resolution of the HD pass, as a whole multiple of the 48x66 unit card", items = HD_PRESETS, default = '20')
    isolate_unit: BoolProperty(name = "Isolate unit", description = ("While a card renders, switch off everything except that unit, its camera, its sun and its "
                                                                      "outline - and switch the unit itself on if it was hidden. Everything is put back before the "
                                                                      "next camera. Without this a neighbouring unit reaching into the frame ends up on the card"),
                               default = True)
    isolate_visible_only: BoolProperty(name = "Visible only", description = ("Card only the VISIBLE part of the unit. The rest of the scene is switched off in the "
                                                                              "viewport as well as for the render, so the unit is left standing there on its own while "
                                                                              "its card renders, and everything is put back before the next one. Nothing hidden is put "
                                                                              "back on: a variation mesh, shield or helmet switched off by hand stays off the card, "
                                                                              "which the plain Isolate unit undoes. Only the camera and its light are ever forced on"),
                                       default = True)
    open_renders: BoolProperty(name = "Open renders when finished", description = ("When the render finishes, load every card it wrote and show them in a new window's "
                                                                                     "Image Editor. Use the image browse dropdown in that window to flip through them"),
                                default = True)
    add_line_art: BoolProperty(name = "Line art outline", description = ("Add a Grease Pencil Line Art object per unit collection, each set to Collection source "
                                                                          "so it only outlines its own unit. Contour plus material borders, edge marks and loose "
                                                                          "edges, following the scene camera - the setup unit_card_sample.blend uses"), default = True)
    line_art_thickness: FloatProperty(name = "Line thickness", description = ("Outline thickness measured in finished-card pixels, so 1.0 is a one pixel outline on "
                                                                               "the card whatever the supersampling or card size. Grease Pencil v3 radii are world "
                                                                               "space, which is why this is not the old modifier's Line Thickness number. The default "
                                                                               "0.30 is the line unit_card_sample.blend draws"),
                                      default = LINE_ART_THICKNESS, min = 0.05, soft_max = 5.0)
    add_sun: BoolProperty(name = "Add light", description = "Give each card camera its own light, aimed the same way as the camera. Only the light of the unit being rendered is lit", default = True)
    light_type: EnumProperty(name = "Light", description = "Which lamp each card camera carries", items = CARD_LIGHT_TYPES,
                             default = 'SUN', update = cardLightTypeChanged)
    sun_strength: FloatProperty(name = "Strength", description = ("Strength of each card camera's light. Switching the light type resets this to that "
                                                                   "type's usual value - 4 for a sun, 500 for a point lamp"),
                                default = SUN_STRENGTH, min = 0.0, soft_max = 1000.0, update = cardLightChanged)
    add_control_rig: BoolProperty(name = "Add control rig", description = ("Also build each unit's IK control rig, so it can be posed before the card is rendered. "
                                                                           "Units that already have one are left alone"), default = False)
    control_rig_type: EnumProperty(name = "Control rig", description = "Which IK layout to build for the units", items = CONTROL_RIG_TYPES, default = 'infantry')
    lift_sunken: BoolProperty(name = "Lift sunken units", description = ("Set a unit standing in the ground down on it - raised by exactly how far its "
                                                                          "lowest point is below z=0 - so the card camera frames it like every other "
                                                                          "unit. A unit fully above the floor, or one parked below the scene, is left "
                                                                          "alone"), default = True)
    card_zoom: FloatProperty(name = "Card zoom", description = "Orthographic width of the card cameras. Lower zooms in", default = CAMERA_ORTHO_SCALE, min = 0.01, soft_max = 10.0, update = cardZoomChanged)
    card_faction: EnumProperty(name = "Faction", description = "Faction to import units for, and the card folder used by units with no card_pic_dir", items = sortFactions)
    card_filter: EnumProperty(name = "Ownership filter", description = "Unit ownership filter", items = OWNERSHIP_FILTERS, default = 1)
    card_upgrade: IntProperty(name = "Armour upgrade", description = "Armour upgrade level to import for the cards. Units without that level fall back to their last one", default = 0, min = 0, max = 3)
    card_spacing: FloatProperty(name = "Unit spacing", description = ("Distance between imported units on X. It has to be wider than the card zoom "
                                                                      "or neighbouring units show up in the card"),
                                default = 2.0, min = 0.1, soft_max = 10.0)


class MED_2_TOOLKIT_Card_Folder(bpy.types.PropertyGroup):
    """One line of the card folder checklist. The list itself is scratch space for
    the Card Folders dialog - what it produces is written onto the rigs."""
    name: StringProperty(name = "Faction", description = "Display name of the faction")
    faction_id: StringProperty(name = "Faction ID", description = "Codename, which is also the ui/units subfolder name")
    enabled: BoolProperty(name = "Write here", description = "Write this unit's card into this faction's folder", default = False)


def factionFolderList():
    """[(display name, codename)] for the folder checklist: every faction of the
    mod that was last read, plus the mercenary folder."""
    factions = readJsonCached(script_folder/('text/available_factions.json'))
    entries = []
    # alphabetical, like every other faction list; Mercs is appended afterwards
    # because it is not a descr_sm_factions faction at all
    for display_name, faction_id in sorted(factions.items(), key=lambda entry: entry[0].lower()):
        if 'spawning' in display_name.lower() or 'spawning' in faction_id.lower():
            continue
        entries.append((display_name, faction_id))
    if not any(faction_id == MERC_FOLDER for _display_name, faction_id in entries):
        entries.append(("Mercs", MERC_FOLDER))
    return entries


def currentCardFolders(context, targets):
    """The folders the targets' cards go to today - their override, or where they
    would default to. Empty when the targets disagree, since one dialog writes one
    answer to all of them.

    The default is the renderer's own, so what the dialog opens ticked is what
    would be written if the dialog were never opened: the mercenary folder for a
    custom armature, every owning faction for an imported EDU unit.
    """
    settings = context.scene.med2_toolkit_cards
    _subfolder, _pattern, dir_key = cardOutputParts(settings)
    index = unitCardIndex()
    chosen = set()
    for unit_id, faction, model in targets:
        folders = cardFolders(model) or defaultCardFolders(index.get(unit_id), faction, dir_key)
        chosen.add(tuple(folders))
    if len(chosen) != 1:
        return []
    return list(chosen.pop())


# Render job in flight, shared with the panel so it can draw the progress bar.
_card_job = None


def cardProgress(job):
    if not job['entries']:
        return 1.0
    return job['index'] / len(job['entries'])


def redrawView3D(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def reportResults(operator, context, title, results):
    results = sorted(results, key=lambda result: SEVERITY_ORDER.get(result[0], 2))
    for level, message in results:
        operator.report({level}, message)
    showResultsPopup(context, title, results)


class MED_2_TOOLKIT_OT_Setup_Card_Scene(bpy.types.Operator):
    bl_idname = "medieval2toolkit.setup_card_scene"
    bl_label = "Set Up Card Compositor"
    bl_description = ("Create the card compositor group and set the render resolution, transparent film "
                      "and TARGA output the cards need. Cameras come from Create Card Cameras.")
    bl_options = {"REGISTER", "UNDO"}

    rebuild: BoolProperty(name = "Rebuild compositor", description = "Rebuild the compositor group from scratch, discarding any tweaks made to it", default = False)

    def execute(self, context):
        # the outlines are per unit collection, so this needs the same target
        # resolution the camera button uses
        targets, source = cardTargets(context)
        results = setupCardScene(context, self.rebuild, targets)
        if context.scene.med2_toolkit_cards.add_line_art and not targets:
            results.append(('WARNING', "No outlines built - tick some entries in the imported models list, or select an armature"))
        elif targets:
            results.append(('INFO', "Outlines built from %d %s" % (len(targets), source)))
        reportResults(self, context, "Card compositor ready", results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Create_Card_Cameras(bpy.types.Operator):
    bl_idname = "medieval2toolkit.create_card_cameras"
    bl_label = "Create Card Cameras"
    bl_description = ("Give every ticked entry in the imported models list its own card camera, sun and - when "
                      "Add control rig is on - its IK control rig, all placed in the unit's own collection. "
                      "With nothing ticked, the selected armatures are used instead.")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.med2_toolkit_cards
        targets, source = cardTargets(context)
        if not targets:
            self.report({'ERROR'}, "Tick some units in the imported models list, or select an armature")
            return {'CANCELLED'}
        rig_type = settings.control_rig_type if settings.add_control_rig else None
        results = createCardCameras(context, targets, settings.add_sun, settings.sun_strength,
                                    settings.card_zoom, rig_type, settings.light_type,
                                    settings.lift_sunken)
        results.append(('INFO', "Built from %d %s" % (len(targets), source)))
        reportResults(self, context, "Card cameras: %d unit(s)" % len(targets), results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Delete_Card_Cameras(bpy.types.Operator):
    bl_idname = "medieval2toolkit.delete_card_cameras"
    bl_label = "Delete Card Cameras"
    bl_description = "Remove every card camera and its sun from the scene."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(cardCameras(context.scene)) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        removed = deleteCardCameras(context.scene)
        self.report({'INFO'}, "Removed %d card camera(s)" % removed)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Look_Through_Card_Camera(bpy.types.Operator):
    bl_idname = "medieval2toolkit.look_through_card_camera"
    bl_label = "Look Through Camera"
    bl_description = "Make the selected unit's card camera the scene camera and look through it."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(cardCameras(context.scene)) > 0

    def execute(self, context):
        targets, _source = cardTargets(context)
        camera = None
        if targets:
            camera = card_renderer.cardCamera(targets[0][0])
        if camera is None:
            camera = cardCameras(context.scene)[0]
        context.scene.camera = camera
        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
        self.report({'INFO'}, "Looking through '%s'" % camera.name)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Import_Card_Units(bpy.types.Operator):
    bl_idname = "medieval2toolkit.import_card_units"
    bl_label = "Import Units for Cards"
    bl_description = ("Import one armour upgrade of every unit of the selected faction, evenly spaced on X so each "
                      "one can be framed on its own. Missing models are extracted with IWTE first.")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.med2_toolkit_cards
        model_folder = context.scene.med2_toolkit_reader.directory_models
        faction = settings.card_faction
        upgrade = settings.card_upgrade
        saveFolderPaths()
        saveSettings()
        unit_list = [json.loads(unit[0]) for unit in cardUnits(self, context)]
        if not unit_list:
            self.report({'ERROR'}, "No units found for that faction and ownership filter")
            return {'CANCELLED'}
        unitTaskWriter()
        engineTaskWriter()
        results = []
        imported = 0
        coordinates_x = 0.0
        broken = 0
        for unit_info in unit_list:
            try:
                unitChecker(model_folder, [unit_info], upgrade)
                # apply_offset=False: the units are laid out on a fixed grid here,
                # so the importer's own half-width spacing must stay out of the way
                offset = unitImporter(model_folder, unit_info, faction, [coordinates_x, 0, 0], upgrade, apply_offset=False)
            except (KeyError, IndexError) as error:
                # a whole faction is a much wider net than importing one unit at a
                # time, and big mods do carry units whose armour_ug_models or mount
                # name has no matching battle_models entry. One of those must not
                # take the rest of the faction down with it.
                broken += 1
                results.append(('WARNING', "Skipped '%s': no model data for %s" % (unit_info['ID'], error)))
                continue
            if offset == 0:
                results.append(('WARNING', "No model imported for '%s'" % unit_info['ID']))
                continue
            imported += 1
            coordinates_x += settings.card_spacing
        if broken:
            results.append(('WARNING', "%d unit(s) reference models that are not in the mod's battle_models.modeldb" % broken))
        rigs = shuffleImportedVariations(context, hideVariations)
        results.append(('INFO', "Imported %d of %d unit(s), %.1f apart on X" % (imported, len(unit_list), settings.card_spacing)))
        if rigs:
            results.append(('INFO', "Rolled variations on %d rig(s) in the imported models list" % rigs))
        postImport(self, context)
        reportResults(self, context, "Card import: %d unit(s)" % imported, results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Shuffle_Card_Variations(bpy.types.Operator):
    bl_idname = "medieval2toolkit.shuffle_card_variations"
    bl_label = "Shuffle All Variations"
    bl_description = "Re-roll the hidden variations of every rig in the imported models list, not just the selection."
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return len(context.scene.med2_toolkit_import_list) > 0

    def execute(self, context):
        rigs = shuffleImportedVariations(context, hideVariations)
        self.report({'INFO'}, "Rolled variations on %d rig(s)" % rigs)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Set_Card_Folders(bpy.types.Operator):
    bl_idname = "medieval2toolkit.set_card_folders"
    bl_label = "Tick Card Folders"
    bl_options = {"INTERNAL"}

    mode: EnumProperty(items = [('ALL', "All", "Tick every faction"),
                                ('NONE', "None", "Untick everything"),
                                ('MERC', "Mercs", "Untick everything and tick the mercenary folder only")],
                       default = 'NONE')

    def execute(self, context):
        for item in context.scene.med2_toolkit_card_folders:
            if self.mode == 'ALL':
                item.enabled = True
            elif self.mode == 'NONE':
                item.enabled = False
            else:
                item.enabled = item.faction_id == MERC_FOLDER
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Toggle_Card_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.toggle_card_folder"
    bl_label = "Toggle Card Folder"
    bl_options = {"INTERNAL"}

    index: IntProperty()

    @classmethod
    def description(cls, context, properties):
        folders = context.scene.med2_toolkit_card_folders
        if 0 <= properties.index < len(folders):
            return "Write the card into ui\\units\\%s" % folders[properties.index].faction_id
        return "Toggle this folder"

    def execute(self, context):
        folders = context.scene.med2_toolkit_card_folders
        if 0 <= self.index < len(folders):
            folders[self.index].enabled = not folders[self.index].enabled
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Edit_Card_Folders(bpy.types.Operator):
    bl_idname = "medieval2toolkit.edit_card_folders"
    bl_label = "Card Folders"
    bl_description = ("Pick which faction folders the cards of the ticked units are written into, instead of "
                      "letting the EDU's card_pic_dir decide. A unit several factions can hire needs its card "
                      "in each of their folders.")
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        targets, _source = cardTargets(context)
        if not targets:
            self.report({'ERROR'}, "Tick some units in the imported models list, or select an armature")
            return {'CANCELLED'}
        collection = context.scene.med2_toolkit_card_folders
        collection.clear()
        current = set(currentCardFolders(context, targets))
        for display_name, faction_id in factionFolderList():
            item = collection.add()
            item.name = display_name
            item.faction_id = faction_id
            item.enabled = faction_id in current
        # folders the units are pinned to that this mod has no faction for - a
        # hand-typed card_pic_dir - would otherwise be dropped silently
        for folder in sorted(current):
            if not any(item.faction_id == folder for item in collection):
                item = collection.add()
                item.name = folder
                item.faction_id = folder
                item.enabled = True
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, context):
        layout = self.layout
        targets, source = cardTargets(context)
        folders = context.scene.med2_toolkit_card_folders
        layout.label(text="Card folders for %d %s" % (len(targets), source), icon='FILE_FOLDER')
        row = layout.row(align=True)
        row.operator("medieval2toolkit.set_card_folders", text="All").mode = 'ALL'
        row.operator("medieval2toolkit.set_card_folders", text="None").mode = 'NONE'
        row.operator("medieval2toolkit.set_card_folders", text="Use Merc Folder", icon='SOLO_ON').mode = 'MERC'
        if not folders:
            layout.label(text="No factions found - run Read Mod Data first", icon='ERROR')
            return
        grid = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        for index, item in enumerate(folders):
            op = grid.operator("medieval2toolkit.toggle_card_folder", text=item.name, depress=item.enabled,
                               icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT')
            op.index = index
        chosen = [item.faction_id for item in folders if item.enabled]
        if chosen:
            layout.label(text="Writes into: %s" % ', '.join(chosen), icon='CHECKMARK')
        else:
            layout.label(text="Nothing ticked - the EDU's own card folder is used again", icon='INFO')

    def execute(self, context):
        targets, _source = cardTargets(context)
        if not targets:
            self.report({'ERROR'}, "Tick some units in the imported models list, or select an armature")
            return {'CANCELLED'}
        chosen = [item.faction_id for item in context.scene.med2_toolkit_card_folders if item.enabled]
        for _unit_id, _faction, model in targets:
            setCardFolders(model, chosen)
        if chosen:
            self.report({'INFO'}, "%d unit(s) now write their card into %s" % (len(targets), ', '.join(chosen)))
        else:
            self.report({'INFO'}, "%d unit(s) back to the folder the EDU picks" % len(targets))
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Render_Cards(bpy.types.Operator):
    bl_idname = "medieval2toolkit.render_cards"
    bl_label = "Render Cards"
    bl_description = "Render one card per card camera in the scene and write it into the card output folder."
    bl_options = {"REGISTER"}

    _timer = None
    # Set while stop() is running. Opening the render window spawns a new window,
    # which pumps events from inside stop() - a TIMER queued before the job was
    # cleared can re-enter modal() there, and used to land in renderNext with
    # _card_job already None ("'NoneType' object is not subscriptable").
    _stopping = False

    @classmethod
    def poll(cls, context):
        return _card_job is None and len(cardCameras(context.scene)) > 0

    def execute(self, context):
        global _card_job
        saveFolderPaths()
        width, height, supersample = applyRenderSettings(context)
        entries, results = buildRenderQueue(context)
        if not entries:
            reportResults(self, context, "Card render", results)
            return {'CANCELLED'}
        _card_job = {
            'entries': entries, 'index': 0, 'results': results, 'written': 0,
            'width': width, 'height': height, 'supersample': supersample,
            'scene_camera': context.scene.camera, 'start': time.time(), 'paths': [],
        }
        if bpy.app.background or context.window is None:
            while _card_job['index'] < len(entries):
                self.renderNext(context)
            return self.finish(context)
        wm = context.window_manager
        wm.progress_begin(0, 100)
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        redrawView3D(context)
        return {'RUNNING_MODAL'}

    def renderNext(self, context):
        job = _card_job
        if job is None or job['index'] >= len(job['entries']):
            return
        entry = job['entries'][job['index']]
        reason = renderCard(context, entry, job['width'], job['height'], job['supersample'])
        if reason is None:
            job['written'] += 1
            job['paths'].extend(renderedPaths(entry))
        else:
            job['results'].append(('ERROR', "%s: %s" % (entry['id'], reason)))
        job['index'] += 1

    def modal(self, context, event):
        if self._stopping:
            # re-entered from inside stop(); the outer call finishes the job
            return {'PASS_THROUGH'}
        if _card_job is None:
            return {'FINISHED'}
        if event.type == 'ESC':
            _card_job['results'].append(('WARNING', "Cancelled after %d card(s)" % _card_job['written']))
            return self.stop(context)
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        self.renderNext(context)
        wm = context.window_manager
        wm.progress_update(int(cardProgress(_card_job) * 100))
        redrawView3D(context)
        if _card_job['index'] < len(_card_job['entries']):
            return {'RUNNING_MODAL'}
        return self.stop(context)

    def stop(self, context):
        self._stopping = True
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        wm.progress_end()
        result = self.finish(context)
        redrawView3D(context)
        return result

    def finish(self, context):
        global _card_job
        job = _card_job
        _card_job = None
        context.scene.camera = job['scene_camera']
        results = job['results']
        elapsed = time.time() - job['start']
        failed = sum(1 for level, _ in results if level == 'ERROR')
        results.append(('INFO', "Wrote %d card(s) in %.1fs" % (job['written'], elapsed)))
        # opened before the popup, so the results are read over the renders
        if context.scene.med2_toolkit_cards.open_renders and job['paths']:
            results.append(openRendersWindow(context, job['paths']))
        reportResults(self, context, "Card render: %d written, %d failed" % (job['written'], failed), results)
        return {'FINISHED'}


class MED_2_TOOLKIT_OT_Open_Card_Folder(bpy.types.Operator):
    bl_idname = "medieval2toolkit.open_card_folder"
    bl_label = "Open Card Folder"
    bl_description = "Open the card output folder in the file explorer."

    def execute(self, context):
        open_folder(bpy.path.abspath(context.scene.med2_toolkit_reader.directory_unit_cards))
        return {'FINISHED'}


class MED_2_TOOLKIT_PT_Unit_Info(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Unit_Info"
    # ignored while the panel is embedded in the section strip; it is what puts
    # this under the main panel in the classic layout, like every other panel
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Card Units"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_info'

    def draw(self, context):
        # Importing units is the Import section's job - this used to carry its own
        # copy of the faction/filter/upgrade importer, which was the same thing
        # twice. What is left is the list of what is already in the scene, which
        # is how the card tools are told which units to work on.
        layout = self.layout
        layout.operator("medieval2toolkit.shuffle_card_variations", icon='FILE_REFRESH')
        layout.label(text="Units in the scene - tick the ones to card")
        drawImportListFilters(layout, context)
        row = layout.row()
        row.template_list("MED_2_TOOLKIT_UL_Import_List", "Card_list", context.scene,
                          "med2_toolkit_import_list", context.scene, "med2_toolkit_import_list_index")
        row = layout.row(align=True)
        row.operator("medieval2toolkit.check_import_items", text="Tick All").mode = 'ALL'
        row.operator("medieval2toolkit.check_import_items", text="None").mode = 'NONE'
        row.operator("medieval2toolkit.check_import_items", text="Invert").mode = 'INVERT'
        # rigs that were never brought in through the importer - hand-built units,
        # or a .glb dragged straight in - still deserve a card
        unlisted = len(unlistedArmatures(context, False))
        row = layout.row(align=True)
        row.operator("medieval2toolkit.add_armature_to_list", text="Add Selected").selection_only = True
        sub = row.row(align=True)
        sub.enabled = unlisted > 0
        sub.operator("medieval2toolkit.add_armature_to_list",
                     text="Add All Unlisted (%d)" % unlisted).selection_only = False
        # same list, so the same upkeep buttons the Unit Import panel has - a unit
        # that should not be carded has to be removable from here too
        row = layout.row(align=True)
        row.operator("medieval2toolkit.remove_item", text="Remove item", icon='X')
        row.operator("medieval2toolkit.purge_list", text="Purge list", icon='TRASH')
        layout.prop(context.scene.med2_toolkit_units, "delete_with_item", text="Delete objects with the entry")
        if context.mode != 'OBJECT':
            layout.enabled = False


class MED_2_TOOLKIT_PT_Card_Scene(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Card_Scene"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Card Scene"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_info'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_cards
        # last resort card folder: used only for a unit the EDU has no
        # card_pic_dir and no ownership for. It lived on the old import block, so
        # it moved here when that went
        layout.prop(settings, "card_faction", text="Fallback faction")
        col = layout.column(align=True)
        col.prop(settings, "card_type", text="")
        col.prop(settings, "custom_size", text="Custom size", toggle=1)
        if settings.custom_size:
            row = col.row(align=True)
            row.prop(settings, "card_width", text="W")
            row.prop(settings, "card_height", text="H")
        width, height = cardResolution(settings)
        col.prop(settings, "supersample", text="Supersampling")
        col.prop(settings, "render_samples", text="Samples")
        col.label(text="Render %dx%d, card %dx%d" % (width*settings.supersample, height*settings.supersample, width, height), icon='RESTRICT_RENDER_OFF')
        hd_width, hd_height = hdResolution(settings)
        col = layout.column(align=True)
        col.prop(settings, "save_hd", text="Keep HD %dx%d render" % (hd_width, hd_height), toggle=1)
        if settings.save_hd:
            col.prop(settings, "hd_preset", text="")
            col.label(text="A second render per unit, into '%s'" % HD_FOLDER, icon='IMAGE_DATA')
            col.label(text="Rescale and smoothing blur off for this pass")
            col.label(text="Camera widens to %.2f so the card's framing still fits"
                           % hdOrthoScale(settings, hd_width, hd_height))
        col.prop(settings, "save_full_size",
                 text="Keep %dx%d render too" % (width*settings.supersample, height*settings.supersample), toggle=1)

        box = layout.box()
        row = box.row(align=True)
        row.prop(settings, "add_line_art", text="Line Art Outline", toggle=1)
        sub = row.row(align=True)
        sub.prop(settings, "line_art_thickness", text="")
        sub.enabled = settings.add_line_art
        if settings.add_line_art:
            existing = lineArtObjects(context.scene)
            if existing:
                box.label(text="%d outline object(s), one per collection" % len(existing), icon='OUTLINER_OB_GREASEPENCIL')
            else:
                box.label(text="Built by Set Up Card Compositor", icon='INFO')
            box.label(text="%.2f px on the card, follows Zoom" % settings.line_art_thickness)

        box = layout.box()
        box.label(text="Cameras, Lighting & Rigs", icon='CAMERA_DATA')
        col = box.column(align=True)
        col.prop(settings, "card_zoom", text="Zoom")
        row = col.row(align=True)
        row.prop(settings, "add_sun", text="Light", toggle=1)
        sub = row.row(align=True)
        sub.prop(settings, "light_type", text="")
        sub.prop(settings, "sun_strength", text="")
        sub.enabled = settings.add_sun
        row = col.row(align=True)
        row.prop(settings, "add_control_rig", text="Control Rig", toggle=1)
        sub = row.row(align=True)
        sub.prop(settings, "control_rig_type", text="")
        sub.enabled = settings.add_control_rig
        col.prop(settings, "lift_sunken", text="Set units standing in the ground onto it", toggle=1)
        targets, source = cardTargets(context)
        col = box.column(align=True)
        col.operator("medieval2toolkit.create_card_cameras", icon='CON_CAMERASOLVER')
        col.label(text="%d %s" % (len(targets), source), icon='CHECKBOX_HLT' if targets else 'CHECKBOX_DEHLT')
        # everything above lands in each unit's own collection
        rigged = sum(1 for _id, _faction, model in targets
                     if model.type == 'ARMATURE' and controlRigOf(model) is not None)
        if targets:
            col.label(text="%d of %d already have a control rig" % (rigged, len(targets)), icon='CON_KINEMATIC')
        existing = len(cardCameras(context.scene))
        if existing:
            col = box.column(align=True)
            col.label(text="%d card camera(s) in the scene" % existing, icon='OUTLINER_OB_CAMERA')
            col.operator("medieval2toolkit.look_through_card_camera", icon='VIEW_CAMERA')
            col.operator("medieval2toolkit.delete_card_cameras", icon='TRASH')

        layout.operator("medieval2toolkit.setup_card_scene", icon='NODE_COMPOSITING')
        if context.mode != 'OBJECT':
            layout.enabled = False


class MED_2_TOOLKIT_PT_Card_Render(bpy.types.Panel):
    bl_idname = "MED_2_TOOLKIT_PT_Card_Render"
    bl_parent_id = "MED_2_TOOLKIT_PT_Main_Panel"
    bl_label = "Render"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Medieval 2 Toolkit"

    @classmethod
    def poll(cls, context):
        return context.scene.med2_toolkit_mode.mode_selection == 'unit_info'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.med2_toolkit_cards
        subfolder, pattern, _dir_key = card_renderer.cardOutputParts(settings)
        layout.label(text="Writes %s\\<dir>\\%s" % (subfolder, pattern % "unit"), icon='FILE_IMAGE')
        if settings.save_full_size:
            layout.label(text="plus %s\\<dir>\\%s\\unit.png" % (subfolder, FULL_SIZE_FOLDER), icon='IMAGE_DATA')
        if settings.save_hd:
            layout.label(text="plus %s\\<dir>\\%s\\unit.png" % (subfolder, HD_FOLDER), icon='IMAGE_DATA')

        box = layout.box()
        targets, source = cardTargets(context)
        row = box.row(align=True)
        row.operator("medieval2toolkit.edit_card_folders", icon='FILE_FOLDER')
        row.enabled = bool(targets)
        if targets:
            pinned = sum(1 for _unit_id, _faction, model in targets if cardFolders(model))
            current = currentCardFolders(context, targets)
            if current:
                box.label(text="<dir> = %s" % ', '.join(current), icon='CHECKMARK')
            else:
                box.label(text="These %s use different folders" % source, icon='INFO')
            if pinned:
                box.label(text="%d of %d pinned by hand" % (pinned, len(targets)), icon='PINNED')
        else:
            box.label(text="Tick units to change their folder", icon='INFO')
        col = layout.column(align=True)
        col.prop(settings, "isolate_unit", text="Isolate unit while rendering", toggle=1)
        sub = col.row(align=True)
        sub.prop(settings, "isolate_visible_only", text="Visible only", toggle=1)
        sub.enabled = settings.isolate_unit
        if settings.isolate_unit and settings.isolate_visible_only:
            col.label(text="Hidden parts stay off the card", icon='HIDE_ON')

        if _card_job is not None:
            job = _card_job
            layout.progress(factor=cardProgress(job), type='BAR',
                            text="Rendering %d/%d..." % (job['index'], len(job['entries'])))
            layout.label(text="Esc to stop", icon='INFO')
        else:
            layout.operator("medieval2toolkit.render_cards", icon='RENDER_STILL')
        layout.prop(settings, "open_renders")
        layout.operator("medieval2toolkit.open_card_folder", icon='FILE_FOLDER')
        if context.mode != 'OBJECT':
            layout.enabled = False


classes = [
    MED_2_TOOLKIT_Card_Data,
    MED_2_TOOLKIT_Card_Folder,
    MED_2_TOOLKIT_OT_Setup_Card_Scene,
    MED_2_TOOLKIT_OT_Create_Card_Cameras,
    MED_2_TOOLKIT_OT_Delete_Card_Cameras,
    MED_2_TOOLKIT_OT_Look_Through_Card_Camera,
    MED_2_TOOLKIT_OT_Import_Card_Units,
    MED_2_TOOLKIT_OT_Shuffle_Card_Variations,
    MED_2_TOOLKIT_OT_Set_Card_Folders,
    MED_2_TOOLKIT_OT_Toggle_Card_Folder,
    MED_2_TOOLKIT_OT_Edit_Card_Folders,
    MED_2_TOOLKIT_OT_Render_Cards,
    MED_2_TOOLKIT_OT_Open_Card_Folder,
    ]

def register():
    for item in classes:
        bpy.utils.register_class(item)
    bpy.types.Scene.med2_toolkit_cards = PointerProperty(type=MED_2_TOOLKIT_Card_Data)
    # scratch space for the Card Folders dialog: the answer is written onto the
    # rigs, so nothing here needs to survive the dialog
    bpy.types.Scene.med2_toolkit_card_folders = CollectionProperty(type=MED_2_TOOLKIT_Card_Folder)

def unregister():
    for item in classes:
        bpy.utils.unregister_class(item)
    del bpy.types.Scene.med2_toolkit_cards
    del bpy.types.Scene.med2_toolkit_card_folders
