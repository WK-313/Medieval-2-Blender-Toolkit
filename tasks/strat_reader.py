"""Read-only campaign model descriptors, independent of Blender.

Block parsing and texture sibling rules follow Unit Transfer's stratmap reader.
Paths retain descriptor spelling; resolution handles Windows-style case on all OSes.
"""
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
import math
import re


@dataclass
class StratLOD:
    kind: str
    path: str
    distance: str = "max"


@dataclass
class StratEntry:
    type: str
    skeleton: str = ""
    scale: float = 1.0
    textures: dict = field(default_factory=dict)
    models: list = field(default_factory=list)
    shadows: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    line: int = 0
    raw: str = ""

    @property
    def name(self):
        return self.type


@dataclass
class StratDocument:
    entries: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    preamble: str = ""
    _by_name: dict = field(default=None, init=False, repr=False, compare=False)

    def by_name(self):
        """Case-insensitive lookup: first definition wins, matching Unit Transfer."""
        if self._by_name is None:
            self._by_name = {}
            for entry in self.entries:
                self._by_name.setdefault(entry.type.casefold(), entry)
        return self._by_name


_MODEL_KEYS = {"model_flexi", "model_flexi_m", "model_flexi_c", "model_flexi_a"}
_CACHE = {}


def parseStratText(text):
    """Parse Latin-1 game text (already decoded), retaining unknown metadata."""
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines)
              if re.match(r"^\s*type(?:\s|$)", line.split(";", 1)[0], re.I)]
    doc = StratDocument(preamble="".join(lines[:starts[0]]) if starts else text)
    seen = set()
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        raw = "".join(lines[start:end])
        name_parts = lines[start].split(";", 1)[0].split(None, 1)
        name = name_parts[1].strip() if len(name_parts) > 1 else ""
        if not name:
            doc.diagnostics.append(f"Line {start + 1}: type has no name; block skipped")
            continue
        entry = StratEntry(name, line=start + 1, raw=raw)
        doc.entries.append(entry)
        if name.casefold() in seen:
            doc.diagnostics.append(f"Line {start + 1}: duplicate type {name}; first definition wins")
        seen.add(name.casefold())
        for offset, line in enumerate(lines[start + 1:end], start + 2):
            parts = line.split(";", 1)[0].split(None, 1)
            if not parts:
                continue
            key = parts[0].lower()
            value = parts[1].strip() if len(parts) > 1 else ""
            entry.metadata.setdefault(key, []).append(value)
            try:
                if key == "skeleton":
                    if not value:
                        raise ValueError("missing skeleton")
                    if not entry.skeleton:
                        entry.skeleton = value
                elif key == "scale":
                    scale = float(value)
                    if not math.isfinite(scale) or scale <= 0:
                        raise ValueError("scale must be finite and positive")
                    entry.scale = scale
                elif key in {"texture", "texture_no_move"}:
                    fields = [p.strip() for p in value.split(",")]
                    if len(fields) != 2 or not all(fields):
                        raise ValueError("expected faction, texture path")
                    faction, path = fields
                    existing = next((f for f in entry.textures if f.casefold() == faction.casefold()), None)
                    if existing is None:
                        entry.textures[faction] = path
                    else:
                        doc.diagnostics.append(f"Line {offset}: duplicate texture faction {faction}; first definition wins")
                elif key in _MODEL_KEYS or key == "shadow_model_flexi":
                    fields = [p.strip() for p in value.split(",")]
                    # Some shipped mods omit the final range. Keep that CAS
                    # available to import without changing its original text.
                    if len(fields) == 1 and fields[0].lower().endswith(".cas"):
                        fields.append("max")
                        doc.diagnostics.append(f"Line {offset}: {name}: {key} has no LOD distance; using max")
                    if len(fields) != 2 or not all(fields):
                        raise ValueError("expected model path, LOD distance")
                    path, distance = fields
                    if distance.lower() != "max":
                        number = float(distance)
                        if not math.isfinite(number) or number < 0:
                            raise ValueError("LOD distance must be finite and nonnegative, or max")
                    target = entry.shadows if key.startswith("shadow_") else entry.models
                    target.append(StratLOD(key, path, distance))
            except ValueError as exc:
                doc.diagnostics.append(f"Line {offset}: {name}: invalid {key}: {exc}")
    return doc


def loadStratModels(data_root):
    """Read a descriptor from a data directory; invalidate cache on file changes.

    OSError is intentionally propagated so the browser can report missing files.
    """
    path = resolveStratPath(data_root, "descr_model_strat.txt")
    if path is None:
        raise FileNotFoundError(f"No descr_model_strat.txt in {data_root}")
    stat = path.stat()
    key = str(path.resolve())
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _CACHE.get(key)
    if cached is None or cached[0] != signature:
        payload = path.read_bytes()
        text = payload.decode("utf-8-sig") if payload.startswith(b"\xef\xbb\xbf") else payload.decode("latin-1")
        _CACHE[key] = (signature, parseStratText(text))
    return _CACHE[key][1]


def selectStratTexture(entry, faction=""):
    """Choose requested faction, then all, then the first declared texture."""
    textures = {key.casefold(): value for key, value in entry.textures.items()}
    return textures.get(faction.casefold(), textures.get("all", next(iter(textures.values()), "")))


def _safe_parts(relative_path):
    value = str(relative_path).strip().replace("\\", "/")
    if not value or PureWindowsPath(value).drive or value.startswith("/"):
        return None
    parts = [p for p in value.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    if parts and parts[0].casefold() == "data":
        parts.pop(0)
    return parts or None


def _resolve_case(root, parts):
    root = Path(root).resolve()
    candidate = root
    try:
        for part in parts:
            exact = candidate / part
            if exact.exists():
                candidate = exact
            else:
                matches = sorted((p for p in candidate.iterdir() if p.name.casefold() == part.casefold()), key=lambda p: p.name)
                if not matches:
                    return None
                candidate = matches[0]
        candidate = candidate.resolve()
        candidate.relative_to(root)  # Also reject symlinks escaping the allowed tree.
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def resolveStratPath(data_root, relative_path, vanilla_data_root=None, texture=False):
    """Resolve only within mod data or an explicitly supplied vanilla data root.

    Mod assets take precedence over vanilla. For textures use .tga.dds, .dds,
    then .tga, matching the game's compressed texture preference over placeholders.
    """
    parts = _safe_parts(relative_path)
    if not parts:
        return None
    variants = [parts]
    if texture:
        name = parts[-1]
        for suffix in (".tga.dds", ".tga", ".dds"):
            if name.lower().endswith(suffix):
                stem = name[:-len(suffix)]
                variants = [parts[:-1] + [stem + ext] for ext in (".tga.dds", ".dds", ".tga")]
                break
    for root in (data_root, vanilla_data_root):
        if root is None or not str(root):
            continue
        for variant in variants:
            result = _resolve_case(root, variant)
            if result is not None:
                # Texture optimisers leave empty .tga placeholders. They must
                # not mask a usable vanilla asset or be handed to Blender.
                try:
                    if not texture or result.stat().st_size:
                        return result
                except OSError:
                    continue
    return None
