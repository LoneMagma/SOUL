const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('pacify', {
  // Config
  getConfig:      ()  => ipcRenderer.invoke('get-config'),
  saveConfig:     (c) => ipcRenderer.invoke('save-config', c),
  resetConfig:    ()  => ipcRenderer.invoke('reset-config'),
  resetAll:       ()  => ipcRenderer.invoke('reset-all'),
  // Window
  getBackendUrl:  ()  => ipcRenderer.invoke('backend-url'),
  close:          ()  => ipcRenderer.send('window-close'),
  minimize:       ()  => ipcRenderer.send('window-minimize'),
  setAmbient:     (on)=> ipcRenderer.send('set-ambient', on),
  openFileDialog: ()  => ipcRenderer.invoke('open-file-dialog'),
  openExternal:   (u) => ipcRenderer.send('open-external', u),
  // Workspace
  toggleWorkspace:()  => ipcRenderer.send('toggle-workspace'),
  closeWorkspace: ()  => ipcRenderer.send('close-workspace'),
  sendWorkspace:  (d) => ipcRenderer.send('workspace-event', d),
  sendToMain:     (d) => ipcRenderer.send('workspace-to-main', d),
  // Events in
  onBackendError:   (cb) => ipcRenderer.on('backend-error',    (_, m) => cb(m)),
  onAmbientChange:  (cb) => ipcRenderer.on('ambient-change',   (_, v) => cb(v)),
  onShortcut:       (cb) => ipcRenderer.on('shortcut',         (_, k) => cb(k)),
  onWorkspaceEvent: (cb) => ipcRenderer.on('workspace-event',  (_, d) => cb(d)),
  onWorkspaceToMain:(cb) => ipcRenderer.on('workspace-to-main',(_, d) => cb(d)),
  onWorkspaceClosed:(cb) => ipcRenderer.on('workspace-closed', ()     => cb()),
  onWorkspaceOpened:(cb) => ipcRenderer.on('workspace-opened', ()     => cb()),
  onBackendLog:     (cb) => ipcRenderer.on('backend-log',      (_, t) => cb(t)),
  exitAmbient:      ()  => ipcRenderer.send('exit-ambient'),
  onAmbientState:   (cb) => ipcRenderer.on('ambient-state',    (_, d) => cb(d)),
  sendToOrb:        (d)  => ipcRenderer.send('orb-event', d),
  ipc: {
    send: (channel, data) => {
      const allowed = ['orb-drag-start','orb-drag-move','orb-drag-end'];
      if (allowed.includes(channel)) ipcRenderer.send(channel, data);
    }
  },
  orbResize:        (w, h) => ipcRenderer.send('orb-resize', w, h),
  orbContextMenu:   (action) => ipcRenderer.send('orb-context', action),
});
