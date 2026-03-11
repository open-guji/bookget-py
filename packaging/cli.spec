# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for bookget-cli.exe
Minimal CLI-only build (no server, no frontend assets).
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / 'bookget' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        'bookget.adapters',
        'bookget.adapters.registry',
        'bookget.adapters.chinese',
        'bookget.adapters.iiif',
        'bookget.core',
        'bookget.models',
        'bookget.text_parsers',
        'bookget.text_converters',
        'aiohttp',
        'aiohttp.web',
        'multidict',
        'yarl',
        'async_timeout',
        'charset_normalizer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'PyQt5', 'wx'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='bookget-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
