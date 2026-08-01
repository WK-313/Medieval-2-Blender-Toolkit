"""Parser/writer for battle_models.modeldb.

Ported from the Unit Transfer tool's `unittransfer/modeldb.py`, which was
verified byte-exact against Third_Age_Reforged (1026 models) and
Divide_and_Conquer_EUR (2192 models). The naming here stays snake_case like the
original so the two stay diffable; everything the addon calls into
(`bmdb_install`, the panels) keeps the toolkit's camelCase.

The file is a length-prefixed token stream ("serialization archive"):
  * a string is stored as ``<byte-length> <that many chars>``
  * numbers are bare whitespace-delimited tokens

Header:  ``<len> serialization::archive 3 0 0 0 0 <COUNT> 0 0``
where ``<COUNT>`` = number-of-real-models + 1 (the extra one is the leading
``blank`` entry). Appending an entry without bumping that count makes the game
ignore it, which is the whole reason the addon parses the file instead of
pasting text onto the end.

For every entry we keep the *raw source substring* that produced it, so writing
appends or replaces one entry verbatim and only bumps the header count -
untouched entries are never re-serialized.
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re

# modeldb is single-byte text (paths are ASCII). latin-1 round-trips every byte
# 1:1, which keeps raw spans exact.
ENCODING = "latin-1"
ARCHIVE_MAGIC = "serialization::archive"

_NAME_PREFIX_RE = re.compile(r"(\d+)\s+")


@dataclass
class Animation:
    mount_type: str            # horse | none | elephant | camel
    primary_skeleton: str
    secondary_skeleton: str
    pri_weapons: list = field(default_factory=list)
    sec_weapons: list = field(default_factory=list)

    def skeletons(self):
        return [s for s in (self.primary_skeleton, self.secondary_skeleton) if s]


@dataclass
class Texture:
    faction: str
    texture: str
    normal: str
    sprite: str


@dataclass
class ModelEntry:
    name: str
    scale: float
    lods: list                           # (mesh, distance) pairs
    main_textures: list
    attach_textures: list
    animations: list
    torch_index: int
    torch: list                          # 6 floats
    raw: str = ""                        # verbatim source text for this entry
    first_entry_pad: bool = False        # see _read_entry's ``pad`` argument
    footer_offset: int = 0               # index into raw where the animation block starts

    def skeletons(self):
        out = []
        for a in self.animations:
            out.extend(a.skeletons())
        return out

    def mesh_files(self):
        return [mesh for mesh, _ in self.lods if mesh]

    def texture_files(self):
        files = []
        for t in list(self.main_textures) + list(self.attach_textures):
            for p in (t.texture, t.normal, t.sprite):
                if p and p != "0":
                    files.append(p)
        # de-dup, keep order
        seen, out = set(), []
        for f in files:
            if f not in seen:
                seen.add(f)
                out.append(f)
        return out

    def factions(self):
        return sorted({t.faction for t in self.main_textures} |
                      {t.faction for t in self.attach_textures})

    def footer(self):
        """The animation/torch block at the tail of the entry, verbatim.

        This is what the toolkit's entry builder takes as its `footer` field, so
        loading an existing entry into the export panel and writing it back out
        keeps the mounts, skeletons and weapons exactly as they were."""
        return self.raw[self.footer_offset:].strip("\n")

    def content_key(self):
        """Everything that defines the entry EXCEPT its name, for dedup compare.

        Includes LOD mesh filenames and all texture paths, so "identical" means
        truly identical including file names."""
        return (
            round(self.scale, 4),
            tuple(self.lods),
            tuple((t.faction, t.texture, t.normal, t.sprite) for t in self.main_textures),
            tuple((t.faction, t.texture, t.normal, t.sprite) for t in self.attach_textures),
            tuple((a.mount_type, a.primary_skeleton, a.secondary_skeleton,
                   tuple(a.pri_weapons), tuple(a.sec_weapons)) for a in self.animations),
            self.torch_index,
            tuple(round(x, 4) for x in self.torch),
        )

    def content_equals(self, other):
        return self.content_key() == other.content_key()


class _Reader:
    """Length-prefixed token reader mirroring the game's FileStream."""

    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def _skip_ws(self):
        while self.i < self.n and self.s[self.i].isspace():
            self.i += 1

    def token(self):
        self._skip_ws()
        start = self.i
        while self.i < self.n and not self.s[self.i].isspace():
            self.i += 1
        return self.s[start:self.i]

    def get_int(self):
        return int(self.token())

    def get_float(self):
        return float(self.token())

    def get_string(self):
        length = int(self.token())
        if length <= 0:
            return ""
        self._skip_ws()
        val = self.s[self.i:self.i + length]
        self.i += length
        return val


@dataclass
class ModelDb:
    header_ints: list                    # the 8 ints after the archive magic
    blank_raw: str                       # verbatim "blank" entry (leading padding entry)
    entries: list
    trailing: str = ""                   # bytes after the last entry (usually "\n")
    header_raw: str = ""                 # verbatim original header (incl trailing whitespace)

    def by_name(self):
        return {e.name: e for e in self.entries}

    def get(self, name):
        return self.by_name().get((name or "").lower())

    def index_of(self, name):
        name = (name or "").lower()
        for i, e in enumerate(self.entries):
            if e.name == name:
                return i
        return -1

    def all_skeletons(self):
        out = set()
        for e in self.entries:
            out.update(e.skeletons())
        out.discard("")
        return out

    def to_text(self):
        # +1 for the blank sentinel entry, but only if the source file had one --
        # some mods lack the vanilla "blank" padding entry and count every entry
        # as real.
        count = len(self.entries) + (1 if self.blank_raw else 0)
        if self.header_raw and count == self.header_ints[5]:
            # No entries added/removed: emit the original header byte-for-byte.
            header = self.header_raw
        else:
            ints = list(self.header_ints)
            ints[5] = count            # entry-count slot
            header = ("%d %s " % (len(ARCHIVE_MAGIC), ARCHIVE_MAGIC)
                      + " ".join(str(x) for x in ints) + "\n")
        body = self.blank_raw + "".join(e.raw for e in self.entries) + self.trailing
        return header + body

    def write(self, path):
        Path(path).write_text(self.to_text(), encoding=ENCODING)


def _read_entry(r, pad=False):
    """Read one entry. ``pad`` reproduces a vanilla quirk: when a modeldb has no
    leading ``blank`` sentinel entry, the game pads the very first real entry
    with 8 extra reserved int-pairs threaded through the body. Every other
    entry, and every entry in a file that does have a ``blank`` sentinel, is
    unpadded."""
    start = r.i

    def firstpad():
        if pad:
            r.get_int()
            r.get_int()

    name = r.get_string().lower()
    scale = r.get_float()
    firstpad()
    lod_count = r.get_int()
    firstpad()
    lods = [(r.get_string(), r.get_int()) for _ in range(lod_count)]
    firstpad()

    def read_textures(pad_after_count):
        cnt = r.get_int()
        if pad_after_count:
            firstpad()
        out = []
        for _ in range(cnt):
            fac = r.get_string().lower()
            tex, nrm, spr = r.get_string(), r.get_string(), r.get_string()
            out.append(Texture(fac, tex, nrm, spr))
        return out

    main_tex = read_textures(pad_after_count=True)
    attach_tex = read_textures(pad_after_count=False)   # no padding around this count
    firstpad()

    # everything from here on is what the entry builder calls the "footer"
    r._skip_ws()
    footer_start = r.i

    mount_n = r.get_int()
    firstpad()
    anims = []
    for _ in range(mount_n):
        mt = r.get_string().lower()
        pri = r.get_string()
        sec = r.get_string()
        priw = [r.get_string() for _ in range(r.get_int())]
        secw = [r.get_string() for _ in range(r.get_int())]
        anims.append(Animation(mt, pri, sec, priw, secw))
    firstpad()

    torch_idx = r.get_int()
    torch = [r.get_float() for _ in range(6)]
    firstpad()
    return ModelEntry(name, scale, lods, main_tex, attach_tex, anims,
                      torch_idx, torch, first_entry_pad=pad,
                      footer_offset=footer_start - start)


def parse_text(text):
    r = _Reader(text)
    magic = r.get_string()
    if magic != ARCHIVE_MAGIC:
        raise ValueError("not a modeldb archive (magic=%r)" % magic)
    header_ints = [r.get_int() for _ in range(8)]
    count = header_ints[5]

    # The body starts at the first token AFTER the header ints. Locating it by
    # the first newline instead would assume the header is exactly one line -
    # true for most mods, but some wrap it, and reading from mid-header makes
    # the next int look like a string length and swallows the first entry.
    r._skip_ws()
    body_start = r.i
    prev_end = body_start

    blank_raw = ""
    entries = []
    for n in range(count):
        pad = False
        if n == 0:
            name = r.get_string().lower()
            if name == "blank":
                for _ in range(39):
                    r.get_int()
                blank_raw = text[prev_end:r.i]
                prev_end = r.i
                continue
            # No blank entry: rewind and treat as a normal first entry, which
            # vanilla pads with extra reserved ints (see _read_entry).
            r.i = prev_end
            pad = True
        # _read_entry always starts at prev_end, so its footer_offset is already
        # relative to the raw slice taken here
        entry = _read_entry(r, pad=pad)
        entry.raw = text[prev_end:r.i]
        entries.append(entry)
        prev_end = r.i

    trailing = text[prev_end:]
    header_raw = text[:body_start]
    return ModelDb(header_ints, blank_raw, entries, trailing, header_raw)


def parse_file(path):
    return parse_text(Path(path).read_text(encoding=ENCODING))


def parse_entry_text(text):
    """Parse a single standalone entry, the shape `buildEntry` produces.

    Raises ValueError when the text is not a well-formed entry, which is how the
    installer refuses to write a broken entry into a mod's modeldb."""
    r = _Reader(text)
    try:
        entry = _read_entry(r)
    except (ValueError, IndexError) as error:
        raise ValueError("could not parse the generated entry: %s" % error)
    leftover = text[r.i:].strip()
    if leftover:
        raise ValueError("trailing junk after the generated entry: %r" % leftover[:40])
    entry.raw = text
    return entry


def rename_entry_raw(raw, new_name):
    """A copy of an entry's raw text with its (length-prefixed) name replaced.

    The name is the first length-prefixed string in the entry body; everything
    after it is preserved verbatim."""
    lead_len = len(raw) - len(raw.lstrip())
    lead, rest = raw[:lead_len], raw[lead_len:]
    match = _NAME_PREFIX_RE.match(rest)
    if not match:
        return raw
    n = int(match.group(1))
    after = rest[match.end() + n:]
    return "%s%d %s%s" % (lead, len(new_name), new_name, after)


def uniqueName(base, taken):
    """`base`, or base_2 / base_3 ... until it is free. Same scheme the Unit
    Transfer tool uses for bmdb name collisions."""
    if base not in taken:
        return base
    index = 2
    while "%s_%d" % (base, index) in taken:
        index += 1
    return "%s_%d" % (base, index)


# Parsed modeldb per file, invalidated when the file's mtime changes. Parsing a
# 21 MB modeldb takes about a second, so an operator that runs twice (check then
# install) must not pay for it twice.
_db_cache = {}

def loadModelDb(mod_folder):
    """Parse the mod's battle_models.modeldb, cached until the file changes.
    Returns (db, error); db is None when the file is missing or unreadable."""
    path = modeldbPath(mod_folder)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None, "No battle_models.modeldb found in %s" % os.path.join(mod_folder, 'unit_models')
    cached = _db_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1], ""
    try:
        db = parse_file(path)
    except (OSError, ValueError) as error:
        return None, "Could not read battle_models.modeldb: %s" % error
    _db_cache[path] = (mtime, db)
    return db, ""


def modeldbPath(mod_folder):
    return os.path.join(mod_folder, 'unit_models', 'battle_models.modeldb')


def invalidate(mod_folder):
    """Drop the cached parse after the file has been written."""
    _db_cache.pop(modeldbPath(mod_folder), None)
