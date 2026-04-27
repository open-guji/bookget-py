# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for bookget-cli.exe
Minimal CLI-only build (no server, no frontend assets).
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent

# Auto-discover all adapter modules so we never miss a new one.
# Replaces the previous hand-maintained list which silently dropped new adapters
# (v0.3.0 shipped without bookget.adapters.iiif.kyoto for this reason).
adapter_imports = collect_submodules('bookget.adapters')

a = Analysis(
    [str(ROOT / 'bookget' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        *adapter_imports,
        # core
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
