import os
import re
import json
import unicodedata
from pathlib import Path

def eduReader(mod_folder):
    try:
        with open(os.path.join(mod_folder, 'descr_sm_factions.txt'), 'r', encoding="utf8") as descr_factions:
            lines = descr_factions.readlines()
            available_factions_list = [re.sub(";.*", " ", line).lower().rstrip().split()[1] for line in lines if line[:7].lower() == 'faction']
    except FileNotFoundError as error:
        return('No descr_sm_factions.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error:
        return('UnicodeError reading the descr_sm_factions.txt. Check that the file is saved in UTF-8 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)
    try:
        with open(os.path.join(mod_folder, 'text', 'expanded.txt'), 'r', encoding="utf16") as expanded:
            skips = ['_descr}', '_descr_short}']
            lines = expanded.readlines()
            expanded_lines = [line.lower().rstrip() for line in lines if line[0] == '{' and not any (x in line for x in skips)]
    except FileNotFoundError as error:
        return('No expanded.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error    :
        return('UnicodeError reading the expanded.txt. Check that the file is saved in UTF-16 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)

    faction_database = {}
    for faction in available_factions_list:
        for name in expanded_lines:
            if ('{%s' % faction) in name.split('}'):
                faction_name = ' '.join(x.title() for x in name.split('}')[1:])
                normalized_faction_name = unicodedata.normalize('NFKD', faction_name).encode('ascii', 'ignore')
                faction_database[normalized_faction_name.decode('ascii')] = faction
    try:
        with open(os.path.join(mod_folder, 'export_descr_unit.txt'), 'r', encoding="utf8") as edu:
            edu_keywords = ['type', 'dictionary', 'officer', 'formation', 'mount', 'engine', 'armour_ug_models', 'ownership', 'era', 'info_pic_dir', 'card_pic_dir']
            lines = edu.readlines()
            edu_lines = [re.sub(",|;.*", " ", line).lower().strip().split() for line in lines if not line.strip().startswith(';') and len(line.split()) > 1]
            edu_cleaned = []
            for line in edu_lines:
                if line[0] not in edu_keywords:
                    continue
                edu_cleaned.append(line)
    except FileNotFoundError as error:
        return('No export_descr_unit.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error:
        return('UnicodeError reading the export_descr_unit.txt. Check that the file is saved in UTF-8 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)
    
    try:
        with open(os.path.join(mod_folder, 'text', 'export_units.txt'), 'r', encoding="utf16") as export_units:
            skips = ['_descr}', '_descr_short}']
            lines = export_units.readlines()
            eu_lines = [line.lower().rstrip() for line in lines if line[0] == '{' and not any (x in line for x in skips)]
    except FileNotFoundError as error:
        return('No export_units.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error:
        return('UnicodeError reading the export_units.txt. Check that the file is saved in UTF-16 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)

    unit_id = ''
    unit_attachment = 'unused'
    unit_officers = []
    unit_formation = []
    unit_models = []
    unit_ownership = {'ownership': [], 'era 0': [], 'era 1': [], 'era 2': []}
    unit_info_dir = 'faction'
    unit_card_dir = 'faction'
    attachments = ['mount', 'engine']
    unit_data = {'ID': unit_id, 'Model': unit_models, 'Officers': unit_officers, 'Formation': unit_formation, 'Attachment': unit_attachment, 'Owners': unit_ownership, 'Info Card': unit_info_dir, 'Unit Card': unit_card_dir}
    temp_database = []
    for line in edu_cleaned:
        identifier = line[0]
        if identifier == 'type':
            unit_data = {'ID': unit_id, 'Model': unit_models, 'Officers': unit_officers, 'Formation': unit_formation, 'Attachment': unit_attachment, 'Owners': unit_ownership, 'Info Card': unit_info_dir, 'Unit Card': unit_card_dir}
            temp_database.append(unit_data)
            unit_id = ''
            unit_attachment = 'unused'
            unit_officers = []
            unit_formation = []
            unit_models = []
            unit_ownership = {'ownership': [], 'era 0': [], 'era 1': [], 'era 2': []}
            unit_info_dir = 'faction'
            unit_card_dir = 'faction'
        elif identifier == 'dictionary':
            unit_id = line[1]
        elif identifier == 'officer':
            unit_officers.append(' '.join(line[1:]))
        elif identifier == 'formation':
            unit_formation = (line[1:3])
        elif identifier in attachments:
            unit_attachment = [identifier, ' '.join(line[1:])]
        elif identifier == 'armour_ug_models':
            unit_models = line[1:]
        elif identifier == 'ownership':
            unit_ownership[identifier] = line[1:]
        elif identifier == 'era':
            unit_ownership[identifier+' '+line[1]] = line[2:]
        elif identifier == 'info_pic_dir':
            unit_info_dir = line[1]
        elif identifier == 'card_pic_dir':
            unit_card_dir = line[1]
    unit_data = {'ID': unit_id, 'Model': unit_models, 'Officers': unit_officers, 'Formation': unit_formation, 'Attachment': unit_attachment, 'Owners': unit_ownership, 'Info Card': unit_info_dir, 'Unit Card': unit_card_dir}
    temp_database.append(unit_data)

    unit_database = {}
    for unit in temp_database:
        for name in eu_lines:
            if ('{%s' % unit['ID']) in name.lower().split('}'):
                unit_name = ' '.join(x.title().strip() for x in name.split('}')[1:])
                normalized_unit_name = unicodedata.normalize('NFKD', unit_name).encode('ascii', 'ignore')
                unit_database[normalized_unit_name.decode('ascii')] = unit

    try:
        with open(os.path.join(mod_folder, 'descr_mount.txt'), 'r', encoding="utf8") as descr_mount:
            save = ['type', 'model', 'root_node_height', 'rider_offset']
            m_lines = descr_mount.readlines()
            mount_lines = [re.sub("(;.*)|(,)", " ", line).lower().rstrip().split() for line in m_lines if line[0] != ';' and any (x in line for x in save)]
    except FileNotFoundError as error:
        return('No descr_mount.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error:
        return('UnicodeError reading the descr_mount.txt. Check that the file is saved in UTF-8 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)

    mount_id = ''
    mount_model = ''
    mount_offset = ''
    mount_riders = []
    mount_data = {}
    mount_database = {}
    for line in mount_lines:
        identifier = line[0]
        if identifier == 'type':
            mount_id = ' '.join(line[1:])
            mount_riders = []
            mount_data = {}
        elif identifier == 'model':
            mount_model = line[1]
        elif identifier == 'rider_offset':
            mount_riders.append([line[1], line[3], line[2]])
            mount_data = {'Model': mount_model, 'Crew': mount_riders}
            mount_database[mount_id] = mount_data

    #   -------------  #
    #   Descr_engines  #
    #   -------------  #

    try:
        with open((os.path.join(mod_folder, 'descr_engines.txt')), 'r', encoding="utf8") as descr_engine:
            save = ['type', 'engine_mesh', 'engine_dock_dist', 'obstacle_x_radius']
            e_lines = descr_engine.readlines()
            engine_lines = [re.sub(";.*", " ", line).lower().rstrip().split() for line in e_lines if line[0] != ';' and any (x in line for x in save)]
    except FileNotFoundError as error:
        return('No descr_engines.txt found in the specified directory.\n%s' % error)
    except UnicodeError as error:
        return('UnicodeError reading the descr_engines.txt. Check that the file is saved in UTF-8 encoding. Alternatively, try to "save as" and replacing the old file.\n%s' % error)

    engine_id = ''
    engine_model = ''
    engine_crew = []
    engine_data = {}
    for line in engine_lines:
        identifier = line[0]
        if identifier == 'type':
            engine_id = ' '.join(line[1:])
            engine_crew = []
            engine_data = {}
            flag = 1
        elif identifier == 'engine_mesh' and flag == 1:
            engine_model = re.sub(".mesh.*", ".glb", line[1])
            flag = 0
        elif identifier == 'engine_dock_dist':
            y = line[1]
        elif identifier == 'obstacle_x_radius':
            x = line[1]
            engine_crew.append([x, y, '0'])
            engine_crew.append(['-'+x, y, '0'])
            engine_data = {'Model': engine_model, 'Crew': engine_crew}
            mount_database[engine_id] = engine_data

    #   --------------  #
    #   Save databases  #
    #   --------------  #

    parent_folder = Path(__file__).parent.parent
    with open((os.path.join(parent_folder, 'text', 'available_factions.json')), 'w') as available_factions_output:
        json.dump(faction_database, available_factions_output, indent=2)
    with open((os.path.join(parent_folder, 'text', 'unit_dictionary.json')), 'w') as units_output:
        json.dump(unit_database, units_output, indent=2)
    with open((os.path.join(parent_folder, 'text', 'attachment_dictionary.json')), 'w') as mounts_output:
        json.dump(mount_database, mounts_output, indent=2)
    
    return('Finished')