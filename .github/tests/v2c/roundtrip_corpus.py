"""Read-only CAS corpus roundtrips. Pass donor main directory and one or more data roots."""
import argparse
import collections
import importlib
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module-root', type=Path, required=True)
    parser.add_argument('--package', default='unittransfer', choices=('unittransfer', 'm2formats'))
    parser.add_argument('--data-root', type=Path, action='append', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.module_root.resolve()))
    cas = importlib.import_module(args.package + '.cas')
    result = {'roots': [], 'total': 0, 'readable': 0, 'exact': 0, 'notes': 0, 'rejected': [], 'failures': []}
    for root in args.data_root:
        folder = root / 'models_strat'
        if not folder.is_dir():
            raise SystemExit(f'FAIL missing corpus folder: {folder}')
        counts = collections.Counter()
        for path in sorted(p for p in folder.rglob('*') if p.is_file() and p.suffix.lower() == '.cas'):
            counts['total'] += 1
            raw = path.read_bytes()
            try:
                scene = cas.read_cas_bytes(raw, str(path))
            except cas.CasError as exc:
                result['rejected'].append({'path': str(path), 'bytes': len(raw), 'reason': str(exc)})
                counts['rejected'] += 1
                continue
            counts['readable'] += 1
            counts['notes'] += bool(scene.notes)
            try:
                output = cas.write_cas(scene)
                if output != raw:
                    raise AssertionError(f'byte mismatch: input={len(raw)} output={len(output)} first={next((i for i,(a,b) in enumerate(zip(raw,output)) if a!=b), min(len(raw),len(output)))}')
                after = cas.read_cas_bytes(output, str(path))
                if (after.vertices, after.triangles, after.nodes) != (scene.vertices, scene.triangles, scene.nodes):
                    raise AssertionError('semantic reread mismatch')
                counts['exact'] += 1
            except Exception as exc:
                result['failures'].append({'path': str(path), 'reason': str(exc), 'notes': scene.notes})
        result['roots'].append({'path': str(root), **counts})
        for key in ('total', 'readable', 'exact', 'notes'):
            result[key] += counts[key]
        print(f"{'PASS' if counts['exact']==counts['readable'] else 'FAIL'} {root.parent.name}: {dict(counts)}")
    if args.report:
        args.report.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f"{'PASS' if not result['failures'] and result['exact'] else 'FAIL'} corpus: {result['exact']}/{result['readable']} byte-exact readable CAS; {len(result['rejected'])} reader rejections of {result['total']} files")
    for entry in result['failures'][:20]:
        print('FAIL', entry['path'], entry['reason'])
    return int(bool(result['failures']) or not result['exact'])


if __name__ == '__main__':
    raise SystemExit(main())
