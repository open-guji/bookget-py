# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for bookget-ui.exe
Bundles server module + built frontend (ui/dist-app/).
Double-click to launch browser UI at http://localhost:8765.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
DIST_APP = ROOT / 'ui' / 'dist-app'

if not DIST_APP.exists():
    raise FileNotFoundError(
        f"Frontend not built: {DIST_APP}\n"
        "Run: cd ui && npm run build:app"
    )

a = Analysis(
    [str(ROOT / 'bookget' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle entire frontend dist
        (str(DIST_APP), 'ui/dist-app'),
    ],
    hiddenimports=[
        'bookget.adapters',
        'bookget.adapters.registry',
        # iiif adapters
        'bookget.adapters.iiif',
        'bookget.adapters.iiif.base_iiif',
        'bookget.adapters.iiif.harvard',
        'bookget.adapters.iiif.kyoto',
        'bookget.adapters.iiif.ndl',
        'bookget.adapters.iiif.princeton',
        'bookget.adapters.iiif.stanford',
        # other adapters
        'bookget.adapters.other',
        'bookget.adapters.other.archive_org',
        'bookget.adapters.other.ctext',
        'bookget.adapters.other.european',
        'bookget.adapters.other.hanchi',
        'bookget.adapters.other.nlc_guji',
        'bookget.adapters.other.shidianguji',
        'bookget.adapters.other.taiwan',
        'bookget.adapters.other.wikimedia_commons',
        'bookget.adapters.other.wikisource',
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
