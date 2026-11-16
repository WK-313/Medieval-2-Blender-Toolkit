"""Unit export textures: a non-power-of-two source (png or dds) must still give a
.texture, resized to a power of two by texconv, instead of being refused."""
import importlib, os, shutil, struct, sys, tempfile
from pathlib import Path
import bpy

SOURCE = Path(os.environ['MED2_ADDON_SOURCE']) if os.environ.get('MED2_ADDON_SOURCE') else next(
    c for p in Path(__file__).resolve().parents for c in (p / 'Medieval-2-Toolkit-main', p) if (c / 'm2formats').is_dir())

def ddsSize(path):
    with open(path, 'rb') as f:
        head = f.read(128)
    if head[:4] != b'DDS ':  # a .texture: 48-byte game header before the DDS
        with open(path, 'rb') as f:
            head = f.read(48 + 128)[48:]
    h, w = struct.unpack('<2I', head[12:20])
    return w, h

failures = []
with tempfile.TemporaryDirectory(prefix='pow2_') as temporary:
    temp = Path(temporary)
    shutil.copytree(SOURCE, temp / 'test_addon', ignore=shutil.ignore_patterns('__pycache__', '.git', 'graphify-out'))
    sys.path.insert(0, str(temp))
    addon = importlib.import_module('test_addon')
    addon.register()
    try:
        exporter = importlib.import_module('test_addon.tasks.unit_exporter')
        texconv = temp / 'test_addon' / 'bin' / 'texconv.exe'
        src = temp / 'src'; src.mkdir()
        cases = []
        for name, (w, h) in (('odd', (600, 500)), ('even', (512, 512))):
            img = bpy.data.images.new(name, w, h, alpha=True)
            img.pixels.foreach_set([0.5] * (w * h * 4))
            img.filepath_raw = str(src / (name + '.png')); img.file_format = 'PNG'; img.save()
            cases.append((name + '.png', src / (name + '.png')))
        # an odd-sized DXT5 dds WITH mips - the pass-through branch
        dds_dir = src / 'dds'; dds_dir.mkdir()
        made = exporter.runTexconv(str(texconv), str(src / 'odd.png'), str(dds_dir), 'odd_dds')
        # runTexconv may already apply -pow2 after the fix; force a real odd dds with texconv directly
        import subprocess
        subprocess.run([str(texconv), '-f', 'DXT5', '-m', '0', '-nologo', '-y', '-o', str(dds_dir), str(src / 'odd.png')], check=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert ddsSize(dds_dir / 'odd.dds') == (600, 500), ddsSize(dds_dir / 'odd.dds')
        cases.append(('odd.dds', dds_dir / 'odd.dds'))
        for label, path in cases:
            out = temp / ('out_' + label.replace('.', '_')); out.mkdir()
            error, warning = exporter.textureFromFile(str(texconv), str(path), str(out), 'tex', diffuse=True)
            tex = out / 'tex.texture'
            if error or not tex.exists():
                failures.append('%s: refused (%s)' % (label, error)); continue
            w, h = ddsSize(tex)
            ok = w & (w - 1) == 0 and h & (h - 1) == 0
            print('%s %s: .texture %dx%d warning=%r' % ('PASS' if ok else 'FAIL', label, w, h, warning))
            if not ok:
                failures.append(label)
            if label.startswith('odd') and not (warning and 'resized from 600x500' in warning):
                failures.append('%s: no resize warning (%r)' % (label, warning))
            if label.startswith('even') and warning:
                failures.append('%s: unexpected warning %r' % (label, warning))
    finally:
        addon.unregister()
if failures:
    print('FAIL', failures); sys.exit(1)
print('PASS all')
