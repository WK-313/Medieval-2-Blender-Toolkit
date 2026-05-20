import re
import json
import unicodedata
from pathlib import Path
parent_folder = Path(__file__).parent.parent

def reader(lines, identifiers):
    cleaned_lines = [re.sub(",|;.*", " ", line).lower().strip().split() for line in lines if not line.strip().startswith(';') and len(line.split()) > 1]
    for line in cleaned_lines:
        if line[0] not in identifiers:
            continue
        attachment_cleaned.append(line)


    with open((parent_folder/'text/attachments_dictionary.json'), 'w') as attachments_output:
        json.dump(attachment_cleaned, attachments_output, indent=2)
    return('Finished')

def attachmentReader(mod_folder, attachment_type):
    attachment_dictionary = []
    if attachment_type == 'mount':
        identifiers = ['type', 'engine_length', 'engine_width']
        with open((mod_folder+'descr_engines.txt'), 'r', encoding="utf8") as descr_engines:
            lines = descr_engines.readlines()
    else:
        identifiers = ['type', 'rider_offset']
        with open((mod_folder+'descr_mount.txt'), 'r', encoding="utf8") as descr_mount:
            lines = descr_mount.readlines()
    reader(lines, identifiers)
    return('Finished')