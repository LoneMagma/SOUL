/**
 * SOUL — Electron Main Process
 */

const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage,
        shell, globalShortcut } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const fs = require('fs');
const net = require('net');

const BACKEND_PORT = 8765;

// CONFIG_PATH must be resolved AFTER app is ready — NOT at module level
function getConfigPath() {
  return path.join(app.getPath('userData'), 'config.json');
}

let mainWindow = null;
let tray = null;
let backendProcess = null;
let isAmbient = false;

// ── Port utils ────────────────────────────────
function isPortInUse(port) {
  return new Promise((resolve) => {
    const t = net.createConnection({ port, host: '127.0.0.1' });
    t.once('connect', () => { t.destroy(); resolve(true); });
    t.once('error', () => resolve(false));
  });
}
function waitForPort(port, maxAttempts = 24) {
  return new Promise((resolve) => {
    let n = 0;
    const iv = setInterval(async () => {
      n++;
      if (await isPortInUse(port)) { clearInterval(iv); resolve(true); }
      else if (n >= maxAttempts) { clearInterval(iv); resolve(false); }
    }, 500);
  });
}

// ── Backend ───────────────────────────────────
async function startBackend() {
  if (await isPortInUse(BACKEND_PORT)) {
    console.log('[SOUL] Backend already running, attaching...');
    return true;
  }

  const py = process.platform === 'win32' ? 'python' : 'python3';
  const backendPath = path.join(__dirname, '..', 'backend', 'main.py');
  console.log('[SOUL] Starting backend:', backendPath);

  backendProcess = spawn(py, [backendPath], {
    env: { ...process.env, GROQ_API_KEY: loadEnvKey('GROQ_API_KEY'), PORCUPINE_KEY: loadEnvKey('PORCUPINE_KEY') },
    cwd: path.join(__dirname, '..', 'backend')
  });

  backendProcess.stdout.on('data', d => console.log(`[Backend] ${d.toString().trim()}`));
  backendProcess.stderr.on('data', d => console.log(`[Backend] ${d.toString().trim()}`));
  backendProcess.on('close', code => {
    if (code !== 0 && mainWindow)
      mainWindow.webContents.send('backend-error', 'Check your .env GROQ_API_KEY at https://console.groq.com');
  });

  return await waitForPort(BACKEND_PORT);
}

function loadEnvKey(key) {
  // Check both possible .env locations
  const locations = [
    path.join(__dirname, '..', '.env'),
    path.join(__dirname, '.env'),
  ];
  for (const p of locations) {
    if (fs.existsSync(p)) {
      const m = fs.readFileSync(p, 'utf8').match(new RegExp(`^${key}=(.+)$`, 'm'));
      if (m) return m[1].trim();
    }
  }
  return process.env[key] || '';
}

function stopBackend() {
  if (backendProcess) { backendProcess.kill(); backendProcess = null; }
}

// ── Window ────────────────────────────────────
function createMainWindow() {
  // Resolve config path AFTER app ready
  const configPath = getConfigPath();
  const isFirstRun = !fs.existsSync(configPath);
  const htmlFile = isFirstRun ? 'onboarding.html' : 'index.html';
  const htmlPath = path.join(__dirname, 'renderer', htmlFile);

  console.log('[SOUL] Config path:', configPath);
  console.log('[SOUL] Loading:', htmlPath);
  console.log('[SOUL] File exists:', fs.existsSync(htmlPath));

  const { screen } = require('electron');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  mainWindow = new BrowserWindow({
    width: 400,
    height: 640,
    frame: false,
    transparent: false, // set dynamically for ambient
    backgroundColor: '#07090e',
    alwaysOnTop: false,
    resizable: false,
    show: false,
    x: width - 420,
    y: height - 660,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      devTools: true,
    }
  });

  // Load the file
  mainWindow.loadFile(htmlPath).catch(err => {
    console.error('[SOUL] loadFile failed:', err);
    // Fallback: try loading index.html directly
    const fallback = path.join(__dirname, 'renderer', 'index.html');
    console.log('[SOUL] Trying fallback:', fallback);
    mainWindow.loadFile(fallback).catch(e => console.error('[SOUL] Fallback also failed:', e));
  });

  // Log load errors
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDesc, validatedURL) => {
    console.error(`[SOUL] Page failed to load: ${errorCode} ${errorDesc} — ${validatedURL}`);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[SOUL] Page loaded successfully');
    mainWindow.show();
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

function createTray() {
  try {
    tray = new Tray(nativeImage.createEmpty());
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Show SOUL', click: () => { mainWindow?.show(); exitAmbient(); } },
      { label: 'Ambient', click: () => enterAmbient() },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() }
    ]));
    tray.setToolTip('SOUL');
    tray.on('click', () => mainWindow?.isVisible() ? mainWindow.hide() : mainWindow?.show());
  } catch(e) { console.log('[SOUL] Tray skipped:', e.message); }
}

// ── Ambient ───────────────────────────────────
function enterAmbient() {
  if (!mainWindow) return;
  isAmbient = true;
  mainWindow.setSize(72, 72);
  mainWindow.setAlwaysOnTop(true, 'floating');
  mainWindow.setSkipTaskbar(true);
  mainWindow.setBackgroundColor('#00000000');
  mainWindow.webContents.send('ambient-change', true);
}
function exitAmbient() {
  if (!mainWindow) return;
  isAmbient = false;
  mainWindow.setSize(400, 640);
  mainWindow.setAlwaysOnTop(false);
  mainWindow.setSkipTaskbar(false);
  mainWindow.setBackgroundColor('#07090e');
  mainWindow.webContents.send('ambient-change', false);
}

// ── Shortcuts ─────────────────────────────────
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
}

// ── IPC ───────────────────────────────────────
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
ipcMain.on('window-close', () => mainWindow?.hide());
ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('open-external', (_, url) => shell.openExternal(url));
ipcMain.on('set-ambient', (_, on) => on ? enterAmbient() : exitAmbient());
ipcMain.handle('open-file-dialog', async () => {
  const { dialog } = require('electron');
  const r = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'] });
  return r.canceled ? null : r.filePaths[0];
});

// ── Lifecycle ─────────────────────────────────
app.whenReady().then(async () => {
  console.log('[SOUL] App ready, userData:', app.getPath('userData'));
  await startBackend();
  createMainWindow();
  createTray();
  registerShortcuts();
  app.on('activate', () => { if (!mainWindow) createMainWindow(); });
});

app.on('will-quit', () => { globalShortcut.unregisterAll(); stopBackend(); });
app.on('before-quit', () => stopBackend());

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); }
  });
}
