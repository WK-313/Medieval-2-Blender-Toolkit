import os
import re
from .text_io import readModLines

def lp(s):
    """Length-prefix a string the way battle_models.modeldb expects."""
    s = str(s)
    if not s:
        return "0"
    return "%d %s" % (len(s), s)

def parseRelativeUnitPath(full_path):
    """'D:\\...\\data\\unit_models\\_units\\Aduniam' -> 'unit_models/_units/Aduniam'."""
    normalized = str(full_path).replace("\\", "/").rstrip("/")
    match = re.search(r"/data/(.+)$", normalized, flags=re.IGNORECASE)
    relative = match.group(1) if match else normalized.lstrip("/")
    return relative

def buildEntry(model_name, relative_path, out_main, out_main_norm, sprite, out_attach, out_attach_norm, footer, factions, mesh_name=None):
    """Build one battle_models.modeldb entry, same layout as generate_bmdb.py."""
    relative_path = relative_path.replace("\\", "/").rstrip("/")
    mesh_path = "%s/%s.mesh" % (relative_path, mesh_name or model_name)
    tex = lambda name: "%s/textures/%s.texture" % (relative_path, name)

    out = []
    out.append(lp(model_name))
    out.append("1 1")
    out.append("%s 6400" % lp(mesh_path))

    out.append(str(len(factions)))
    for faction in factions:
        out.append(lp(faction))
        out.append(lp(tex(out_main)))
        out.append(lp(tex(out_main_norm)))
        out.append(lp(sprite))

    out.append(str(len(factions)))
    for faction in factions:
        out.append(lp(faction))
        out.append(lp(tex(out_attach)))
        out.append("%s 0" % lp(tex(out_attach_norm)))

    out.append(footer.replace("\\n", "\n"))
    return "\n".join(out)

# An entry starts with "<len> <name>", then "1 <lod count>", then a .mesh line.
ENTRY_START = re.compile(r"^\d+ (\S+)\s*\n1 \d+\s*\n\d+ \S+\.mesh", re.IGNORECASE | re.MULTILINE)

# Parsed entry names per modeldb file, invalidated when the file's mtime changes,
# so panel redraws don't re-read a multi-megabyte file.
_entry_names_cache = {}

def bmdbEntryNames(mod_folder):
    """All entry names (lowercased) in the mod's battle_models.modeldb, or None
    if the mod has no modeldb file."""
    modeldb_path = os.path.join(mod_folder, 'unit_models', 'battle_models.modeldb')
    try:
        mtime = os.path.getmtime(modeldb_path)
    except OSError:
        return None
    cached = _entry_names_cache.get(modeldb_path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    text = "".join(readModLines(modeldb_path, 'utf-8'))
    names = {match.group(1).lower() for match in ENTRY_START.finditer(text)}
    _entry_names_cache[modeldb_path] = (mtime, names)
    return names

def parseSpriteAndFooter(mod_folder, model_name):
    """Pull the sprite path and footer block of an existing model entry out of
    the mod's battle_models.modeldb. Returns (sprite, footer, error)."""
    modeldb_path = os.path.join(mod_folder, 'unit_models', 'battle_models.modeldb')
    if not os.path.isfile(modeldb_path):
        return None, None, "No battle_models.modeldb found in %s" % mod_folder
    text = "".join(readModLines(modeldb_path, 'utf-8'))

    starts = [(m.start(), m.group(1)) for m in ENTRY_START.finditer(text)]
    entry_text = None
    for index, (offset, name) in enumerate(starts):
        if name.lower() == model_name.lower():
            end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
            entry_text = text[offset:end]
            break
    if entry_text is None:
        return None, None, "Model '%s' not found in battle_models.modeldb" % model_name

    sprite_match = re.search(r"\d+ (\S+\.spr)", entry_text, re.IGNORECASE)
    sprite = sprite_match.group(1) if sprite_match else ""

    # The footer starts right after the attachment texture block. Walk the two
    # faction blocks (main: faction/texture/normal/sprite, attach:
    # faction/texture/normal/empty-sprite) line-wise to find where it begins.
    lines = entry_text.splitlines()
    try:
        cursor = 3  # name, "1 N", first mesh line
        while cursor < len(lines) and ".mesh" in lines[cursor].lower():
            cursor += 1
        main_count = int(lines[cursor].split()[0]); cursor += 1
        cursor += main_count * 4
        attach_count = int(lines[cursor].split()[0]); cursor += 1
        cursor += attach_count * 3
        footer = "\n".join(lines[cursor:]).strip("\n")
    except (ValueError, IndexError):
        return sprite, None, "Could not parse the footer of '%s' (unusual entry layout)" % model_name
    return sprite, footer, None
