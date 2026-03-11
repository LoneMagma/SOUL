# -*- mode: python ; coding: utf-8 -*-
# SOUL — PyInstaller Spec  v1.6
#
# Run from repo root:
#   pyinstaller backend/soul.spec --distpath backend/dist --noconfirm
#
# Output: backend/dist/soul_backend.exe
# electron-builder then picks this up via extraResources in package.json.

import sys
from pathlib import Path

backend_dir = Path(SPECPATH)   # resolves to backend/

a = Analysis(
    [str(backend_dir / 'main.py')],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=[
        # All backend packages — PyInstaller misses these on some Python installs
        (str(backend_dir / 'memory'),        'memory'),
        (str(backend_dir / 'actions'),       'actions'),
        (str(backend_dir / 'perception'),    'perception'),
        (str(backend_dir / 'voice'),         'voice'),
        # verifier.py lives at backend root — include explicitly
        (str(backend_dir / 'verifier.py'),   '.'),
    ],
    hiddenimports=[
        # ── uvicorn internals ─────────────────────────────────────────────────
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
        # ── FastAPI / Starlette ───────────────────────────────────────────────
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
        # ── Pydantic ─────────────────────────────────────────────────────────
        'pydantic',
        'pydantic.v1',
        'pydantic_core',
        # ── HTTP client ───────────────────────────────────────────────────────
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
        # ── WebSockets ────────────────────────────────────────────────────────
        'websockets',
        'websockets.legacy',
        'websockets.legacy.server',
        'websockets.legacy.client',
        'wsproto',
        # ── Automation — pyautogui stack ──────────────────────────────────────
        # All of these are pulled in by pyautogui on Windows; list explicitly
        # because PyInstaller doesn't follow the lazy imports inside pyautogui.
        'pyautogui',
        'pyautogui._pyautogui_win',
        'pygetwindow',
        'pygetwindow._pygetwindow_win',
        'pymsgbox',
        'pytweening',
        'mouseinfo',
        'pyscreeze',
        # ── TTS ───────────────────────────────────────────────────────────────
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        # ── Vision / screen capture ───────────────────────────────────────────
        'PIL',
        'PIL.Image',
        'PIL.ImageGrab',
        'PIL.ImageOps',
        # ── System monitoring ─────────────────────────────────────────────────
        'psutil',
        'psutil._pswindows',
        # ── Standard lib extras ───────────────────────────────────────────────
        'sqlite3',
        'email.mime.text',
        'email.mime.multipart',
        'importlib.metadata',
        'importlib.resources',
        'pkg_resources',
        'pkg_resources.extern',
        # ── Difflib (used by verifier + observer similarity scoring) ─────────
        'difflib',
        # ── win32 (pygetwindow dependency on Windows) ─────────────────────────
        'win32api',
        'win32con',
        'win32gui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Unused GUI frameworks — keeps exe smaller and reduces AV heuristic surface
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
    # UPX off: compression triggers AV heuristics aggressively — not worth it
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=True for the friends/test build so crash output is visible.
    # Flip to False for the public GitHub release.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(backend_dir / '..' / 'frontend' / 'assets' / 'icon.ico'),
)
