# Medieval 2 mod text files are often saved as Windows-1252/ANSI rather than
# UTF-8/UTF-16, depending on what tool a modder used. Rather than failing outright,
# fall back through the encodings that are actually likely, ending on latin-1
# which can decode any byte sequence and therefore never raises.
FALLBACK_CHAINS = {
    'utf-8': ['utf-8', 'utf-8-sig', 'cp1252', 'latin-1'],
    'utf-16': ['utf-16', 'utf-16-le', 'utf-16-be', 'cp1252', 'latin-1'],
}

def dataPath(data_folder, *parts):
    """<data_folder>/<parts> found the way the game finds it: the loose file,
    then the folder's own packs (a Kingdoms campaign such as mods/crusades
    keeps everything there; the base game's own data/ is read out of the
    game's packs/data_*.pack), then the base game's loose data/ and packs.
    Packed files are read out into a temp cache. A .txt that exists only as
    its compiled <name>.txt.strings.bin - all the base game and DLC text -
    comes back as that, which readModLines decodes. When nothing has it, the
    loose path comes back unchanged, so opening it raises FileNotFoundError
    exactly as before."""
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from ..m2formats import gamepack
    loose = os.path.join(data_folder, *parts)
    data = Path(os.path.normpath(data_folder))
    mod = SimpleNamespace(root=data.parent, data=data)
    relative = '/'.join(parts)
    candidates = [relative] + ([relative + '.strings.bin'] if relative.lower().endswith('.txt') else [])
    for candidate in candidates:
        if os.path.isfile(os.path.join(data_folder, candidate)):
            return os.path.join(data_folder, candidate)
        try:
            found, _ = gamepack.lookup(candidate, mod)
        except (OSError, gamepack.PackError, ValueError):
            found = None
        if found:
            return str(found)
    return loose

def stringsBinLines(raw):
    """A tagged .strings.bin as the {tag}value lines of its .txt. Read side of
    Unit Transfer's unittransfer/stringsbin.py: u16 style (2 = tagged), u16
    flavour, u32 count, then count x (tag, value), each a u16 length in
    UTF-16 code units and that many little-endian units. A real newline in a
    value is written \\n, as in the .txt."""
    import struct
    style, _flavour, count = struct.unpack_from('<HHI', raw, 0)
    if style != 2:
        raise ValueError('not a tagged .strings.bin')
    position, lines = 8, []
    def string():
        nonlocal position
        (units,) = struct.unpack_from('<H', raw, position)
        start, position = position + 2, position + 2 + units * 2
        return raw[start:position].decode('utf-16-le', 'replace')
    for _ in range(count):
        tag = string()
        value = string().replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')
        lines.append('{%s}%s\n' % (tag, value))
    return lines

def readModLines(path, primary_encoding='utf-8'):
    encodings_to_try = FALLBACK_CHAINS.get(primary_encoding, [primary_encoding, 'cp1252', 'latin-1'])
    with open(path, 'rb') as f:
        raw = f.read()
    if str(path).lower().endswith('.strings.bin'):
        return stringsBinLines(raw)
    for encoding in encodings_to_try:
        try:
            return raw.decode(encoding).splitlines(keepends=True)
        except UnicodeError:
            continue
    return raw.decode('latin-1', errors='replace').splitlines(keepends=True)
