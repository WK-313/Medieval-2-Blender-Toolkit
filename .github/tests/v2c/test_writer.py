"""Independent binary fixtures for CAS serialization; no game installation needed.
Run: python tests/v2c/test_writer.py
"""
import struct
import unittest
from array import array
import os
from pathlib import Path
import sys

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    candidate for parent in Path(__file__).resolve().parents
    for candidate in (parent / 'Medieval-2-Toolkit-main', parent)
    if (candidate / 'm2formats/cas.py').is_file())
sys.path.insert(0, str(SOURCE))
from m2formats import cas


def text(value):
    raw = value.encode('latin1') + b'\0'
    return struct.pack('<I', len(raw)) + raw


def chunk(kind, payload):
    return struct.pack('<II', len(payload) + 8, kind) + payload


def fixture(*, unknown=False, baked=False, partial=False, version=3.2):
    """Pack documented fields directly, independently of the production writer."""
    head = bytearray(50)
    struct.pack_into('<fIII fII', head, 0, version, 38, 9, 0, 2.0, 1, 0)
    head[28:50] = bytes(range(22))
    data = bytes(head) + struct.pack('<IHII', 2, 0x4321, 0, 1) + struct.pack('<f', 0)
    for i, name in enumerate(('Scene Root', 'bone_pelvis')):
        data += text(name) + struct.pack('<5I', int(baked and i == 1), 0, 0, 0, 0) + text('node_prop' if i else '')
    if baked:
        data += struct.pack('<4f', 0, 0, 0, 1)
    data += struct.pack('<6f', 0, 0, 0, 0.5, 1.5, -0.5)
    header = bytearray(data)
    struct.pack_into('<II', header, 42, len(data) - 42, 0)
    data = bytes(header)
    for kind in (1, 2):
        body = struct.pack('<I', 1) + text('static' if kind == 1 else 'skin') + text('Mass = 4')
        body += bytes([0x61 + kind]) * (37 if kind == 1 else 28)
        body += struct.pack('<HHBB', 3, 1, 1, 1)
        if kind == 2:
            body += struct.pack('<3I', 1, 0, 1)
        body += struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
        body += struct.pack('<9f', 0, 0, 1, 0, 0, 1, 0, 0, 1)
        body += struct.pack('<3H', 0, 1, 2) + struct.pack('<I', 0)
        body += struct.pack('<6f', 0, 0, 1, 0, 0, 1)
        body += struct.pack('<3I', 0xff001122, 0xff334455, 0xff667788) + b'TAIL'
        body += b'UVWXYZ' if kind == 1 and version >= 3.17 else (b'UVW' if kind == 1 else b'ABCD')
        if partial and kind == 1:
            body = struct.pack('<I', 2) + body[4:]  # second advertised object is absent
        data += chunk(kind, body)
    mat = struct.pack('<II', 1, 1) + b'\0textures\\atlas.tga\0'
    mat += struct.pack('<7f', 1, 0.5, 0.25, 1, 0.125, 0.25, 0.5) + bytes(range(90, 119))
    data += chunk(5, mat)
    for kind in (3, 8, 10):
        data += chunk(kind, b'\0' * 8)
    if unknown:
        data += chunk(123, b'opaque-chunk-payload')
    return data


class CasWriterTests(unittest.TestCase):
    def test_edit_float32_version_302(self):
        scene = self.decode(fixture(version=3.02))
        scene.objects[0].positions[0] = 7.0
        self.assertEqual(self.roundtrip(scene).objects[0].positions[0], 7.0)

    def test_material_order_across_chunks(self):
        material = struct.pack('<II', 1, 1) + b'\0second.tga\0'
        material += struct.pack('<7f', 1, 1, 1, 1, 0, 0, 0) + b'\0' * 28 + b'\1'
        raw = fixture() + chunk(5, material)
        scene = self.decode(raw)
        self.assertEqual(cas.write_cas(scene), raw)
        scene.materials.reverse()
        scene.objects[0].material = 0
        after = self.roundtrip(scene)
        self.assertEqual([m.texture for m in after.materials], ['second.tga', 'textures\\atlas.tga'])
        self.assertEqual(after.materials[after.objects[0].material].texture, 'second.tga')

    def decode(self, raw=None):
        return cas.read_cas_bytes(fixture() if raw is None else raw, 'fixture.cas')

    def roundtrip(self, scene):
        return cas.read_cas_bytes(cas.write_cas(scene), 'roundtrip.cas')

    def test_independent_fixture_exact(self):
        for kwargs in ({}, {'baked': True}, {'version': 3.02}, {'unknown': True}):
            with self.subTest(kwargs=kwargs):
                raw = fixture(**kwargs)
                scene = self.decode(raw)
                self.assertEqual((scene.vertices, scene.triangles), (6, 2))
                self.assertEqual(cas.write_cas(scene), raw)

    def test_fresh_static_and_skinned_scene(self):
        scene = cas.CasScene(source='fresh.cas', version=3.2, nodes=['Scene Root', 'bone_pelvis'], parents=[-1, 0], pivots=array('f', [0, 0, 0, 0, 2, 0]), key_times=array('f', [0]))
        scene.materials = [cas.CasMaterial(texture='new.tga')]
        for skin in (False, True):
            scene.objects.append(cas.CasObject(name=str(skin), skinned=skin, material=0, positions=array('f', [0, 0, 0, 1, 0, 0, 0, 1, 0]), normals=array('f', [0, 0, 1] * 3), uvs=array('f', [0, 0, 1, 0, 0, 1]), indices=array('H', [0, 1, 2]), bones=array('I', [1, 1, 1] if skin else [])))
        out = self.roundtrip(scene)
        self.assertEqual(out.nodes, scene.nodes)
        self.assertEqual(out.parents, scene.parents)
        self.assertEqual(out.pivots, scene.pivots)
        for actual, expected in zip(out.objects, scene.objects):
            for field in ('positions', 'normals', 'uvs', 'bones', 'indices', 'skinned', 'material'):
                self.assertEqual(getattr(actual, field), getattr(expected, field))
        self.assertFalse(out.notes)

    def test_edits_reserialize_all_known_fields(self):
        scene = self.decode()
        scene.length = 4.5
        scene.nodes[1] = 'bone_new'
        scene.pivots[4] = 9.5
        obj = scene.objects[1]
        obj.name = 'renamed-longer'
        obj.properties = 'replacement properties'
        obj.positions[0] = -4.25
        obj.normals[1] = 0.25
        obj.uvs[0] = 0.375
        obj.indices[:] = array('H', [2, 1, 0])
        obj.bones[0] = 0
        obj.colours[1] = 0x12345678
        obj.material = None
        mat = scene.materials[0]
        mat.texture = 'textures\\replacement.tga'
        mat.diffuse, mat.specular = (0.25, 0.5, 0.75, 1), (0.5, 0.25, 0.125)
        raw = cas.write_cas(scene)
        self.assertNotEqual(raw, fixture())
        out = self.decode(raw)
        for field in ('length', 'nodes', 'pivots'):
            self.assertEqual(getattr(out, field), getattr(scene, field))
        self.assertEqual(out.objects[1], obj)
        self.assertEqual(out.materials[0], mat)
        for opaque in (b'TAIL', b'UVWXYZ', b'ABCD', b'b' * 37, b'c' * 28, bytes(range(90,119)), b'node_prop'):
            self.assertIn(opaque, raw)
        self.assertEqual(raw[20:42], fixture()[20:42])
        self.assertEqual(raw[46:50], fixture()[46:50])

    def test_skeleton_chunk_size_after_header_edits(self):
        raw = fixture()
        scene = self.decode(raw)
        scene.nodes[1] += '_longer'
        scene.key_times.extend([1, 2])
        output = cas.write_cas(scene)
        self.assertEqual(struct.unpack_from('<I', output, 42)[0],
                         struct.unpack_from('<I', raw, 42)[0] + len('_longer') + 8)

    def test_fresh_chunk_order_and_closing_counts(self):
        scene = self.decode()
        for item in [scene, *scene.objects, *scene.materials]:
            if hasattr(item, '_wire'):
                del item._wire
        output = cas.write_cas(scene)
        after = self.decode(output)
        self.assertEqual([kind for kind, _, _ in after._wire['chunks']], [1, 2, 3, 8, 10, 5])
        self.assertEqual(struct.unpack_from('<I', output, 42)[0], after._wire['skeleton_size'])
        for kind, chunk_raw, tail in after._wire['chunks']:
            if kind in (1, 2):
                self.assertEqual(struct.unpack_from('<I', tail, 2 if kind == 1 else 0)[0], 1)
        import copy
        extra = copy.deepcopy(after.objects[1])
        extra.name = 'another skin'
        after.objects.append(extra)
        resized = self.roundtrip(after)
        skin_tail = next(tail for kind, _, tail in resized._wire['chunks'] if kind == 2)
        self.assertEqual(struct.unpack('<I', skin_tail)[0], 2)

    def test_external_material_name_rejected(self):
        scene = self.decode()
        scene.materials[0].name = 'not-a-binary-material-field'
        with self.assertRaises(cas.CasError):
            cas.write_cas(scene)

    def test_geometry_resize_recomputes_counts(self):
        scene = self.decode()
        obj = scene.objects[0]
        obj.positions.extend([1, 1, 0]); obj.normals.extend([0, 0, 1])
        obj.uvs.extend([1, 1]); obj.colours.append(0xffffffff)
        obj.indices.extend([1, 3, 2])
        out = self.roundtrip(scene)
        self.assertEqual((out.objects[0].vertices, out.objects[0].triangles), (4, 2))
        self.assertEqual(out.objects[0].indices, obj.indices)

    def test_add_delete_and_reorder(self):
        import copy
        scene = self.decode()
        second = copy.deepcopy(scene.objects[0])
        second.name = 'another static'
        scene.objects.insert(0, second)
        scene.materials.append(cas.CasMaterial(texture='second.tga'))
        second.material = 1
        out = self.roundtrip(scene)
        self.assertEqual([o.name for o in out.objects], ['another static', 'static', 'skin'])
        self.assertEqual(out.objects[0].material, 1)
        self.assertEqual(len(out.materials), 2)
        scene.objects.pop(1)
        out = self.roundtrip(scene)
        self.assertEqual([o.name for o in out.objects], ['another static', 'skin'])

    def test_noncanonical_strings_and_trailing_bytes(self):
        raw = fixture().replace(text('static'), struct.pack('<I', 9) + b'static\0\0\0', 1)
        # Account for the deliberately expanded string in its chunk length.
        start = raw.index(struct.pack('<I', 1) + struct.pack('<I', 9) + b'static') - 8
        data = bytearray(raw)
        struct.pack_into('<I', data, start, struct.unpack_from('<I', data, start)[0] + 2)
        raw = bytes(data) + b'END'
        scene = self.decode(raw)
        self.assertEqual(cas.write_cas(scene), raw)

    def test_partial_scene_unchanged_only(self):
        raw = fixture(partial=True)
        scene = self.decode(raw)
        self.assertTrue(scene.notes)
        self.assertEqual(cas.write_cas(scene), raw)
        scene.objects[0].positions[0] += 1
        with self.assertRaises(cas.CasError):
            cas.write_cas(scene)

    def test_unknown_chunk_survives_known_edit(self):
        scene = self.decode(fixture(unknown=True, baked=True))
        scene.objects[0].positions[0] = 12.5
        raw = cas.write_cas(scene)
        self.assertIn(chunk(123, b'opaque-chunk-payload'), raw)
        self.assertEqual(self.decode(raw).objects[0].positions[0], 12.5)
        self.assertEqual(self.decode(raw).baked_keys, 16)

    def test_float_bits_survive_unedited(self):
        data = bytearray(fixture())
        colour_at = data.index(b'\0textures\\atlas.tga\0') + len(b'\0textures\\atlas.tga\0')
        struct.pack_into('<I', data, colour_at, 0x7f800123)  # signaling NaN payload
        struct.pack_into('<I', data, colour_at + 4, 0x80000000)  # negative zero
        raw = bytes(data)
        self.assertEqual(cas.write_cas(self.decode(raw)), raw)

    def test_invalid_scene_rejected(self):
        mutations = {
            'normal count': lambda s: s.objects[0].normals.pop(),
            'UV count': lambda s: s.objects[0].uvs.pop(),
            'bone count': lambda s: s.objects[1].bones.pop(),
            'bone index': lambda s: s.objects[1].bones.__setitem__(0, 100),
            'vertex index': lambda s: s.objects[0].indices.__setitem__(0, 100),
            'material index': lambda s: setattr(s.objects[0], 'material', 100),
            'pivot count': lambda s: s.pivots.pop(),
            'parent cycle': lambda s: s.parents.__setitem__(1, 1),
            'nonfinite vertex': lambda s: s.objects[0].positions.__setitem__(0, float('nan')),
            'nonfinite pivot': lambda s: s.pivots.__setitem__(0, float('inf')),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                scene = self.decode(); mutate(scene)
                with self.assertRaises(cas.CasError):
                    cas.write_cas(scene)

    def test_corrupt_source_rejected(self):
        for raw in (b'', fixture()[:50], fixture()[:-20], b'not a model'):
            with self.subTest(length=len(raw)), self.assertRaises(cas.CasError):
                cas.write_cas(self.decode(raw))


if __name__ == '__main__':
    unittest.main(verbosity=2)
