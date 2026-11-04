import re
from . import modeldb

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

def bmdbEntryNames(mod_folder):
    """All entry names (lowercased) in the mod's battle_models.modeldb, or None
    if the mod has no readable modeldb file.

    Read with the token parser, not by matching lines: a mod's entries can have
    trailing spaces, a scale other than 1 or LODs on one line, and a line match
    missed 176 of Third Age Reforged's 1225 entries."""
    db, _error = modeldb.loadModelDb(mod_folder)
    if db is None:
        return None
    return {entry.name for entry in db.entries}

def parseSpriteAndFooter(mod_folder, model_name):
    """Pull the sprite path and footer block of an existing model entry out of
    the mod's battle_models.modeldb. Returns (sprite, footer, error)."""
    db, error = modeldb.loadModelDb(mod_folder)
    if db is None:
        return None, None, error
    entry = db.get(model_name)
    if entry is None:
        return None, None, "Model '%s' not found in battle_models.modeldb" % model_name
    sprite = next((t.sprite for t in entry.main_textures if t.sprite and t.sprite != "0"), "")
    return sprite, entry.footer(), None
