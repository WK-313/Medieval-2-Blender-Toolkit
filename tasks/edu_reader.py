import os
import re
import json
import unicodedata
from pathlib import Path
from .text_io import readModLines

def eduReader(mod_folder):
    try:
        lines = readModLines(os.path.join(mod_folder, 'descr_sm_factions.txt'), 'utf-8')
        available_factions_list = [re.sub(";.*", " ", line).lower().rstrip().split()[1] for line in lines if line[:7].lower() == 'faction']
    except FileNotFoundError as error:
        return('No descr_sm_factions.txt found in the specified directory.\n%s' % error)
    try:
        lines = readModLines(os.path.join(mod_folder, 'text', 'expanded.txt'), 'utf-16')
        skips = ['_descr}', '_descr_short}']
        expanded_lines = [line.lower().rstrip() for line in lines if line[0] == '{' and not any (x in line for x in skips)]
    except FileNotFoundError as error:
        return('No expanded.txt found in the specified directory.\n%s' % error)

    faction_database = {}
    for faction in available_factions_list:
        for name in expanded_lines:
            if ('{%s' % faction) in name.split('}'):
                faction_name = ' '.join(x.title() for x in name.split('}')[1:])
                normalized_faction_name = unicodedata.normalize('NFKD', faction_name).encode('ascii', 'ignore')
                faction_database[normalized_faction_name.decode('ascii')] = faction
    try:
        lines = readModLines(os.path.join(mod_folder, 'export_descr_unit.txt'), 'utf-8')
        edu_keywords = ['type', 'dictionary', 'officer', 'formation', 'mount', 'engine', 'armour_ug_models', 'ownership', 'era', 'info_pic_dir', 'card_pic_dir']
        edu_lines = [re.sub(",|;.*", " ", line).lower().strip().split() for line in lines if not line.strip().startswith(';') and len(line.split()) > 1]
        edu_cleaned = []
        for line in edu_lines:
            if line[0] not in edu_keywords:
                continue
            edu_cleaned.append(line)
    except FileNotFoundError as error:
        return('No export_descr_unit.txt found in the specified directory.\n%s' % error)

    try:
        lines = readModLines(os.path.join(mod_folder, 'text', 'export_units.txt'), 'utf-16')
        skips = ['_descr}', '_descr_short}']
        eu_lines = [line.lower().rstrip() for line in lines if line[0] == '{' and not any (x in line for x in skips)]
    except FileNotFoundError as error:
        return('No export_units.txt found in the specified directory.\n%s' % error)

    unit_type = ''
    unit_id = ''
    unit_attachment = 'unused'
    unit_officers = []
    unit_formation = []
    unit_models = []
    unit_ownership = {'ownership': [], 'era 0': [], 'era 1': [], 'era 2': []}
    unit_info_dir = 'faction'
    unit_card_dir = 'faction'
    attachments = ['mount', 'engine']

    # The EDU `type` is the one thing that is unique per unit - the `dictionary`
    # key is not (two units may share one) and neither is the name it looks up
    # in export_units.txt - so it is kept and used to tell units apart below.
    def unitEntry():
        return {'Type': unit_type, 'ID': unit_id, 'Model': unit_models, 'Officers': unit_officers, 'Formation': unit_formation, 'Attachment': unit_attachment, 'Owners': unit_ownership, 'Info Card': unit_info_dir, 'Unit Card': unit_card_dir}

    temp_database = []
    for line in edu_cleaned:
        identifier = line[0]
        if identifier == 'type':
            # nothing has been read yet before the first type line, so there is
            # no unit to close off - the old code banked an empty one here
            if unit_type:
                temp_database.append(unitEntry())
            unit_type = ' '.join(line[1:])
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
    if unit_type:
        temp_database.append(unitEntry())

    # {dictionary key: display name} from export_units.txt, built once instead
    # of rescanning the file per unit. A key that appears twice keeps the last
    # spelling, which is what the old per-unit scan did - it never broke out of
    # the loop on a match.
    eu_names = {}
    for name in eu_lines:
        key = name.split('}')[0].lstrip('{')
        if not key:
            continue
        unit_name = ' '.join(x.title().strip() for x in name.split('}')[1:])
        eu_names[key] = unicodedata.normalize('NFKD', unit_name).encode('ascii', 'ignore').decode('ascii')

    # Two EDU units can share one export_units.txt name: a dismounted version
    # reusing the mounted unit's text ("Knights of the Blazing Sun" for both
    # `knights_blazing_sun` and `knights_blazing_sun_foot`), or DaC's five
    # catapults all reading "Catapult". Keying the dictionary on that name alone
    # made the later unit overwrite the earlier one, so only the last of them
    # could ever be picked in any dropdown - 19 of DaC's 931 units were
    # unreachable. Every unit sharing a name is labelled with its EDU type,
    # which is unique, and the units export_units.txt has nothing for are listed
    # under their type rather than dropped.
    shared_names = {}
    for unit in temp_database:
        shared_names.setdefault(eu_names.get(unit['ID'], ''), []).append(unit)

    unit_database = {}
    for unit in temp_database:
        display = eu_names.get(unit['ID'], '')
        if not display:
            label = unit['Type'].title()
        elif len(shared_names[display]) > 1:
            label = '%s (%s)' % (display, unit['Type'])
        else:
            label = display
        if not label:
            continue
        # a name two units still agree on (the same type twice, which a valid
        # EDU cannot have) must not lose one of them either
        base, suffix = label, 2
        while label in unit_database:
            label = '%s %d' % (base, suffix)
            suffix += 1
        unit_database[label] = unit

    try:
        m_lines = readModLines(os.path.join(mod_folder, 'descr_mount.txt'), 'utf-8')
        save = ['type', 'model', 'root_node_height', 'rider_offset']
        mount_lines = [re.sub("(;.*)|(,)", " ", line).lower().rstrip().split() for line in m_lines if line[0] != ';' and any (x in line for x in save)]
    except FileNotFoundError as error:
        return('No descr_mount.txt found in the specified directory.\n%s' % error)

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
        e_lines = readModLines(os.path.join(mod_folder, 'descr_engines.txt'), 'utf-8')
        save = ['type', 'engine_mesh', 'engine_dock_dist', 'obstacle_x_radius']
        engine_lines = [re.sub(";.*", " ", line).lower().rstrip().split() for line in e_lines if line[0] != ';' and any (x in line for x in save)]
    except FileNotFoundError as error:
        return('No descr_engines.txt found in the specified directory.\n%s' % error)

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