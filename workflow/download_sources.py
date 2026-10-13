"""Fetch pinned upstream archives and verify every file against its Git blob ID."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import os
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def blob_sha(content):
    return hashlib.sha1(f'blob {len(content)}\0'.encode() + content).hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError(f'Unsafe upstream path: {name}')
    return Path(*path.parts)


def content_at(path):
    if path.is_symlink():
        return os.readlink(path).encode()
    return path.read_bytes()


def verify_repo(repo, root=ROOT):
    base = root / 'projects' / repo['folder']
    missing = []
    for entry in repo['tree']:
        if entry['type'] != 'blob':
            continue
        path = base / safe_relative(entry['path'])
        if not path.exists() and not path.is_symlink():
            missing.append(entry)
        elif blob_sha(content_at(path)) != entry['sha']:
            raise ValueError(f'Upstream file changed; refusing to overwrite: {repo["folder"]}/{entry["path"]}')
    return missing


def install_archive(repo, archive_bytes, root=ROOT):
    base = root / 'projects' / repo['folder']
    missing = verify_repo(repo, root)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        prefix = names[0].split('/')[0] + '/'
        pending = []
        # Validate the entire required payload before writing any upstream file.
        for entry in missing:
            relative = safe_relative(entry['path'])
            payload = archive.read(prefix + entry['path'])
            if blob_sha(payload) != entry['sha']:
                raise ValueError(f'Git blob checksum mismatch: {entry["path"]}')
            target = base / relative
            if not target.resolve().is_relative_to(base.resolve()):
                raise ValueError('Unsafe destination')
            if entry['mode'] == '120000':
                dest = payload.decode()
                if not (target.parent / dest).resolve().is_relative_to(base.resolve()):
                    raise ValueError('Unsafe upstream symlink')
            pending.append((entry, target, payload))
        # Regular files first, so archive symlinks cannot redirect writes.
        for entry, target, payload in sorted(pending, key=lambda item: item[0]['mode'] == '120000'):
            if not target.parent.resolve().is_relative_to(base.resolve()):
                raise ValueError('Unsafe destination parent')
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry['mode'] == '120000':
                target.symlink_to(payload.decode())
            else:
                target.write_bytes(payload)
                target.chmod(0o755 if entry['mode'] == '100755' else 0o644)
    if verify_repo(repo, root):
        raise ValueError('Incomplete extraction')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true', help='Verify existing files without downloading')
    args = parser.parse_args()
    repos = json.loads((ROOT / 'workflow/source-trees.json').read_text())
    for repo in repos:
        if repo.get('truncated'):
            raise ValueError('Incomplete source manifest')
        missing = verify_repo(repo)
        if missing and args.verify:
            raise ValueError(f'{repo["folder"]}: {len(missing)} files missing')
        if missing:
            print(f'Downloading pinned {repo["folder"]}...', flush=True)
            url = f'https://codeload.github.com/{repo["repo"]}/zip/{repo["sha"]}'
            req = urllib.request.Request(url, headers={'User-Agent': 'wechat-article-workflow'})
            with urllib.request.urlopen(req, timeout=120) as response:
                install_archive(repo, response.read())
        print(f'{repo["folder"]}: pinned files verified', flush=True)


if __name__ == '__main__':
    main()
