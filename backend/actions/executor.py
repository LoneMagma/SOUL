"""
SOUL — Action Executor
Every action goes through confirmation. No exceptions.
Actions are Windows-first, reliable, no exotic dependencies.
"""

import asyncio
import os
import shutil
import subprocess
import platform
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict

WINDOWS = platform.system() == "Windows"


class PendingAction:
    def __init__(self, action_type: str, params: dict, display_text: str):
        self.action_type = action_type
        self.params = params
        self.display_text = display_text
        self.timestamp = datetime.now()
        self.id = f"{action_type}_{int(self.timestamp.timestamp()*1000)}"
        self.resolved = False
        self._event = asyncio.Event()
        self._accepted = False

    async def wait(self, timeout: int = 30) -> bool:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return self._accepted
        except asyncio.TimeoutError:
            self.resolved = True
            return False

    def accept(self):
        self._accepted = True
        self.resolved = True
        self._event.set()

    def reject(self):
        self._accepted = False
        self.resolved = True
        self._event.set()


# ── Action implementations ────────────────────

# Map common spoken names to actual Windows executables/commands
APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome",
    "google chrome": "chrome",
    "firefox": "firefox",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "spotify": "spotify",
    "discord": "discord",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "terminal": "wt",
    "windows terminal": "wt",
    "powershell": "powershell",
    "cmd": "cmd",
    "command prompt": "cmd",
    "settings": "ms-settings:",
    "control panel": "control",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "teams": "msteams",
    "zoom": "zoom",
    "vlc": "vlc",
    "snipping tool": "snippingtool",
    "screenshot": "snippingtool",
    "camera": "microsoft.windows.camera:",
    "clock": "ms-clock:",
    "maps": "bingmaps:",
    "weather": "bingweather:",
    "store": "ms-windows-store:",
}

async def _open_app(p: dict) -> str:
    app = p.get("app_name", "").strip()
    if not app:
        raise ValueError("No app specified")

    if not WINDOWS:
        subprocess.Popen(["open", "-a", app] if platform.system() == "Darwin" else [app])
        return f"Opened {app}"

    # Resolve alias
    resolved = APP_ALIASES.get(app.lower(), app)

    # Try in order: ms-uri, direct exe, start command, shell execute
    errors = []

    # 1. MS URI schemes (settings, store, etc.)
    if resolved.endswith(":"):
        subprocess.Popen(f'start "" "{resolved}"', shell=True)
        return f"Opened {app}"

    # 2. Direct subprocess with common exe paths
    search_names = [resolved, resolved + ".exe"]
    for name in search_names:
        try:
            result = subprocess.run(
                f'start "" "{name}"',
                shell=True, capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return f"Opened {app}"
        except Exception as e:
            errors.append(str(e))

    # 3. Search Program Files
    prog_dirs = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    for prog_dir in prog_dirs:
        if not prog_dir:
            continue
        # Search 2 levels deep
        for root, dirs, files in os.walk(prog_dir):
            depth = root.replace(prog_dir, "").count(os.sep)
            if depth > 2:
                del dirs[:]
                continue
            for f in files:
                if f.lower() in [resolved.lower(), resolved.lower() + ".exe",
                                  app.lower() + ".exe"]:
                    try:
                        subprocess.Popen([os.path.join(root, f)], shell=True)
                        return f"Opened {app}"
                    except Exception as e:
                        errors.append(str(e))

    # 4. Last resort: ShellExecute via PowerShell
    try:
        subprocess.Popen(
            ['powershell', '-Command', f'Start-Process "{resolved}"'],
            capture_output=True
        )
        return f"Opened {app}"
    except Exception as e:
        errors.append(str(e))

    raise RuntimeError(f"Couldn't find or launch '{app}'. Try opening it manually.")


async def _close_app(p: dict) -> str:
    name = p.get("app_name", "").strip()
    if not name:
        raise ValueError("No app specified")
    if WINDOWS:
        # Kill by window title or process name
        subprocess.run(f'taskkill /F /IM "{name}.exe"', shell=True, capture_output=True)
        subprocess.run(f'taskkill /F /FI "WINDOWTITLE eq {name}*"', shell=True, capture_output=True)
    else:
        subprocess.run(["pkill", "-f", name], capture_output=True)
    return f"Closed {name}"


async def _web_search(p: dict) -> str:
    query = p.get("query", "").strip()
    if not query:
        raise ValueError("No search query")
    url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
    webbrowser.open(url)
    return f"Searching: {query}"


async def _open_url(p: dict) -> str:
    url = p.get("url", "").strip()
    if not url:
        raise ValueError("No URL")
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url}"


async def _move_file(p: dict) -> str:
    src = Path(p.get("source", ""))
    dst = Path(p.get("destination", ""))
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src}")
    shutil.move(str(src), str(dst))
    return f"Moved {src.name} → {dst}"


async def _copy_file(p: dict) -> str:
    src = Path(p.get("source", ""))
    dst = Path(p.get("destination", ""))
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src}")
    shutil.copy2(str(src), str(dst))
    return f"Copied {src.name} → {dst}"


async def _take_screenshot(p: dict) -> str:
    try:
        from PIL import ImageGrab
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = p.get("save_path", str(Path.home() / "Desktop" / f"screenshot_{ts}.png"))
        img = ImageGrab.grab()
        img.save(save_path)
        # Open folder containing it
        if WINDOWS:
            subprocess.Popen(f'explorer /select,"{save_path}"', shell=True)
        return f"Screenshot saved to {save_path}"
    except Exception as e:
        raise RuntimeError(f"Screenshot failed: {e}")


async def _set_volume(p: dict) -> str:
    level = max(0, min(100, int(p.get("level", 50))))
    if WINDOWS:
        # Use PowerShell — zero extra deps
        ps_cmd = f"""
        $obj = New-Object -ComObject WScript.Shell
        $vol = [math]::Round({level} / 2)
        for ($i=0; $i -lt 50; $i++) {{ $obj.SendKeys([char]174) }}
        for ($i=0; $i -lt $vol; $i++) {{ $obj.SendKeys([char]175) }}
        """
        subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
    elif platform.system() == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
    else:
        subprocess.run(["amixer", "sset", "Master", f"{level}%"])
    return f"Volume → {level}%"


async def _play_media(p: dict) -> str:
    path = p.get("file_path", "")
    if path and Path(path).exists():
        if WINDOWS:
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return f"Playing {Path(path).name}"
    raise ValueError("File not found or not specified")


async def _show_notification(p: dict) -> str:
    title = p.get("title", "SOUL")
    message = p.get("message", "")
    if WINDOWS:
        # Pure PowerShell toast — no deps
        ps = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $template.GetElementsByTagName('text')[0].InnerText = '{title}'
        $template.GetElementsByTagName('text')[1].InnerText = '{message}'
        $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('SOUL').Show($toast)
        """
        subprocess.Popen(["powershell", "-Command", ps], capture_output=True)
    return f"Notification shown: {title}"


async def _open_folder(p: dict) -> str:
    path = p.get("path", str(Path.home()))
    if WINDOWS:
        subprocess.Popen(f'explorer "{path}"', shell=True)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return f"Opened {path}"


REGISTRY: Dict[str, Callable] = {
    "open_app":          _open_app,
    "close_app":         _close_app,
    "web_search":        _web_search,
    "open_url":          _open_url,
    "move_file":         _move_file,
    "copy_file":         _copy_file,
    "take_screenshot":   _take_screenshot,
    "set_volume":        _set_volume,
    "play_media":        _play_media,
    "show_notification": _show_notification,
    "open_folder":       _open_folder,
    # Aliases the LLM might use
    "search":            _web_search,
    "screenshot":        _take_screenshot,
    "open":              _open_app,
    "volume":            _set_volume,
}


class ActionExecutor:
    def __init__(self, on_pending: Callable = None):
        self.on_pending = on_pending
        self._pending: Dict[str, PendingAction] = {}

    async def request(self, action_type: str, params: dict,
                      display_text: str, timeout: int = 30) -> dict:
        # Normalise type
        atype = action_type.lower().strip()

        if atype not in REGISTRY:
            return {
                "success": False,
                "error": f"I don't know how to do '{action_type}' yet.",
                "action_id": None
            }

        pending = PendingAction(atype, params, display_text)
        self._pending[pending.id] = pending

        if self.on_pending:
            self.on_pending(pending)

        accepted = await pending.wait(timeout)

        if not accepted:
            self._pending.pop(pending.id, None)
            return {"success": False, "cancelled": True,
                    "message": "Cancelled.", "action_id": pending.id}

        try:
            result = await REGISTRY[atype](params)
            self._pending.pop(pending.id, None)
            return {"success": True, "message": result, "action_id": pending.id}
        except Exception as e:
            self._pending.pop(pending.id, None)
            return {"success": False, "error": str(e), "action_id": pending.id}

    def confirm(self, action_id: str):
        if action_id in self._pending:
            self._pending[action_id].accept()

    def reject(self, action_id: str):
        if action_id in self._pending:
            self._pending[action_id].reject()

    @property
    def pending_actions(self) -> list:
        return [
            {"id": a.id, "type": a.action_type,
             "display_text": a.display_text,
             "timestamp": a.timestamp.isoformat()}
            for a in self._pending.values() if not a.resolved
        ]
