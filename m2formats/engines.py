"""Parsers for the siege-engine files: ``descr_engines.txt``,
``descr_mounted_engines.txt`` and ``descr_engine_skeleton.txt``.

A siege unit's EDU ``engine`` (or ``mounted_engine``) field names an engine
defined in ``descr_engines.txt``::

    type                Dol_Guldur_Tower
    culture             all
    class               holy_cart
    pathfinding_data    none
    reference_points    siege_engines/great_bell_tower_standard_milan.modelReferencePoints

    engine_model_group  normal
    engine_skeleton     Great_bell_tower_standard
    engine_bone_map     siege_engines/BoneMaps/Great_Bell_Tower_standard.xml
    engine_collision    siege_engines/collision_models/belltower_collide.CAS
    engine_mesh         siege_engines/Dol_Guldur_Tower_lod0.mesh, 40.0
    ...

So an engine transfer needs FOUR things in the destination:
  1. the ``descr_engines.txt`` block(s),
  2. every file named on a ``reference_points`` / ``pathfinding_data`` /
     ``engine_bone_map`` / ``engine_collision`` / ``engine_mesh`` line,
  3. the **textures** those meshes use - which are *baked into the .mesh binary*,
     not named in any text file (see :func:`mesh_textures`),
  4. each model group's ``engine_skeleton`` entry from
     ``descr_engine_skeleton.txt``, plus the ``.CAS``/``.evt`` animation files it
     names (engine animations live loose under ``animations/engine/``, not in a
     unit anim pack).

Blocks start at a line whose first token is ``type`` and run until the next one.
Verbatim block text is kept so a transfer can append it unchanged. Note a single
engine ``type`` may appear in SEVERAL blocks (one per ``culture`` / ``variant``,
e.g. the per-culture siege towers) - lookups therefore return a list.
``;`` starts a comment.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple



ENCODING = "latin-1"

#: Engine keys whose value names a file, relative to the mod's ``data/`` folder.
#: ``engine_mesh`` is ``"<path>, <distance>"``; the rest are a bare path.
FILE_KEYS = ("reference_points", "pathfinding_data", "engine_bone_map",
             "engine_collision", "engine_mesh")
#: values that mean "no file here"
NO_FILE = {"", "none", "no"}


def _strip_comment(s: str) -> str:
    return s.split(";", 1)[0].rstrip()


def _line_kv(line: str) -> Tuple[str, str]:
    """(key, value) for one line; ('', '') for blanks/comments."""
    body = _strip_comment(line).strip()
    if not body:
        return "", ""
    parts = body.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def data_rel(path: str) -> str:
    """Normalise a path as written in an engine file to a ``data/``-relative one.

    Engine files write mesh/bonemap paths already relative to ``data/``
    (``siege_engines/x.mesh``) but animation paths WITH the prefix
    (``data/animations/engine/x.CAS``). Backslashes are normalised too.
    """
    p = str(path).replace("\\", "/").strip().strip('"').lstrip("/")
    if p.lower().startswith("data/"):
        p = p[5:]
    return p


def _file_value(key: str, value: str) -> str:
    """The file path a ``key value`` line names, or '' if it names none."""
    if key not in FILE_KEYS:
        return ""
    val = value.split(",", 1)[0].strip() if key == "engine_mesh" else value.strip()
    if val.lower() in NO_FILE:
        return ""
    return data_rel(val)


# --------------------------------------------------------------------------
@dataclass
class ModelGroup:
    """One ``engine_model_group`` (normal / dying / dead) of an engine."""
    name: str = ""
    skeleton: str = ""
    bone_map: str = ""
    collision: str = ""
    meshes: List[str] = field(default_factory=list)   # data-relative, LOD order


@dataclass
class Engine:
    type: str = ""
    culture: str = ""
    variant: str = ""
    engine_class: str = ""
    reference_points: str = ""
    pathfinding_data: str = ""
    groups: List[ModelGroup] = field(default_factory=list)
    attack_stats: List[List[str]] = field(default_factory=list)  # CSV values per line
    raw: str = ""                                    # verbatim block text

    # ---- what this engine depends on -----------------------------------
    def skeletons(self) -> List[str]:
        """``engine_skeleton`` names across the model groups (deduped, in order)."""
        out: List[str] = []
        seen = set()
        for g in self.groups:
            if g.skeleton and g.skeleton.lower() not in seen:
                seen.add(g.skeleton.lower())
                out.append(g.skeleton)
        return out

    def mounted_skeletons(self) -> List[str]:
        """Skeleton names for a block out of ``descr_mounted_engines.txt``.

        A mounted engine (elephant cannon, camel gun, …) has NO
        ``engine_model_group``: its model comes from the unit's mount, so the
        block only carries ``reference_points``. Its ``class`` line is what names
        the ``descr_engine_skeleton.txt`` entry - the mounted equivalent of a
        ground engine's ``engine_skeleton`` (usually ``serpentine``,
        ``rocket_launcher`` or ``ballista``).

        Only call this for mounted blocks: in ``descr_engines.txt`` ``class``
        names a hardcoded engine class (``ram``, ``tower``, …), not a skeleton.
        """
        out = self.skeletons()          # normally empty; honour it if a mod adds groups
        if self.engine_class and not any(
                self.engine_class.lower() == s.lower() for s in out):
            out.insert(0, self.engine_class)
        return out

    def file_refs(self) -> List[str]:
        """Every data-relative file the block names, deduped, in file order."""
        out: List[str] = []
        seen = set()
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            rel = _file_value(k, v)
            if rel and rel.lower() not in seen:
                seen.add(rel.lower())
                out.append(rel)
        return out

    def mesh_refs(self) -> List[str]:
        """Just the ``engine_mesh`` paths (the ones carrying baked textures)."""
        return [r for r in self.file_refs() if r.lower().endswith(".mesh")]

    def projectiles(self) -> List[str]:
        """Projectile names fired by this engine (3rd CSV slot of ``attack_stat``)."""
        out: List[str] = []
        seen = set()
        for vals in self.attack_stats:
            if len(vals) > 2:
                p = vals[2].strip()
                if p and p.lower() not in NO_FILE and p.lower() not in seen:
                    seen.add(p.lower())
                    out.append(p)
        return out

    # ---- dedup ----------------------------------------------------------
    def content_key(self):
        """Everything defining the engine EXCEPT its name (for dedup compare)."""
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "type":
                out.append((k.lower(), v.lower()))
        return tuple(out)

    def content_equals(self, other: "Engine") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class EngineFile:
    preamble: str = ""
    engines: List[Engine] = field(default_factory=list)

    def by_type(self) -> Dict[str, List[Engine]]:
        """Lowercased engine type -> every block declaring it (culture/variant)."""
        out: Dict[str, List[Engine]] = {}
        for e in self.engines:
            out.setdefault(e.type.lower(), []).append(e)
        return out

    def get_all(self, name: str) -> List[Engine]:
        """Every block for an engine type ([] when absent). Case-insensitive."""
        if not name:
            return []
        return self.by_type().get(name.lower(), [])

    def get(self, name: str) -> Optional[Engine]:
        blocks = self.get_all(name)
        return blocks[0] if blocks else None

    def to_text(self) -> str:
        return self.preamble + "".join(e.raw for e in self.engines)


def _parse_engine_block(raw: str) -> Engine:
    e = Engine(raw=raw)
    group: Optional[ModelGroup] = None
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if not k:
            continue
        if k == "type" and not e.type:
            e.type = v
        elif k == "culture" and not e.culture:
            e.culture = v
        elif k == "class" and not e.engine_class:
            e.engine_class = v
        elif k == "variant" and not e.variant:
            e.variant = v
        elif k == "reference_points" and not e.reference_points:
            e.reference_points = _file_value(k, v)
        elif k == "pathfinding_data" and not e.pathfinding_data:
            e.pathfinding_data = _file_value(k, v)
        elif k == "engine_model_group":
            group = ModelGroup(name=v)
            e.groups.append(group)
        elif k == "attack_stat":
            e.attack_stats.append([x.strip() for x in v.split(",")])
        elif group is not None:
            if k == "engine_skeleton" and not group.skeleton:
                group.skeleton = v
            elif k == "engine_bone_map" and not group.bone_map:
                group.bone_map = _file_value(k, v)
            elif k == "engine_collision" and not group.collision:
                group.collision = _file_value(k, v)
            elif k == "engine_mesh":
                rel = _file_value(k, v)
                if rel:
                    group.meshes.append(rel)
    return e


def _block_starts(lines: List[str]) -> List[int]:
    """Indices of lines that open a block (first token ``type``, not a comment)."""
    starts: List[int] = []
    for i, line in enumerate(lines):
        s = line.lstrip()
        if s.startswith(";"):
            continue
        if s.startswith("type") and (len(s) == 4 or s[4].isspace()):
            starts.append(i)
    return starts


def parse_text(text: str) -> EngineFile:
    lines = text.splitlines(keepends=True)
    starts = _block_starts(lines)
    if not starts:
        return EngineFile(preamble=text, engines=[])
    out = EngineFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.engines.append(_parse_engine_block("".join(lines[start:end])))
    return out


def parse_file(path: str | Path) -> EngineFile:
    p = Path(path)
    if not p.exists():
        return EngineFile()
    # Read WITHOUT letting the platform decide what a line ending is: `to_text`
    # is a pure splice of these raws, so whatever comes in goes back out. With
    # universal newlines a file mixing CRLF and lone LF (Third Age Reforged
    # ships one) came back longer than it went in, which is the one thing these
    # modules promise not to do.
    return parse_text(p.read_bytes().decode(ENCODING))


# --------------------------------------------------------------------------
@dataclass
class EngineSkeleton:
    """One ``type`` block of ``descr_engine_skeleton.txt``.

    Each ``anim`` line is ``anim <key> <path.CAS> [-if:N] [-fr:N] [-evt:<path>]``.
    """
    type: str = ""
    anims: List[Tuple[str, str]] = field(default_factory=list)   # (key, cas path)
    raw: str = ""

    def anim_files(self) -> List[str]:
        """Every ``.CAS`` and ``-evt:`` file the block names (data-relative)."""
        out: List[str] = []
        seen = set()
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k != "anim" or not v:
                continue
            for tok in v.split():
                rel = ""
                if tok.lower().startswith("-evt:"):
                    rel = data_rel(tok[5:].rstrip(","))
                elif "/" in tok or "\\" in tok:
                    rel = data_rel(tok.rstrip(","))
                if rel and rel.lower() not in seen:
                    seen.add(rel.lower())
                    out.append(rel)
        return out

    def content_key(self):
        out = []
        for line in self.raw.splitlines():
            k, v = _line_kv(line)
            if k and k != "type":
                # collapse the wild whitespace these files use so two identical
                # entries formatted differently still compare equal
                out.append((k.lower(), " ".join(v.lower().split())))
        return tuple(out)

    def content_equals(self, other: "EngineSkeleton") -> bool:
        return self.content_key() == other.content_key()


@dataclass
class EngineSkeletonFile:
    preamble: str = ""
    skeletons: List[EngineSkeleton] = field(default_factory=list)

    def by_type(self) -> Dict[str, EngineSkeleton]:
        return {s.type.lower(): s for s in self.skeletons}

    def get(self, name: str) -> Optional[EngineSkeleton]:
        if not name:
            return None
        return self.by_type().get(name.lower())

    def to_text(self) -> str:
        return self.preamble + "".join(s.raw for s in self.skeletons)


def _parse_skeleton_block(raw: str) -> EngineSkeleton:
    s = EngineSkeleton(raw=raw)
    for line in raw.splitlines():
        k, v = _line_kv(line)
        if k == "type" and not s.type:
            s.type = v
        elif k == "anim" and v:
            parts = v.split(None, 1)
            key = parts[0]
            path = ""
            if len(parts) > 1:
                for tok in parts[1].split():
                    if "/" in tok or "\\" in tok:
                        path = data_rel(tok.rstrip(","))
                        break
            s.anims.append((key, path))
    return s


def parse_skeleton_text(text: str) -> EngineSkeletonFile:
    lines = text.splitlines(keepends=True)
    starts = _block_starts(lines)
    if not starts:
        return EngineSkeletonFile(preamble=text, skeletons=[])
    out = EngineSkeletonFile(preamble="".join(lines[:starts[0]]))
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.skeletons.append(_parse_skeleton_block("".join(lines[start:end])))
    return out


def parse_skeleton_file(path: str | Path) -> EngineSkeletonFile:
    p = Path(path)
    if not p.exists():
        return EngineSkeletonFile()
    # Read WITHOUT letting the platform decide what a line ending is: `to_text`
    # is a pure splice of these raws, so whatever comes in goes back out. With
    # universal newlines a file mixing CRLF and lone LF (Third Age Reforged
    # ships one) came back longer than it went in, which is the one thing these
    # modules promise not to do.
    return parse_skeleton_text(p.read_bytes().decode(ENCODING))


# --------------------------------------------------------------------------
TEXTURE_EXTS = (".texture", ".dds", ".tga")
_MAX_STR = 260


def mesh_textures(path: str | Path) -> List[str]:
    """Data-relative texture paths baked into a siege-engine ``.mesh`` file.

    Returns [] for a missing/unreadable file. Deduped, in file order.
    """
    p = Path(path)
    try:
        blob = p.read_bytes()
    except OSError:
        return []
    return textures_in_blob(blob)


def textures_in_blob(blob: bytes) -> List[str]:
    """The texture paths inside a mesh byte-string (see :func:`mesh_textures`)."""
    out: List[str] = []
    seen = set()
    i, end = 0, len(blob) - 4
    while i < end:
        n = struct.unpack_from("<I", blob, i)[0]
        if 5 <= n <= _MAX_STR and i + 4 + n <= len(blob):
            chunk = blob[i + 4:i + 4 + n]
            if all(32 <= c < 127 for c in chunk):
                s = chunk.decode("latin-1")
                if s.lower().endswith(TEXTURE_EXTS) and ("/" in s or "\\" in s):
                    rel = data_rel(s)
                    if rel.lower() not in seen:
                        seen.add(rel.lower())
                        out.append(rel)
                i += 4 + n
                continue
        i += 1
    return out
