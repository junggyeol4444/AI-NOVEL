"""Stage 99 reproducible cumulative source ZIP; offline, no Git/network access."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PREV = ROOT.parent / 'AI_Novel_Factory_stage98_local.zip'
ALLOWED_ROOTS = {'src', 'tests', 'docs', 'scripts', 'packaging'}
ALLOWED_TOP = {'.gitignore', '.env.example', '.editorconfig', '.python-version', 'README.md', 'pyproject.toml'}
MODIFIED_OLD = {'README.md'}
DISALLOWED_PARTS = {'__pycache__', '.git', '.github', 'build', 'dist', 'user_data', 'secrets',
                    'manuscripts', 'reference_uploads', '.pytest_cache'}


def collect_files() -> dict[str, Path]:
    files = {}
    for p in ROOT.rglob('*'):
        if not p.is_file() or p.is_symlink():
            continue
        name = p.relative_to(ROOT).as_posix()
        parts = p.relative_to(ROOT).parts
        if any(part in DISALLOWED_PARTS for part in parts):
            continue
        if name in ALLOWED_TOP or parts[0] in ALLOWED_ROOTS:
            if p.suffix.lower() in {'.pyc', '.pyo', '.db', '.sqlite3', '.pem', '.key'}:
                continue
            if name.startswith('docs/stage99_') or not name.endswith('.log'):
                # Legacy stage85 .log files must be retained, despite the suffix.
                files[name] = p
            elif name.startswith('docs/stage85_worktree_driver_part') and name.endswith('_background.log'):
                files[name] = p
    return files


def pack(destination: Path, previous: Path = PREV) -> dict:
    files = collect_files()
    with ZipFile(previous) as archive:
        previous_names = set(archive.namelist())
        if len(previous_names) != len(archive.namelist()):
            raise RuntimeError('duplicate_previous_entry')
        lost = sorted(previous_names - files.keys())
        changed = sorted(name for name in previous_names & files.keys()
                         if sha256(archive.read(name)).digest() != sha256(files[name].read_bytes()).digest())
        if lost or set(changed) - MODIFIED_OLD or archive.testzip():
            raise RuntimeError('prior_sources_changed_or_missing')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=6) as out:
        for name, path in sorted(files.items()):
            out.write(path, arcname=name)
    with ZipFile(destination) as check:
        bad = check.testzip()
        if bad or set(check.namelist()) != set(files):
            raise RuntimeError('bad_final_archive')
    return {'file_count':len(files), 'previous_count':len(previous_names),
            'previous_preserved': len(previous_names), 'changed_previous': changed,
            'added_files':len(files)-len(previous_names), 'crc_ok':True,
            'zip_sha256':sha256(destination.read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    parser.add_argument('--previous', type=Path, default=PREV)
    args=parser.parse_args()
    print(json.dumps(pack(args.destination, args.previous),indent=2))
