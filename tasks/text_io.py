# Medieval 2 mod text files are often saved as Windows-1252/ANSI rather than
# UTF-8/UTF-16, depending on what tool a modder used. Rather than failing outright,
# fall back through the encodings that are actually likely, ending on latin-1
# which can decode any byte sequence and therefore never raises.
FALLBACK_CHAINS = {
    'utf-8': ['utf-8', 'utf-8-sig', 'cp1252', 'latin-1'],
    'utf-16': ['utf-16', 'utf-16-le', 'utf-16-be', 'cp1252', 'latin-1'],
}

def readModLines(path, primary_encoding='utf-8'):
    encodings_to_try = FALLBACK_CHAINS.get(primary_encoding, [primary_encoding, 'cp1252', 'latin-1'])
    with open(path, 'rb') as f:
        raw = f.read()
    for encoding in encodings_to_try:
        try:
            return raw.decode(encoding).splitlines(keepends=True)
        except UnicodeError:
            continue
    return raw.decode('latin-1', errors='replace').splitlines(keepends=True)
