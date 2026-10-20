"""Write a battle model (``.mesh``) - Phase 95d.

:mod:`unittransfer.mesh` reads a model as a grammar up to the vertex streams
and then searches its way over the bookkeeping between them, which is enough
to draw one. Writing one is not, so this module reads the WHOLE archive - every
class descriptor, object id and reference - and :func:`write_mesh` writes it
back the same way, counting the ids itself.

The bookkeeping, measured on every model in the installed mods and the game's
packs (``tests/test_meshwrite``):

* **A pointer** is ``u16 class id``, then, the first time that class turns up
  in the file, ``u8 tracking`` and ``u8 version``, then ``u32 object id``.
  New objects take the next id in the order they are written, so a writer
  that writes the same things in the same order gets the same ids without
  being told them. **A reference** to an object already written is ``u16
  class id`` and ``u32`` that object's id.
* **An object held by value** writes ``u8 tracking, u8 version`` (``00 00``)
  the first time its class turns up, and nothing after. These are the runs of
  zero words the reader in ``mesh.py`` steps over.
* **The class ids are the game's own**, the same number for the same record in
  every file: 4 the model, 7 its part list, 11 a group and 10 the small object
  each group points to that points back at it, 6 the vertex pool, 3 the LOD
  table. The LOD record is 39 on a unit and 38 on a building
  (:attr:`MeshLayout.lod_class`), and the one that points back at it the
  class below.
* **The vertex streams are kept in three lists by what one vertex holds**:
  eight bytes (18, the UVs and the weights), twelve (23, the positions, and a
  static model's float normals) and four (28, the bone indices and a skinned
  model's packed normals, tangents and binormals). Each stream points to a
  small object that points back at it (17, 22, 27). The order of the streams
  inside a list is the file's own and is kept; it is not sorted.

What follows the bone table is the LOD record: its name (``characterlod0``),
then seventeen texture slots (empty on a unit, which takes its textures from
the modeldb; filled on a siege engine or a building) and the material
settings. None of it is bookkeeping, so it is kept as the bytes it is
(:attr:`MeshLayout.lod_body`), and a model with no layout to keep gets the one
every unit in the game carries, :data:`CHARACTER_LOD_BODY`.

The bone table's second number is not the bone's position, which is what
``mesh.py`` assumed when it dropped it: a unit's ``bone_weapon01`` and
``bone_weapon`` both say 20, ``bone_shield01`` and ``bone_shield`` both 22.
It is kept on :attr:`unittransfer.mesh.MeshFile.bone_links` and written back.
"""
from __future__ import annotations

import hashlib
import math
import struct
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import mesh as _mesh
from .mesh import BOOST_SIGNATURE, MeshError, MeshFile, MeshGroup
from . import i18n as _i18n

#: ``(tracking, version)`` each class writes the first time it turns up.
#: Read back off every model installed; a file that says otherwise is not one
#: this module writes exactly, and :func:`read_layout` says so.
CLASS_INFO: Dict[int, Tuple[int, int]] = {
    3: (1, 0), 4: (1, 3), 6: (1, 0), 7: (1, 0), 10: (1, 0), 11: (1, 3),
    17: (1, 0), 18: (1, 0), 22: (1, 0), 23: (1, 0), 27: (1, 0), 28: (1, 0),
}
#: the LOD record's header, and the header of the record pointing back at it
LOD_INFO, BACK_INFO = (1, 4), (1, 0)
#: The three stream lists, by bytes a vertex: (stream class, back-pointer class).
FAMILIES: Tuple[Tuple[int, int], ...] = ((18, 17), (23, 22), (28, 27))
#: Which list a stream type goes in, by the bytes one vertex takes.
FAMILY_BY_STRIDE = {8: 0, 12: 1, 4: 2}
#: The LOD record's class on a unit; a building's is 38. The record that
#: points back at it is always the class one below.
CHARACTER_LOD = 39

#: A unit's LOD record after its name: seventeen empty texture slots, then the
#: material settings. Byte for byte the same in every unit and mount installed.
CHARACTER_LOD_BODY = b"\x11\x00\x00\x00" + bytes(68) + bytes.fromhex(
    "04000000010000000300000012c03f0004000000ffffffffffffffffffffffff"
    "ffffffff09000000000000400000000000000000000000000000000000000000"
    "000000000000000000000000080000000200000000000000803f000000000000"
    "000000000000000000000000803f0000000000000000020000000000803f0000"
    "00000000000000000000000000000000803f0000000000000000020000000000"
    "803f000000000000000000000000000000000000803f00000000000000000200"
    "00000000803f000000000000000000000000000000000000803f000000000000"
    "0000020000000000803f000000000000000000000000000000000000803f0000"
    "000000000000020000000000803f000000000000000000000000000000000000"
    "803f0000000000000000020000000000803f0000000000000000000000000000"
    "00000000803f0000000000000000020000000000803f00000000000000000000"
    "0000000000000000803f0000000000000000")

#: Bytes a vertex of each stream type, for the types that have one length.
FIXED_STRIDE = {0: 12, 1: 8, 2: 4, 4: 8, 8: 4, 9: 4, 13: 4, 14: 4}


@dataclass
class MeshLayout:
    """Everything in a ``.mesh`` that is not geometry, as the file had it."""

    #: the archive's root object is tracked (it takes object id 0) in a
    #: skinned model and not in a static one
    root_tracked: bool = True
    #: the three stream lists: ``(stream type, stride, the u32 after its data)``
    families: List[List[Tuple[int, int, int]]] = field(default_factory=lambda: [
        [(4, 8, 0), (1, 8, 0)], [(0, 12, 0)], [(2, 4, 0), (3, 4, 0), (10, 4, 0), (11, 4, 0)]])
    #: the ten bytes between the last stream and the bounding sphere
    pool_tail: bytes = b"\x00" * 10
    #: the bounding sphere as written (centre, radius), and the hash of the
    #: positions it was written for: a model whose positions changed gets a
    #: new one
    sphere: bytes = b""
    sphere_of: str = ""
    #: a hash of each decoded array as read, so a stream is written from its
    #: own bytes until the array behind it changes
    read_as: Dict[str, str] = field(default_factory=dict)
    after_sphere: int = 0
    #: the file closes on a sphere too: the same one on a unit, a wider one
    #: on a siege engine
    end_sphere: bytes = b""
    lod_class: int = CHARACTER_LOD
    lod_name: str = "characterlod0"
    lod_body: bytes = CHARACTER_LOD_BODY

    def stream_types(self) -> List[int]:
        return [t for fam in self.families for t, _s, _w in fam]


def _hash(values) -> str:
    raw = values if isinstance(values, (bytes, bytearray)) else values.tobytes()
    return hashlib.blake2b(raw, digest_size=12).hexdigest()


def _hashes(m: MeshFile) -> Dict[str, str]:
    return {"positions": _hash(m.positions), "normals": _hash(m.normals),
            "uvs": _hash(m.uvs), "weights": _hash(m.weights),
            "bone_ids": _hash(m.bone_ids)}


#: the decoded array each stream type is written from, and the arrays a
#: stream is worked out of when it has to be made again
STREAM_SOURCE = {0: ("positions",), 1: ("weights",), 2: ("bone_ids",),
                 3: ("normals",), 4: ("uvs",),
                 10: ("positions", "normals", "uvs"),
                 11: ("positions", "normals", "uvs")}


# ---------------------------------------------------------------------------
# the strict reader


class _In:
    """A cursor that checks every bookkeeping byte against the counter."""

    def __init__(self, data: bytes, source: str):
        self.d = data
        self.p = 0
        self.source = source
        self.seen: set = set()
        self.next_oid = 0

    def fail(self, what: str):
        raise MeshError(_i18n.msg("eng.meshwrite.at_offset", "{name}: {what} at offset {p}", name=Path(self.source).name, what=what, p=self.p))

    def take(self, fmt: str):
        n = struct.calcsize(fmt)
        if self.p + n > len(self.d):
            self.fail(_i18n.msg("eng.meshwrite.ends_early", "ends early"))
        v = struct.unpack_from(fmt, self.d, self.p)
        self.p += n
        return v if len(v) > 1 else v[0]

    def blob(self, n: int) -> bytes:
        if n < 0 or self.p + n > len(self.d):
            self.fail(_i18n.msg("eng.meshwrite.ends_early", "ends early"))
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def text(self) -> str:
        return self.blob(self.take("<I")).decode("latin-1")

    def inline(self) -> None:
        if self.take("<H") != 0:
            self.fail(_i18n.msg("eng.meshwrite.expected_an_inline_class_header", "expected an inline class header"))

    def new(self, cid: int, info: Optional[Tuple[int, int]] = None) -> int:
        got = self.take("<H")
        if got != cid:
            self.fail(_i18n.msg("eng.meshwrite.expected_class_found", "expected class {cid}, found {got}", cid=cid, got=got))
        if cid not in self.seen:
            self.seen.add(cid)
            if self.take("<BB") != (info or CLASS_INFO.get(cid)):
                self.fail(_i18n.msg("eng.meshwrite.class_has_a_header_this_writer", "class {cid} has a header this writer does not know", cid=cid))
        oid = self.take("<I")
        if oid != self.next_oid:
            self.fail(_i18n.msg("eng.meshwrite.object_id_expected", "object id {oid}, expected {next_oid}", oid=oid, next_oid=self.next_oid))
        self.next_oid += 1
        return oid

    def ref(self, cid: int, oid: int) -> None:
        got = self.take("<H")
        if got != cid or self.take("<I") != oid:
            self.fail(_i18n.msg("eng.meshwrite.expected_a_reference_to_object", "expected a reference to object {oid}", oid=oid))


def read_layout(data: bytes, source: str = "") -> Tuple[MeshLayout, dict]:
    """``(layout, parts)`` out of a whole ``.mesh``, every byte accounted for.

    ``parts`` holds the geometry as read: ``groups`` (``(type, mesh name,
    index bytes, flag, byte)``), ``streams`` (raw per type), ``verts``,
    ``bones`` and ``links``. Raises :class:`MeshError` on a file whose
    bookkeeping is not the grammar above - which no file installed is.
    """
    a = _In(data, source)
    lay = MeshLayout()
    if a.text().encode("latin-1") != BOOST_SIGNATURE:
        a.fail(_i18n.msg("eng.meshwrite.not_a_boost_archive", "not a boost archive"))
    if a.blob(5) != b"\x03\x04\x04\x04\x08" or a.take("<I") != 1:
        a.fail(_i18n.msg("eng.meshwrite.an_archive_header_this_writer_does", "an archive header this writer does not know"))
    track, version = a.take("<BB")
    if (track, version) == (1, 0):
        lay.root_tracked = True
        if a.take("<I") != 0:
            a.fail(_i18n.msg("eng.meshwrite.the_root_object_is_not_object", "the root object is not object 0"))
        a.next_oid = 1
    elif (track, version) == (0, 0):
        lay.root_tracked = False
    else:
        a.fail(_i18n.msg("eng.meshwrite.a_root_header_this_writer_does", "a root header this writer does not know"))
    a.inline()
    if a.take("<I") != 1:
        a.fail(_i18n.msg("eng.meshwrite.more_than_one_model_in_the", "more than one model in the file"))
    a.inline()
    model = a.new(4)
    a.inline()
    parts_list = a.new(7)
    a.inline()
    groups = []
    for i in range(a.take("<I")):
        if i == 0:
            a.inline()
        gid = a.new(11)
        name, tex = a.text(), a.text()
        if i == 0:
            a.inline()
        idx = a.blob(a.take("<I") * 6)
        flag = a.take("<I")
        byte = a.take("<B")
        if i == 0:
            a.inline()
            a.inline()
        a.new(10)
        a.ref(11, gid)
        groups.append((name, tex, idx, flag, byte))

    a.new(6)
    a.ref(7, parts_list)
    verts = a.take("<I")
    lay.families = []
    streams: Dict[int, bytes] = {}
    for scls, bcls in FAMILIES:
        a.inline()
        fam = []
        for j in range(a.take("<I")):
            if j == 0:
                a.inline()
            sid = a.new(scls)
            stype = a.take("<I")
            if j == 0:
                a.inline()
            if a.take("<I") != verts:
                a.fail(_i18n.msg("eng.meshwrite.stream_is_not_one_value_a", "stream {stype} is not one value a vertex", stype=stype))
            stride = {0: 8, 1: 12, 2: 4}[len(lay.families)]
            streams[stype] = a.blob(verts * stride)
            word = a.take("<I")
            a.new(bcls)
            a.ref(scls, sid)
            fam.append((stype, stride, word))
        lay.families.append(fam)
    lay.pool_tail = a.blob(10)
    lay.sphere = a.blob(16)
    lay.after_sphere = a.take("<I")
    bones, links = [], []
    n = a.take("<I")
    if n:
        a.inline()
    for _ in range(n):
        bones.append(a.text())
        links.append(a.take("<I"))

    trailer_start = a.p
    a.new(3)
    a.ref(4, model)
    a.inline()
    if a.take("<I") != 1:
        a.fail(_i18n.msg("eng.meshwrite.more_than_one_lod_record", "more than one LOD record"))
    a.inline()
    lod_cls = a.take("<H")
    a.p -= 2
    lay.lod_class = lod_cls
    lod = a.new(lod_cls, LOD_INFO)
    lay.lod_name = a.text()
    # the record's own bytes run to the pointer that closes the file
    back = lod_cls - 1
    end = len(data) - 16 - 6 - 8
    if end < a.p:
        a.fail(_i18n.msg("eng.meshwrite.no_closing_record", "no closing record"))
    lay.lod_body = a.blob(end - a.p)
    a.new(back, BACK_INFO)
    a.ref(lod_cls, lod)
    lay.end_sphere = a.blob(16)
    groups_out = groups
    parts = {"groups": groups_out, "streams": streams, "verts": verts,
             "bones": bones, "links": links, "trailer_start": trailer_start}
    return lay, parts


def attach_layout(m: MeshFile, data: bytes, parsed=None) -> bool:
    """Give a model read by ``mesh.read_mesh`` what writing it back needs.

    Fills :attr:`MeshFile.layout`, each group's :attr:`MeshGroup.byte`, the
    bone links and the streams the viewer does not decode. False, with the
    reason on ``m.notes``, for a file this writer could not account for.
    """
    try:
        lay, parts = parsed if parsed is not None else read_layout(data, m.source)
    except MeshError as e:
        m.notes.append(_i18n.msg("eng.meshwrite.not_writable_exactly", "not writable exactly: {e}", e=e))
        return False
    if len(parts["groups"]) != len(m.groups) or parts["verts"] != m.vertices:
        m.notes.append(_i18n.msg("eng.meshwrite.not_writable_exactly_the_two_readers", "not writable exactly: the two readers disagree"))
        return False
    for g, (_n, _t, _i, _f, byte) in zip(m.groups, parts["groups"]):
        g.byte = byte
    if m.bones != parts["bones"]:
        # the viewer's reader comes away from a few siege engines with no
        # bones; this one has read every byte, so its table is the file's
        m.bones = list(parts["bones"])
    m.bone_links = list(parts["links"])
    m.extra_streams = dict(parts["streams"])
    lay.sphere_of = _hash(m.positions)
    lay.read_as = _hashes(m)
    m.layout = lay
    return True


# ---------------------------------------------------------------------------
# the writer


class _Out:
    """Writes the bookkeeping the way :class:`_In` checks it."""

    def __init__(self):
        self.parts: List[bytes] = []
        self.seen: set = set()
        self.next_oid = 0

    def put(self, fmt: str, *v) -> None:
        self.parts.append(struct.pack(fmt, *v))

    def raw(self, b: bytes) -> None:
        self.parts.append(b)

    def text(self, s: str) -> None:
        b = s.encode("latin-1", "replace")
        self.put("<I", len(b))
        self.raw(b)

    def inline(self) -> None:
        self.put("<H", 0)

    def new(self, cid: int, info: Optional[Tuple[int, int]] = None) -> int:
        self.put("<H", cid)
        if cid not in self.seen:
            self.seen.add(cid)
            self.put("<BB", *(info or CLASS_INFO[cid]))
        oid = self.next_oid
        self.next_oid += 1
        self.put("<I", oid)
        return oid

    def ref(self, cid: int, oid: int) -> None:
        self.put("<HI", cid, oid)


def _pack_vectors(vec: Sequence[float], verts: int) -> bytes:
    """Three floats a vertex into the packed form ``mesh._unpack_normals`` reads:
    unsigned bytes biased around 127.5, z in the first byte, x in the third."""
    out = bytearray(verts * 4)
    for v in range(verts):
        for c in range(3):
            b = round((vec[v * 3 + c] + 1.0) * 0.5 * 255.0)
            out[v * 4 + 2 - c] = 0 if b < 0 else 255 if b > 255 else b
    return bytes(out)


def _tangents(m: MeshFile) -> Tuple[array, array]:
    """Per-vertex tangent and binormal from the positions, UVs and normals.

    For a stream the model has no bytes for, a vertex count that changed for
    instance: the game lights a normal map along these, so a written model
    needs real ones, not zeros.
    """
    n = m.vertices
    tan = [0.0] * (n * 3)
    bit = [0.0] * (n * 3)
    p, uv = m.positions, m.uvs
    for g in m.groups:
        ix = g.indices
        for t in range(0, len(ix) - 2, 3):
            a, b, c = ix[t], ix[t + 1], ix[t + 2]
            e1 = [p[b * 3 + k] - p[a * 3 + k] for k in range(3)]
            e2 = [p[c * 3 + k] - p[a * 3 + k] for k in range(3)]
            if uv:
                du1, dv1 = uv[b * 2] - uv[a * 2], uv[b * 2 + 1] - uv[a * 2 + 1]
                du2, dv2 = uv[c * 2] - uv[a * 2], uv[c * 2 + 1] - uv[a * 2 + 1]
            else:
                du1, dv1, du2, dv2 = 1.0, 0.0, 0.0, 1.0
            det = du1 * dv2 - du2 * dv1
            if abs(det) < 1e-12:
                continue
            r = 1.0 / det
            for k in range(3):
                tk = (e1[k] * dv2 - e2[k] * dv1) * r
                bk = (e2[k] * du1 - e1[k] * du2) * r
                for v in (a, b, c):
                    tan[v * 3 + k] += tk
                    bit[v * 3 + k] += bk
    # Measured on the reference horses: the file's tangent is the NEGATED
    # direction u grows in (94% within 45 degrees, the rest seams), and its
    # binormal is tangent x normal (98%), not the direction v grows in.
    nrm = m.normals
    for v in range(n):
        x, y, z = tan[v * 3:v * 3 + 3]
        nx, ny, nz = nrm[v * 3:v * 3 + 3] if len(nrm) == n * 3 else (0.0, 1.0, 0.0)
        d = x * nx + y * ny + z * nz
        x, y, z = x - nx * d, y - ny * d, z - nz * d
        ln = math.sqrt(x * x + y * y + z * z)
        if ln < 1e-12:
            x, y, z, ln = 1.0, 0.0, 0.0, 1.0
        x, y, z = -x / ln, -y / ln, -z / ln
        tan[v * 3:v * 3 + 3] = [x, y, z]
        bit[v * 3:v * 3 + 3] = [y * nz - z * ny, z * nx - x * nz, x * ny - y * nx]
    return array("f", tan), array("f", bit)


def _sphere(m: MeshFile) -> bytes:
    """A tight sphere round every vertex, the kind the game writes.

    The game's own is not centred on the box (a horse's sits 0.35 above it)
    and its radius reaches exactly the farthest vertex. Ritter's two passes
    give a sphere within a few percent of the smallest, then each vertex
    still outside grows it just enough.
    """
    p, n = m.positions, m.vertices
    pt = lambda i: (p[i * 3], p[i * 3 + 1], p[i * 3 + 2])
    d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2
    a = pt(0)
    b = max((pt(i) for i in range(n)), key=lambda q: d2(q, a))
    c = max((pt(i) for i in range(n)), key=lambda q: d2(q, b))
    centre = [(b[k] + c[k]) / 2 for k in range(3)]
    r = math.sqrt(d2(b, c)) / 2
    for i in range(n):
        q = pt(i)
        dist = math.sqrt(d2(q, centre))
        if dist > r:
            r2 = (r + dist) / 2
            for k in range(3):
                centre[k] += (q[k] - centre[k]) * (r2 - r) / dist
            r = r2
    r *= 1.0000005       # float rounding must not leave a vertex outside
    return struct.pack("<4f", centre[0], centre[1], centre[2], r)


def _stream(m: MeshFile, stype: int, stride: int, cache: dict) -> bytes:
    """One stream's bytes: as read while nothing it depends on has changed,
    else from the decoded arrays."""
    n = m.vertices
    raw = m.extra_streams.get(stype, b"")
    if len(raw) == n * stride and all(
            cache["now"][k] == cache["was"].get(k)
            for k in STREAM_SOURCE.get(stype, ())):
        return raw
    if stype == 0:
        return m.positions.tobytes()
    if stype == 4:
        uv = array("f", m.uvs) if m.uvs else array("f", bytes(n * 8))
        for i in range(0, len(uv), 2):
            uv[i] *= 0.5               # the file halves u: see mesh.py
        return uv.tobytes()
    if stype == 1:
        if len(m.weights) == n * 2:
            return m.weights.tobytes()
        return array("f", [1.0, 0.0] * n).tobytes()
    if stype == 2:
        return m.bone_ids if len(m.bone_ids) == n * 4 else bytes(n * 4)
    if stype == 3:
        nrm = m.normals if len(m.normals) == n * 3 else array("f", [0.0, 1.0, 0.0] * n)
        return nrm.tobytes() if stride == 12 else _pack_vectors(nrm, n)
    if stype in (10, 11):
        if "tb" not in cache:
            cache["tb"] = _tangents(m)
        vec = cache["tb"][0 if stype == 10 else 1]
        return vec.tobytes() if stride == 12 else _pack_vectors(vec, n)
    return (b"\xff\xff\xff\xff" if stride == 4 else bytes(stride)) * n


def write_mesh(m: MeshFile, path=None) -> bytes:
    """``m`` as the bytes of a ``.mesh``; written to ``path`` as well if given.

    A model read with its layout (``mesh.read_mesh(path, layout=True)``) and
    not changed writes back to the bytes it was read from. One that was
    changed, or built from nothing, writes the streams of a unit model, a
    fresh bounding sphere, and tangents worked out from its UVs where it has
    none of its own.
    """
    if not m.positions:
        raise MeshError(_i18n.msg("eng.meshwrite.a_model_with_no_vertices_cannot", "a model with no vertices cannot be written"))
    n = m.vertices
    if n > 0xFFFF + 1:
        raise MeshError(_i18n.msg("eng.meshwrite.n_vertices_a_mesh_indexes_at", "{n:,} vertices: a .mesh indexes at most 65,536", n=n))
    if len(m.positions) != n * 3:
        raise MeshError("position stream must contain three values per vertex")
    for name, stride in (("normals", 3), ("uvs", 2), ("weights", 2), ("bone_ids", 4)):
        values = getattr(m, name)
        if values and len(values) != n * stride:
            raise MeshError(f"{name} stream must contain {stride} values per vertex")
    if m.bone_links and len(m.bone_links) != len(m.bones):
        raise MeshError("bone links must contain one entry per bone")
    for g in m.groups:
        if len(g.indices) % 3:
            raise MeshError(f"group {g.name}/{g.texture_group} has incomplete triangles")
        if g.indices and max(g.indices) >= n:
            raise MeshError(_i18n.msg("eng.meshwrite.group_indexes_past_the_vertex_pool", "group {name}/{texture_group} indexes past the vertex pool", name=g.name, texture_group=g.texture_group))
    lay = m.layout or MeshLayout()
    o = _Out()
    o.text(BOOST_SIGNATURE.decode("latin-1"))
    o.raw(b"\x03\x04\x04\x04\x08")
    o.put("<I", 1)
    if lay.root_tracked:
        o.put("<BBI", 1, 0, 0)
        o.next_oid = 1
    else:
        o.put("<BB", 0, 0)
    o.inline()
    o.put("<I", 1)
    o.inline()
    model = o.new(4)
    o.inline()
    parts_list = o.new(7)
    o.inline()
    o.put("<I", len(m.groups))
    for i, g in enumerate(m.groups):
        if i == 0:
            o.inline()
        gid = o.new(11)
        o.text(g.name)
        o.text(g.texture_group)
        if i == 0:
            o.inline()
        o.put("<I", len(g.indices) // 3)
        o.raw(array("H", g.indices).tobytes())
        o.put("<I", g.flag)
        o.put("<B", getattr(g, "byte", 0))
        if i == 0:
            o.inline()
            o.inline()
        o.new(10)
        o.ref(11, gid)

    o.new(6)
    o.ref(7, parts_list)
    o.put("<I", n)
    cache = {"was": lay.read_as if m.layout else {}, "now": _hashes(m)}
    for (scls, bcls), fam in zip(FAMILIES, lay.families):
        o.inline()
        o.put("<I", len(fam))
        for j, (stype, stride, word) in enumerate(fam):
            if j == 0:
                o.inline()
            sid = o.new(scls)
            o.put("<I", stype)
            if j == 0:
                o.inline()
            o.put("<I", n)
            o.raw(_stream(m, stype, stride, cache))
            o.put("<I", word)
            o.new(bcls)
            o.ref(scls, sid)
    o.raw(lay.pool_tail)
    kept = bool(lay.sphere) and lay.sphere_of == _hash(m.positions)
    sphere = lay.sphere if kept else _sphere(m)
    o.raw(sphere)
    o.put("<I", lay.after_sphere)
    o.put("<I", len(m.bones))
    if m.bones:
        o.inline()
    links = list(getattr(m, "bone_links", []) or [])
    for i, b in enumerate(m.bones):
        o.text(b)
        o.put("<I", links[i] if i < len(links) else i)

    o.new(3)
    o.ref(4, model)
    o.inline()
    o.put("<I", 1)
    o.inline()
    lod = o.new(lay.lod_class, LOD_INFO)
    o.text(lay.lod_name)
    o.raw(lay.lod_body)
    o.new(lay.lod_class - 1, BACK_INFO)
    o.ref(lay.lod_class, lod)
    o.raw(lay.end_sphere if kept else sphere)
    out = b"".join(o.parts)
    if path is not None:
        Path(path).write_bytes(out)
    return out
