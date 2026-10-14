"""Build local cumulative ZIP; preserve dotfiles and compare stage77 baseline."""
from pathlib import Path
import zipfile
import hashlib
import sys

root=Path(__file__).resolve().parents[1]
prior=Path('/mnt/data/AI_Novel_Factory_stage77_local.zip')
target=Path('/mnt/data/AI_Novel_Factory_stage78_local.zip')
excluded={'.DS_Store'}
files=sorted(p for p in root.rglob('*') if p.is_file() and
             not any(part in {'__pycache__','.pytest_cache','.git'} for part in p.relative_to(root).parts) and
             p.suffix!='.pyc' and p.name not in excluded)
with zipfile.ZipFile(prior) as baseline:
    old=set(baseline.namelist())
    new={p.relative_to(root).as_posix() for p in files}
    missing=old-new
    assert not missing, f'missing baseline entries: {sorted(missing)}'
    changed=[]
    for name in old:
        if baseline.read(name)!= (root/name).read_bytes():
            changed.append(name)
    assert changed==['README.md'], f'unexpected baseline modification: {changed}'
with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
    for p in files:
        z.write(p,p.relative_to(root).as_posix())
with zipfile.ZipFile(target) as z:
    assert z.testzip() is None
    assert len(z.namelist())==len(files)
    assert all(x in z.namelist() for x in ('.gitignore','.env.example','.python-version'))
print(f'zip={target} files={len(files)} prior={len(old)} added={len(files)-len(old)}')
print(f'sha256={hashlib.sha256(target.read_bytes()).hexdigest()}')
