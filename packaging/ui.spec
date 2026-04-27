# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for bookget-ui.exe
Bundles server module + built frontend (ui/dist-app/).
Double-click to launch browser UI at http://localhost:8765.
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
DIST_APP = ROOT / 'ui' / 'dist-app'

if not DIST_APP.exists():
    raise FileNotFoundError(
        f"Frontend not built: {DIST_APP}\n"
        "Run: cd ui && npm run build:app"
    )

# Auto-discover all adapter modules so we never miss a new one.
adapter_imports = collect_submodules('bookget.adapters')

a = Analysis(
    [str(ROOT / 'bookget' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle entire frontend dist
        (str(DIST_APP), 'ui/dist-app'),
    ],
    hiddenimports=[
        *adapter_imports,
        # core
        'bookget.core',
        'bookget.models',
        'bookget.server',
        'bookget.server.app',
        'bookget.server.routes',
        'bookget.server.sse',
        'bookget.server.static',
        'bookget.server.tasks',
        'bookget.text_parsers',
        'bookget.text_converters',
        'aiohttp',
        'aiohttp.web',
        'aiohttp.web_middlewares',
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
    name='bookget-ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # No console window — browser-only UI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
