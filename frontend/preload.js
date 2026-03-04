const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pacify', {
  getConfig: () => ipcRenderer.invoke('get-config'),
  saveConfig: (c) => ipcRenderer.invoke('save-config', c),
  getBackendUrl: () => ipcRenderer.invoke('backend-url'),
  close: () => ipcRenderer.send('window-close'),
  minimize: () => ipcRenderer.send('window-minimize'),
  setAmbient: (on) => ipcRenderer.send('set-ambient', on),
  openFileDialog: () => ipcRenderer.invoke('open-file-dialog'),
  openExternal: (url) => ipcRenderer.send('open-external', url),
  resetConfig: () => ipcRenderer.invoke('reset-config'),
  onBackendError: (cb) => ipcRenderer.on('backend-error', (_, m) => cb(m)),
  onAmbientChange: (cb) => ipcRenderer.on('ambient-change', (_, on) => cb(on)),
  onShortcut: (cb) => ipcRenderer.on('shortcut', (_, key) => cb(key)),
});
