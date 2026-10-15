"""Validation-only self-contained offline Windows portable AI bundle assembly.

Online access is allowed ONLY in the disposable GitHub Actions packaging job
to retrieve PUBLIC and permissively licensed CPU runtime/model assets. Nothing
is downloaded at application runtime and neither private manuscripts nor API
tokens belong in this zip. Always label output as experimental QA, not release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen
from zipfile import ZipFile

from huggingface_hub import hf_hub_download

LLAMA_RELEASE = 'b11624'
LLAMA_RUNTIME = ('https://github.com/ggml-org/llama.cpp/releases/download/'
                 'b11624/llama-b11624-bin-win-cpu-x64.zip')
LLAMA_SHA256 = '57f436b5153fc411b4dc13a2d24b45d91968e1163a6c5bf3941d20bb28689e8c'
MODEL_REPOSITORY = 'bartowski/SmolLM2-135M-Instruct-GGUF'
MODEL_FILE = 'SmolLM2-135M-Instruct-Q4_K_M.gguf'
MODEL_LICENSE = 'Apache-2.0'
RELEASE_NOTE = """AI Novel Factory Portable — EXPERIMENTAL QA / NOT A PUBLIC RELEASE

Run AI_Novel_Factory.exe on Windows x64 without installing Python, PyTorch,
or a hosted model. The console mode ANF_Local_Model.exe launches the bundled
CPU-only llama.cpp runtime and the bundled SmolLM2-135M Q4_K_M GGUF weight.
All local inference calls use Windows subprocess pipes and run offline.

The 135M model is tiny and not suitable to certify coherent Korean-language
250-episode novels. Set the expected length and review every generated draft.
Never auto-publish. An end-to-end demonstration is NOT content-quality approval.
Actual Windows 10/11 x64 physical visual acceptance remains separate.

Do not treat original reference novels or user credential files as packaging
inputs. Program settings and manuscripts stay on the user's local disk.
"""


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download_public(url: str, target: Path) -> Path:
    if target.exists():
        return target
    with urlopen(Request(url, headers={'User-Agent': 'ANF-validation-bundle'}),
                 timeout=120) as source, target.open('xb') as dest:
        shutil.copyfileobj(source, dest, 1024 * 1024)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--gui-exe', type=Path, required=True)
    parser.add_argument('--bridge-exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=Path('build/ci/portable-downloads'))
    args = parser.parse_args(argv)
    root = args.output.resolve()
    cache = args.cache.resolve()
    if root.exists():
        raise RuntimeError('Refusing to overwrite an existing portable output folder')
    if not args.gui_exe.is_file() or not args.bridge_exe.is_file():
        raise RuntimeError('Both compiled Windows executables are required')
    cache.mkdir(parents=True, exist_ok=True)
    zip_file = download_public(LLAMA_RUNTIME, cache / 'llama-cpu-x64-b11624.zip')
    if file_hash(zip_file) != LLAMA_SHA256:
        raise RuntimeError('llama.cpp release SHA256 mismatch — stop packaging')
    model_cache = hf_hub_download(repo_id=MODEL_REPOSITORY, filename=MODEL_FILE,
                                  local_dir=str(cache / 'model'))
    model_cache = Path(model_cache)
    if not model_cache.is_file() or model_cache.stat().st_size < 70_000_000:
        raise RuntimeError('GGUF missing, incomplete, or unexpectedly small')
    root.mkdir(parents=True)
    runtime = root / 'runtime'
    runtime.mkdir()
    model = root / 'models'
    model.mkdir()
    licenses = root / 'licenses'
    licenses.mkdir()
    shutil.copy2(args.gui_exe, root / 'AI_Novel_Factory.exe')
    shutil.copy2(args.bridge_exe, root / 'ANF_Local_Model.exe')
    copied = set()
    with ZipFile(zip_file) as archive:
        for member in archive.infolist():
            name = Path(member.filename).name
            if not name or Path(name).suffix.lower() not in ('.dll', '.exe'):
                continue
            if name.lower() in copied:
                raise RuntimeError('Ambiguous duplicate CPU runtime binary: ' + name)
            copied.add(name.lower())
            with archive.open(member) as src, (runtime / name).open('xb') as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    if not (runtime / 'llama-cli.exe').is_file():
        raise RuntimeError('CPU package did not contain llama-cli.exe')
    shutil.copy2(model_cache, model / MODEL_FILE)

    licenses_sources = {
        'llama-cpp-MIT.txt':
            'https://raw.githubusercontent.com/ggml-org/llama.cpp/b11624/LICENSE',
        'model-Apache-2.0.txt':
            'https://www.apache.org/licenses/LICENSE-2.0.txt',
    }
    for name, url in licenses_sources.items():
        source = download_public(url, cache / name)
        if source.stat().st_size < 1000:
            raise RuntimeError('License text incomplete: ' + name)
        shutil.copy2(source, licenses / name)
    (root / 'README-QA.txt').write_text(RELEASE_NOTE, encoding='utf-8')

    check = subprocess.run([str(root / 'ANF_Local_Model.exe'), '--self-test'],
                           cwd=root, capture_output=True, text=True,
                           errors='replace', timeout=45)
    if check.returncode:
        raise RuntimeError('Bundled llama.cpp runtime self-test failed: '
                           + str(check.returncode))

    manifest = dict(kind='ANF_PORTABLE_OFFLINE_QA_NOT_RELEASE',
                    public_model=MODEL_REPOSITORY + '/' + MODEL_FILE,
                    public_model_license=MODEL_LICENSE,
                    llama_cpp_release=LLAMA_RELEASE,
                    external_account_required=False,
                    local_ai_after_download=True,
                    quality_or_250_episodes_certified=False,
                    os='Windows x64',
                    contents={p.relative_to(root).as_posix():
                              {'bytes': p.stat().st_size, 'sha256': file_hash(p)}
                              for p in sorted(root.rglob('*')) if p.is_file()})
    (root / 'bundle-manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(json.dumps({'bundle_type':manifest['kind'],
                      'file_count':len(manifest['contents']),
                      'model_sha256':file_hash(model / MODEL_FILE),
                      'model_bytes':(model / MODEL_FILE).stat().st_size,
                      'llama_runtime_self_test':'PASS',
                      'user_files_packaged':False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
