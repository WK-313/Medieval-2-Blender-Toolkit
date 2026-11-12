"""GitHub release downloads and staged installation (no Blender API calls)."""
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import urllib.request
import zipfile

REPOSITORY = 'WK-313/Medieval-2-Blender-Toolkit'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_UNPACKED = 512 * 1024 * 1024


def version_tuple(value):
    match = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', value)
    if not match:
        raise ValueError('Release version must have the form v1.2.3')
    return tuple(map(int, match.groups()))


def request(url):
    return urllib.request.urlopen(urllib.request.Request(
        url, headers={'User-Agent': 'Medieval-2-Toolkit-Updater',
                      'Accept': 'application/vnd.github+json'}), timeout=30)


def latest_release():
    with request(API_URL) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Release response is too large')
    release = json.loads(data)
    version = version_tuple(release['tag_name'])
    if release.get('draft') or release.get('prerelease'):
        raise ValueError('Only published stable releases can be installed')
    tag = release['tag_name']
    name = 'Medieval-2-Toolkit-v%s.zip' % '.'.join(map(str, version))
    asset = next((a for a in release.get('assets', []) if a['name'] == name), None)
    if asset is None:
        raise ValueError('The latest release has no installable toolkit ZIP')
    url = f'https://github.com/{REPOSITORY}/releases/download/{tag}/{name}'
    if asset['browser_download_url'] != url:
        raise ValueError('Unexpected release download URL')
    return dict(version=version, url=url, digest=asset.get('digest'), size=asset['size'])


def package_info(folder):
    """Read metadata without executing downloaded Python."""
    tree = ast.parse((folder / '__init__.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('The ZIP has no addon metadata')


def stage_archive(archive, stage, expected, blender_version):
    """Reject unsafe ZIP paths and verify metadata before touching the install."""
    with zipfile.ZipFile(archive) as z:
        files = z.infolist()
        if len(files) > 10000 or sum(f.file_size for f in files) > MAX_UNPACKED:
            raise ValueError('Release ZIP exceeds extraction limits')
        roots, seen = set(), set()
        for f in files:
            p = PurePosixPath(f.filename)
            if (p.is_absolute() or '..' in p.parts or '\\' in f.filename
                    or ':' in f.filename or not p.parts
                    or stat.S_ISLNK(f.external_attr >> 16)):
                raise ValueError('Unsafe path in release ZIP')
            key = str(p).casefold().rstrip('/')
            if key in seen:
                raise ValueError('Duplicate path in release ZIP')
            seen.add(key)
            roots.add(p.parts[0])
        if len(roots) != 1:
            raise ValueError('Release ZIP must contain one addon folder')
        z.extractall(stage)
    folder = stage / roots.pop()
    info = package_info(folder)
    if tuple(info['version']) != tuple(expected):
        raise ValueError('Release tag and addon version do not match')
    if tuple(info['blender']) > tuple(blender_version):
        raise ValueError('This release requires Blender %s' % '.'.join(map(str, info['blender'])))
    for required in ('panels', 'tasks', 'directories.py'):
        if not (folder / required).exists():
            raise ValueError('Incomplete toolkit release ZIP')
    return folder


def download_release(release, destination):
    if not 0 < release['size'] <= MAX_DOWNLOAD:
        raise ValueError('Release download exceeds size limit')
    digest, count = hashlib.sha256(), 0
    with request(release['url']) as response, destination.open('wb') as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            count += len(block)
            if count > MAX_DOWNLOAD:
                raise ValueError('Release download exceeds size limit')
            digest.update(block)
            output.write(block)
    if count != release['size']:
        raise ValueError('Incomplete release download')
    expected = release.get('digest')
    if expected and expected != 'sha256:' + digest.hexdigest():
        raise ValueError('Release download checksum does not match GitHub')


def install_staged(staged, target):
    """Keep a full backup; restore it if replacing the install fails."""
    target = target.resolve()
    for relative in ('text', 'assets/Saved', 'assets/blender_assets.cats.txt'):
        source, dest = target / relative, staged / relative
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        elif source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    backup_root = target.parent.parent / 'med2-update-backups'
    backup_root.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=target.name + '-', dir=backup_root)) / target.name
    target.rename(backup)
    try:
        staged.rename(target)
    except Exception:
        backup.rename(target)
        raise
    return backup
