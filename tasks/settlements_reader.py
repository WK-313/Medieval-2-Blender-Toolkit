import os
import re
import bpy
import json
from pathlib import Path


def findPKGs():
    if bpy.context.scene.med2_toolkit_reader.mods_filtered != "custom":
        mod_directory = bpy.context.scene.med2_toolkit_reader.mods_filtered
    else:
        mod_directory = bpy.context.scene.med2_toolkit_reader.directory_mod_data

    settlement_folder = Path(mod_directory)/'settlements'
    settlement_subfolders = []
    # a mod with no settlements folder is not an error - it just has none to list
    if settlement_folder.exists():
        for item in settlement_folder.iterdir():
            if item.is_dir():
                settlement_subfolders.append(item.name.title())

    pkg_files = {}
    for root, dirs, files in os.walk(str(settlement_folder)):
        for filename in files:
            if filename.endswith(".worldpkgdesc"):
                folder_path = Path(root)/filename
                with open(folder_path, "r", encoding="ascii", errors="surrogateescape") as f:
                    text = f.read()
                text = text.replace('\r', '').replace('\n', '').lower()
                cleaned = ''
                for char in text:
                    if char.isprintable():
                        cleaned += char
                pkg_info = re.split(r'(archive|ambientmisc|ambient|techtree|rivercrossing|fieldfortification|settlement)', maxsplit=2, string=cleaned)
                remaining_string = pkg_info[4].split('settlements/', maxsplit=1)[1]
                remaining_string = re.split('.worldculture|environment', string=remaining_string)
                # relative to the mod and with NO leading separator: the importer
                # joins it onto the settlements output folder, and a leading one
                # would make it absolute and throw that folder away
                world = str(Path('data')/'settlements'/(remaining_string[0]+'.world'))
                pkg_data = {"name" : pkg_info[2], "type" : pkg_info[3], "world" : world, "folder" : str(folder_path)}
                # culture = remaining_string[2]
                # pkg_data = {"name" : pkg_info[2], "type" : pkg_info[3], "world" : world, "culture" : culture, "folder" : folder}
                pkg_files[filename] = pkg_data

    #   --------------  #
    #   Save databases  #
    #   --------------  #

    parent_folder = Path(__file__).parent.parent
    with open(os.path.join(parent_folder, "text", "settlement_folders.json"), 'w') as folders_output:
        json.dump(settlement_subfolders, folders_output, indent=2)

    with open(os.path.join(parent_folder, "text", "settlement_pkgs.json"), 'w') as pkg_output:
        json.dump(pkg_files, pkg_output, indent=2)

    return('Finished')
