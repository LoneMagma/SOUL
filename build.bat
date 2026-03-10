@echo off
REM ════════════════════════════════════════════════════════════════
REM  SOUL v1.5 — Full EXE Build
REM  Drop this file in the repo root (same level as backend/ and frontend/)
REM  Run: build.bat
REM  Output: frontend\dist\SOUL Setup 1.5.0.exe
REM
REM  Stage 1: PyInstaller  → backend\dist\soul_backend.exe
REM  Stage 2: electron-builder → frontend\dist\SOUL Setup 1.5.0.exe
REM ════════════════════════════════════════════════════════════════

title SOUL Builder
setlocal EnableDelayedExpansion

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║         SOUL v1.5 — EXE Build                ║
echo  ╚══════════════════════════════════════════════╝
echo.

REM ── Sanity checks ──────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python not found. Install Python 3.11+ and ensure it is on PATH.
    pause & exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] node not found. Install Node.js 18+.
    pause & exit /b 1
)

if not exist "backend\soul.spec" (
    echo [ERROR] backend\soul.spec not found. Place soul.spec in the backend\ folder.
    pause & exit /b 1
)

if not exist "frontend\package.json" (
    echo [ERROR] frontend\package.json not found.
    pause & exit /b 1
)

REM ── Stage 1: PyInstaller ───────────────────────────────
echo [Stage 1/2] Building Python backend with PyInstaller...
echo.

python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo  Installing PyInstaller...
    pip install pyinstaller --quiet
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause & exit /b 1
    )
)

echo  Checking backend Python deps...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] pip install -r requirements.txt failed.
    pause & exit /b 1
)

if exist "backend\dist"  rmdir /s /q "backend\dist"
if exist "backend\build" rmdir /s /q "backend\build"

echo  Running PyInstaller (this takes 1-4 minutes)...
cd backend
python -m PyInstaller soul.spec --distpath dist --workpath build --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. Common causes:
    echo   - Missing hidden import: add it to soul.spec hiddenimports and retry.
    echo   - Module not installed: run  pip install -r requirements.txt  and retry.
    cd ..
    pause & exit /b 1
)
cd ..

if not exist "backend\dist\soul_backend.exe" (
    echo [ERROR] soul_backend.exe was not produced. Check PyInstaller output above.
    pause & exit /b 1
)
echo  soul_backend.exe built successfully.
echo.

REM ── Stage 2: electron-builder ──────────────────────────
echo [Stage 2/2] Building Electron installer...
echo.

cd frontend

if not exist "node_modules" (
    echo  Running npm install...
    call npm install --prefer-offline
    if errorlevel 1 (
        echo [ERROR] npm install failed.
        cd ..
        pause & exit /b 1
    )
)

if exist "dist" rmdir /s /q "dist"

call npm run build:win
if errorlevel 1 (
    echo.
    echo [ERROR] electron-builder failed. Common causes:
    echo   - assets\icon.ico missing or wrong format (must be 256x256 ICO)
    echo   - node_modules incomplete: delete frontend\node_modules and retry
    cd ..
    pause & exit /b 1
)
cd ..

echo.
echo  ╔══════════════════════════════════════════════════════════════╗
echo  ║  BUILD COMPLETE                                              ║
echo  ║                                                              ║
echo  ║  Installer: frontend\dist\SOUL Setup 1.5.0.exe              ║
echo  ║                                                              ║
echo  ║  Self-contained — no Python required on end user machine.   ║
echo  ║                                                              ║
echo  ║  After install, user places GROQ key in:                    ║
echo  ║    %%APPDATA%%\soul\.env                                       ║
echo  ║  Format: GROQ_API_KEY=gsk_xxxx                              ║
echo  ╚══════════════════════════════════════════════════════════════╝
echo.
start "" "frontend\dist"
pause
