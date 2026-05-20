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

    settlement_folder = os.path.join(mod_directory, "settlements")
    settlement_subfolders = []
    directory = os.listdir(settlement_folder)
    for item in directory:
        if os.path.isdir(os.path.join(settlement_folder, item)):
            settlement_subfolders.append(item.title())

    pkg_files = {}
    pkg_data = {}
    for root, dirs, files in os.walk(settlement_folder):
        for filename in files:
            if filename.endswith(".worldpkgdesc"):
                folder  = os.path.join(root, filename)
                with open(folder, "r", encoding="ascii", errors="surrogateescape") as f:
                    text = f.read()
                text = text.replace('\r', '').replace('\n', '').lower()
                cleaned = ''
                for char in text:
                    if char.isprintable():
                        cleaned += char
                pkg_info = re.split(r'(archive|ambientmisc|ambient|techtree|rivercrossing|fieldfortification|settlement)', maxsplit=2, string=cleaned)
                print(pkg_info)
                remaining_string = pkg_info[4].split('settlements/', maxsplit=1)[1]
                print(remaining_string)
                remaining_string = re.split('.worldculture|environment', string=remaining_string)
                print(remaining_string)
                world = ('\\data\\settlements\\'+remaining_string[0]+'.world').replace('/', '\\')
                pkg_data = {"name" : pkg_info[2], "type" : pkg_info[3], "world" : world, "folder" : folder}
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