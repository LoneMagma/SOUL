/**
 * SOUL — Electron Main Process
 * v6: Workspace panel, fixed ambient, IPC for workspace
 * v6.1: Packaged-mode backend detection (soul_backend.exe)
 */

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage,
        shell, globalShortcut } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const BACKEND_PORT = 8765;

function getConfigPath() {
  return path.join(app.getPath('userData'), 'config.json');
}

let mainWindow    = null;
let workspaceWin  = null;
// tray: reserved for v2 system tray implementation
let backendProcess = null;
let isAmbient     = false;

// ── Port utils ──────────────────────────────────────────
function isPortInUse(port) {
  return new Promise(resolve => {
    const t = net.createConnection({ port, host: '127.0.0.1' });
    t.once('connect', () => { t.destroy(); resolve(true); });
    t.once('error', () => resolve(false));
  });
}
function waitForPort(port, maxAttempts = 30) {
  return new Promise(resolve => {
    let n = 0;
    const iv = setInterval(async () => {
      n++;
      if (await isPortInUse(port)) { clearInterval(iv); resolve(true); }
      else if (n >= maxAttempts) { clearInterval(iv); resolve(false); }
    }, 500);
  });
}

// ── Env / key loader ────────────────────────────────────
// Checks (in order):
//   1. .env next to the exe / in the source tree (dev)
//   2. userData folder — users drop their .env here after install
//   3. process.env (system environment variable)
function loadEnvKey(key) {
  const locations = [
    path.join(__dirname, '..', '.env'),
    path.join(__dirname, '.env'),
    path.join(app.getPath('userData'), '.env'),   // packaged: user drops .env here
  ];
  for (const p of locations) {
    if (fs.existsSync(p)) {
      const m = fs.readFileSync(p, 'utf8').match(new RegExp(`^${key}=(.+)$`, 'm'));
      if (m) return m[1].trim();
    }
  }
  return process.env[key] || '';
}

// ── Backend ─────────────────────────────────────────────
async function startBackend() {
  if (await isPortInUse(BACKEND_PORT)) {
    console.log('[SOUL] Backend already running, attaching...');
    return true;
  }

  const userData = app.getPath('userData');
  const envVars = {
    ...process.env,
    GROQ_API_KEY:       loadEnvKey('GROQ_API_KEY'),
    PORCUPINE_KEY:      loadEnvKey('PORCUPINE_KEY'),
    SOUL_DATA_DIR:      userData,
    PYTHONUTF8:         '1',
    PYTHONIOENCODING:   'utf-8',
  };

  if (app.isPackaged) {
    // ── Packaged mode: launch the frozen soul_backend.exe ──
    // electron-builder copies it to resources/backend/soul_backend.exe
    const exePath = path.join(process.resourcesPath, 'backend', 'soul_backend.exe');
    console.log('[SOUL] Packaged mode — launching:', exePath);

    if (!fs.existsSync(exePath)) {
      console.error('[SOUL] soul_backend.exe not found at:', exePath);
      return false;
    }

    backendProcess = spawn(exePath, [], {
      env: envVars,
      cwd: path.join(process.resourcesPath, 'backend'),
      // detached: false so it dies with Electron
    });
  } else {
    // ── Dev mode: launch via python ──────────────────────
    const py = process.platform === 'win32' ? 'python' : 'python3';
    const backendPath = path.join(__dirname, '..', 'backend', 'main.py');
    console.log('[SOUL] Dev mode — starting backend:', backendPath);

    backendProcess = spawn(py, [backendPath], {
      env: envVars,
      cwd: path.join(__dirname, '..', 'backend'),
    });
  }

  backendProcess.stdout.on('data', d => {
    const txt = d.toString().trim();
    console.log(`[Backend] ${txt}`);
    workspaceWin?.webContents.send('backend-log', txt);
  });
  backendProcess.stderr.on('data', d => console.log(`[Backend] ${d.toString().trim()}`));
  backendProcess.on('close', code => {
    if (code !== 0 && mainWindow)
      mainWindow.webContents.send('backend-error', 'Backend stopped. Check your GROQ_API_KEY.');
  });

  return await waitForPort(BACKEND_PORT);
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

// ── Main Window ─────────────────────────────────────────
function createMainWindow() {
  const configPath = getConfigPath();
  const isFirstRun = !fs.existsSync(configPath);
  const htmlFile = isFirstRun ? 'onboarding.html' : 'index.html';
  const htmlPath = path.join(__dirname, 'renderer', htmlFile);

  console.log('[SOUL] Config:', configPath);
  console.log('[SOUL] Loading:', htmlPath, '| exists:', fs.existsSync(htmlPath));

  const { screen } = require('electron');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: 400,
    height: 640,
    frame: false,
    transparent: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    alwaysOnTop: false,
    resizable: false,
    show: false,
    roundedCorners: true,
    x: width - 420,
    y: height - 660,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  });

  mainWindow.loadFile(htmlPath).catch(err => {
    console.error('[SOUL] loadFile failed:', err);
    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'))
      .catch(e => console.error('[SOUL] fallback failed:', e));
  });

  mainWindow.webContents.on('did-fail-load', (_, code, desc) => {
    console.error(`[SOUL] Load failed: ${code} ${desc}`);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[SOUL] Page loaded successfully');
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
    workspaceWin?.close();
  });
}

// ── Workspace Window ─────────────────────────────────────
function createWorkspaceWindow() {
  if (workspaceWin && !workspaceWin.isDestroyed()) {
    workspaceWin.focus();
    return;
  }

  const { screen } = require('electron');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const mainBounds = mainWindow?.getBounds() || { x: width - 420, y: height - 660 };

  workspaceWin = new BrowserWindow({
    width: 480,
    height: 720,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    alwaysOnTop: false,
    resizable: false,
    show: false,
    roundedCorners: true,
    x: mainBounds.x - 492,
    y: Math.max(0, mainBounds.y - 40),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  });

  const wsPath = path.join(__dirname, 'renderer', 'workspace.html');
  workspaceWin.loadFile(wsPath).catch(e => console.error('[SOUL] workspace load failed:', e));
  workspaceWin.webContents.on('did-finish-load', () => workspaceWin.show());
  workspaceWin.on('closed', () => {
    workspaceWin = null;
    mainWindow?.webContents.send('workspace-closed');
  });
}

function toggleWorkspace() {
  if (!workspaceWin || workspaceWin.isDestroyed()) {
    createWorkspaceWindow();
    mainWindow?.webContents.send('workspace-opened');
  } else {
    workspaceWin.close();
  }
}

// ── Ambient orb window ────────────────────────────────────
let orbWindow = null;

function enterAmbient() {
  if (!mainWindow) return;
  isAmbient = true;

  const { screen } = require('electron');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const mb = mainWindow.getBounds();

  const orbSize = 160;
  const orbX = width - orbSize - 24;
  const orbY = height - 220 - 24; /* 220 = orb(160) + strip(56) */

  orbWindow = new BrowserWindow({
    width: orbSize, height: 220,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    x: orbX, y: orbY,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    }
  });

  orbWindow.loadFile(path.join(__dirname, 'renderer', 'ambient.html'));
  orbWindow.webContents.on('did-finish-load', () => {
    orbWindow?.show();
    orbWindow?.setIgnoreMouseEvents(false);
  });
  orbWindow.on('closed', () => { orbWindow = null; });

  mainWindow.hide();
  workspaceWin?.hide();
}

function exitAmbient() {
  if (!mainWindow) return;
  isAmbient = false;
  orbWindow?.close();
  orbWindow = null;
  mainWindow.show();
  mainWindow.focus();
  workspaceWin?.show();
}

// ── Shortcuts ────────────────────────────────────────────
function registerShortcuts() {
  globalShortcut.register('Alt+S', () => {
    if (!mainWindow) return;
    if (isAmbient) { exitAmbient(); mainWindow.show(); mainWindow.focus(); }
    else if (mainWindow.isVisible() && mainWindow.isFocused()) mainWindow.hide();
    else { mainWindow.show(); mainWindow.focus(); }
  });
  globalShortcut.register('Alt+E', () => mainWindow?.webContents.send('shortcut', 'toggle_screen'));
  globalShortcut.register('Alt+Z', () => isAmbient ? exitAmbient() : enterAmbient());
  globalShortcut.register('Alt+X', () => mainWindow?.webContents.send('shortcut', 'clear_chat'));
  globalShortcut.register('Alt+T', () => {
    if (isAmbient) exitAmbient();
    mainWindow?.show(); mainWindow?.focus();
    mainWindow?.webContents.send('shortcut', 'focus_input');
  });
  globalShortcut.register('Alt+W', () => toggleWorkspace());
}

// ── IPC ──────────────────────────────────────────────────
ipcMain.handle('get-config', () => {
  const p = getConfigPath();
  return fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : null;
});
ipcMain.handle('save-config', (_, c) => {
  const p = getConfigPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(c, null, 2));
  return true;
});
ipcMain.handle('backend-url', () => `ws://127.0.0.1:${BACKEND_PORT}/ws`);
ipcMain.handle('reset-config', () => {
  const p = getConfigPath();
  if (fs.existsSync(p)) fs.unlinkSync(p);
  return true;
});
ipcMain.handle('reset-all', async () => {
  try {
    // 1. Tell backend to wipe its config + memory DB + in-memory state
    const r = await fetch(`http://127.0.0.1:${BACKEND_PORT}/reset`, { method: 'POST' });
    const data = await r.json();

    // 2. Also wipe Electron-side config (userData/config.json)
    const p = getConfigPath();
    if (fs.existsSync(p)) fs.unlinkSync(p);

    // 3. Reload main window to onboarding
    if (mainWindow && !mainWindow.isDestroyed()) {
      const onboardPath = path.join(__dirname, 'renderer', 'onboarding.html');
      mainWindow.loadFile(onboardPath);
    }

    // 4. Close workspace if open
    workspaceWin?.close();

    console.log('[SOUL] Full reset complete:', data);
    return { success: true };
  } catch (e) {
    console.error('[SOUL] reset-all failed:', e.message);
    return { success: false, error: e.message };
  }
});
ipcMain.handle('open-file-dialog', async () => {
  const { dialog } = require('electron');
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    title: 'Select File'
  });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.on('window-close',    () => mainWindow?.hide());
ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('open-external',   (_, url) => shell.openExternal(url));
ipcMain.on('set-ambient',     (_, on) => on ? enterAmbient() : exitAmbient());
ipcMain.on('toggle-workspace', () => toggleWorkspace());
ipcMain.on('exit-ambient',     () => exitAmbient());
ipcMain.on('close-workspace',  () => workspaceWin?.close());

// Orb manual drag handlers
let dragOffset = { x: 0, y: 0 };
ipcMain.on('orb-drag-start', (_, data) => {
  if (!orbWindow || orbWindow.isDestroyed()) return;
  const [wx, wy] = orbWindow.getPosition();
  dragOffset = { x: data.x - wx, y: data.y - wy };
});
ipcMain.on('orb-drag-move', (_, data) => {
  if (!orbWindow || orbWindow.isDestroyed()) return;
  orbWindow.setPosition(data.x - dragOffset.x, data.y - dragOffset.y, false);
});
ipcMain.on('orb-drag-end', () => { dragOffset = { x: 0, y: 0 }; });

// Relay main window events → orb
ipcMain.on('orb-event', (_, data) => {
  orbWindow?.webContents.send('ambient-state', data);
});

// Orb resize
ipcMain.on('orb-resize', (_, w, h) => {
  if (!orbWindow || orbWindow.isDestroyed()) return;
  const bounds = orbWindow.getBounds();
  orbWindow.setBounds({ x: bounds.x, y: bounds.y, width: w, height: h }, false);
});

// Orb context/action handlers
ipcMain.on('orb-context', (_, action) => {
  if (!orbWindow || orbWindow.isDestroyed()) return;
  const b = orbWindow.getBounds();
  if (action === 'open' || action === 'dblclick') {
    exitAmbient();
  } else if (action === 'workspace') {
    exitAmbient();
    setTimeout(() => toggleWorkspace(), 180);
  } else if (action === 'exit') {
    exitAmbient();
  } else if (action === 'screenshot') {
    mainWindow?.webContents.send('shortcut', 'screenshot');
  } else if (action === 'hover-expand') {
    orbWindow.setBounds({ x: b.x, y: b.y, width: 160, height: 220 }, false);
  } else if (action === 'hover-collapse') {
    orbWindow.setBounds({ x: b.x, y: b.y, width: 160, height: 220 }, false);
  } else if (action === 'close-menu') {
    orbWindow.setBounds({ x: b.x, y: b.y, width: 160, height: 220 }, false);
  }
});

// Relay workspace events
ipcMain.on('workspace-event', (_, data) => {
  workspaceWin?.webContents.send('workspace-event', data);
});

// workspace → main (single handler — deduplicated from v6 which had two)
ipcMain.on('workspace-to-main', (_, data) => {
  if (data.type === 'open_external' && data.url) {
    shell.openExternal(data.url);
    return;
  }
  if (data.type === 'theme_change' && data.theme) {
    mainWindow?.webContents.send('shortcut', `theme:${data.theme}`);
    mainWindow?.webContents.send('workspace-to-main', data);
    orbWindow?.webContents.send('ambient-state', { theme: data.theme });
    return;
  }
  mainWindow?.webContents.send('workspace-to-main', data);
});

// ── Lifecycle ────────────────────────────────────────────
app.whenReady().then(async () => {
  console.log('[SOUL] userData:', app.getPath('userData'));
  console.log('[SOUL] packaged:', app.isPackaged);
  await startBackend();
  createMainWindow();
  registerShortcuts();
  app.on('activate', () => { if (!mainWindow) createMainWindow(); });
});

app.on('will-quit',    () => { globalShortcut.unregisterAll(); stopBackend(); });
app.on('before-quit',  () => stopBackend());

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}
