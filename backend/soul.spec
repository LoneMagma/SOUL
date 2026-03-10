# -*- mode: python ; coding: utf-8 -*-
# SOUL — PyInstaller spec
# Place this file at: backend/soul.spec
# Run from repo root via build.bat — do not run directly.

import sys
from pathlib import Path

backend_dir = Path(SPECPATH)   # resolves to the directory containing this .spec file

a = Analysis(
    [str(backend_dir / 'main.py')],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        # Include the memory and actions packages explicitly so
        # PyInstaller doesn't miss them on some Python installs.
        (str(backend_dir / 'memory'),     'memory'),
        (str(backend_dir / 'actions'),    'actions'),
        (str(backend_dir / 'perception'), 'perception'),
    ],
    hiddenimports=[
        # ── uvicorn internals ────────────────────────────────
        'uvicorn',
        'uvicorn.main',
        'uvicorn.config',
        'uvicorn.server',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.middleware',
        'uvicorn.middleware.proxy_headers',
        # ── FastAPI / Starlette ──────────────────────────────
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        'starlette.websockets',
        'starlette.responses',
        'starlette.background',
        # ── Pydantic ─────────────────────────────────────────
        'pydantic',
        'pydantic.v1',
        'pydantic_core',
        # ── HTTP client ──────────────────────────────────────
        'httpx',
        'httpcore',
        'h11',
        'h2',
        'hpack',
        'hyperframe',
        'anyio',
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        'sniffio',
        # ── WebSockets ───────────────────────────────────────
        'websockets',
        'websockets.legacy',
        'websockets.legacy.server',
        'websockets.legacy.client',
        'wsproto',
        # ── TTS ──────────────────────────────────────────────
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        # ── Vision / system ──────────────────────────────────
        'PIL',
        'PIL.Image',
        'PIL.ImageGrab',
        'psutil',
        'psutil._pswindows',
        # ── Standard lib extras ──────────────────────────────
        'sqlite3',
        'email.mime.text',
        'email.mime.multipart',
        'importlib.metadata',
        'importlib.resources',
        'pkg_resources',
        'pkg_resources.extern',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we definitely don't need — keeps the exe smaller
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'PyQt5',
        'PyQt6',
        'wx',
        'test',
        'unittest',
        'xmlrpc',
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='soul_backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression triggers AV more aggressively — leave off
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # no console window — logs go to stdout which Electron captures
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(backend_dir / '..' / 'frontend' / 'assets' / 'icon.ico'),
)
