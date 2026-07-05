import os
import re
import json
from pathlib import Path
from .text_io import readModLines

def bmdbReader(mod_folder):
    # read bmdb into list and clear unnecessary info.
    try:
        lines = readModLines(os.path.join(mod_folder, 'unit_models', 'battle_models.modeldb'), 'utf-8')
        bmdb_text = ' '.join(''.join(lines).splitlines())
        bmdb_text = bmdb_text.lower().strip()
    except FileNotFoundError as error:
        return('No battle_models.modeldb found in the specified directory.\n%s' % error)

    holder_list = []
    for line in bmdb_text.splitlines():
        segmented = line.split()
        cleared = []
        for seg in segmented:
            if seg == 'serialization::archive' or seg == 'blank':
                continue
            try:
                float(seg)
            except ValueError:
                cleared.append(seg)
        holder_list.append(' '.join(cleared))
    bmdb_text = holder_list[0]
    bmdb_text = bmdb_text.replace("unit_models/", "\nunit_models/").replace(".mesh ", ".mesh\n").replace(".texture", ".texture\n")

    bmdb_cleaned = []
    for line in bmdb_text.splitlines():
        line = line.strip()
        if len(line) > 0:
            bmdb_cleaned.append(line)

    model_id = 'Empty'
    model_path = ''
    model_mesh = ''
    model_textures = {}
    model_data = {'Mesh': '', 'Folder': model_path, 'Textures': model_textures}
    model_database = {}
    flag = 0
    for entry in bmdb_cleaned:
        if  flag == 0 and '.mesh' in entry:
            model_data = {'Mesh': model_mesh, 'Folder': model_path, 'Textures': model_textures}
            if model_id in model_database:
                model_database[model_id+"___duplicate"] = model_data
            else:
                model_database[model_id] = model_data
            model_textures = {}
            model_id = previous_line
            model_path = '/'.join(entry.split("/")[:-1])
            model_mesh = entry.split("/")[-1].replace(".mesh", ".glb")
            flag = 1
        elif '.texture' in entry:
            faction_id = previous_line
            model_textures.setdefault(faction_id, [])
            model_textures[faction_id].append(re.sub(".*/|\.texture.*", "", entry)+".dds")
            flag = 0
        # If none of the above keywords, store the model or faction ID
        else:
            previous_line = entry.split(' ')[-1]
    model_data = {'Mesh': model_mesh, 'Folder': model_path, 'Textures': model_textures}
    if model_id in model_database:
        model_database[model_id+"___duplicate"] = model_data
    else:
        model_database[model_id] = model_data
    del model_database['Empty']


    parent_folder = Path(__file__).parent.parent
    with open((os.path.join(parent_folder, 'text', 'model_dictionary.json')), 'w') as models_output:
        json.dump(model_database, models_output, indent=2)
    return('Finished')