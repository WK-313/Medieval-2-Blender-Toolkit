"""Compare original/native CAS skeleton and every triangle corner, tolerating float32."""
import argparse
import importlib
from pathlib import Path
import sys
import types

parser = argparse.ArgumentParser()
parser.add_argument('original', type=Path)
parser.add_argument('exported', type=Path)
parser.add_argument('--addon', type=Path, default=Path('Medieval-2-Toolkit-main'))
args = parser.parse_args()
package = types.ModuleType('gate_formats')
package.__path__ = [str(args.addon.resolve() / 'm2formats')]
sys.modules[package.__name__] = package
cas = importlib.import_module(package.__name__ + '.cas')
original, exported = (cas.read_cas(path) for path in (args.original, args.exported))
assert original.nodes == exported.nodes, 'Bone order/name changed'
assert original.parents == exported.parents, 'Skeleton hierarchy changed'
assert len(original.objects) == len(exported.objects)
assert max(abs(a-b) for a, b in zip(original.pivots, exported.pivots)) < 2e-6

def corners(scene, obj):
    positions = cas.posed_positions(obj, cas.bind_world(scene))
    return [(tuple(positions[3*i:3*i+3]), tuple(obj.uvs[2*i:2*i+2]),
             scene.nodes[obj.bones[i]] if obj.bones else scene.nodes[0]) for i in obj.indices]

def close(a, b):
    return a[2] == b[2] and max(abs(x-y) for x, y in zip(a[0]+a[1], b[0]+b[1])) < 2e-6

for source, result in zip(original.objects, exported.objects):
    assert source.triangles == result.triangles
    a, b = corners(original, source), corners(exported, result)
    for i in range(0, len(a), 3):
        first, second = a[i:i+3], b[i:i+3]
        assert any(all(close(first[k], second[(k+offset) % 3]) for k in range(3))
                   for offset in range(3)), ('Triangle differs or winding reversed', source.name, i//3)
print('PASS original/native CAS bone order, hierarchy, pivots, triangle winding, positions, UVs and weights:', exported.triangles, 'triangles')
