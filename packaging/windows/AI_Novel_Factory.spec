# -*- mode: python ; coding: utf-8 -*-
"""One-file Windows GUI executable. Run ONLY on an offline Windows Python 3.12 host.

Usage (through scripts/build_windows_exe.py; no installers or downloads here):
    python -m PyInstaller --noconfirm --distpath dist/stage97 --workpath build/stage97 packaging/windows/AI_Novel_Factory.spec
"""
from pathlib import Path

# SPECPATH is defined by PyInstaller as the directory containing this spec.
PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]

analysis = Analysis(
    [str(PROJECT_ROOT / 'packaging' / 'windows' / 'launcher.py')],
    pathex=[str(PROJECT_ROOT / 'src')],
    binaries=[],
    datas=[],
    # The desktop entry point lazily imports app.py so static tracing misses it.
    hiddenimports=['ai_novel_factory.desktop.app', 'ai_novel_factory.desktop.ci_user_journey'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name='AI_Novel_Factory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
