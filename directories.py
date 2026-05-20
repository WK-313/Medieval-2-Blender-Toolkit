
from pathlib import Path
import json, bpy

script_folder = Path(__file__).parent

def saveFolderPaths():
    mod_list = bpy.context.scene.med2_toolkit_reader.list_holder
    if bpy.context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_data = bpy.context.scene.med2_toolkit_reader.mods_filtered
        temp_list = mod_list.split(',')
        temp_list.remove(mod_data)
        temp_list.insert(0, mod_data)
        mod_list = ','.join(temp_list)
    else:
        mod_data = bpy.context.scene.med2_toolkit_reader.directory_mod_data
    directories = {
        "directory_med2": bpy.context.scene.med2_toolkit_reader.directory_med2,
        "directory_iwte": bpy.context.scene.med2_toolkit_reader.directory_iwte,
        "directory_mod_list": mod_list,
        "directory_mod_data": mod_data,
        "directory_models": bpy.context.scene.med2_toolkit_reader.directory_models,
        "directory_settlements": bpy.context.scene.med2_toolkit_reader.directory_settlements
    }
    with open(script_folder/('text/directories.json'), 'w') as directories_output:
        json.dump(directories, directories_output, indent=2)
    return{"FINISHED"}


def saveSettings():
    settings = {
        "hide_toggle" : bpy.context.scene.med2_toolkit_units.hide_toggle,
        "use_existing" : bpy.context.scene.med2_toolkit_units.use_existing,
        "frame_toggle" : bpy.context.scene.med2_toolkit_units.frame_toggle,
        "textured_toggle" : bpy.context.scene.med2_toolkit_units.textured_toggle,
        "use_existing_settlement" : bpy.context.scene.med2_toolkit_settlements.use_existing_settlement
    }
    with open(script_folder/('text/menu_settings.json'), 'w') as settings_output:
        json.dump(settings, settings_output, indent=2)
    return{"FINISHED"}