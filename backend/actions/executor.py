"""
SOUL — Action Executor v7
Auto-confirm for read-only actions. Full tier unlocks shell execution.
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

# Actions that never need confirmation — they only read or display
AUTO_CONFIRM = {
    # Info / read-only
    "get_system_info", "get_running_processes", "read_clipboard",
    "check_battery", "get_time", "get_weather_info", "show_notification",
    "read_file", "list_folder",
    # Window / input
    "focus_window", "media_control", "press_keys", "type_text",
    "toggle_screen_capture",
    # App control (safe — user asked for it)
    "open_app", "close_app", "open_folder", "open_url", "web_search",
    "open_file_in_app", "rename_file",
    # Media
    "play_media", "take_screenshot", "set_volume", "lock_screen",
    # Files (create/write — destructive but user-initiated)
    "create_file", "write_file",
    # Clipboard
    "copy_to_clipboard",
}

# Actions that require Full tier
FULL_TIER_ONLY = {
    "run_command", "delete_file", "write_file", "kill_process",
}


class PendingAction:
    def __init__(self, action_type: str, params: dict, display_text: str):
        self.action_type  = action_type
        self.params       = params
        self.display_text = display_text
        self.timestamp    = datetime.now()
        self.id           = f"{action_type}_{int(self.timestamp.timestamp()*1000)}"
        self.resolved     = False
        self._event       = asyncio.Event()
        self._accepted    = False

    async def wait(self, timeout: int = 30) -> bool:
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return self._accepted
        except asyncio.TimeoutError:
            self.resolved = True
            return False

    def accept(self):
        self._accepted = True
        self.resolved  = True
        self._event.set()

    def reject(self):
        self._accepted = False
        self.resolved  = True
        self._event.set()


# ── App aliases ───────────────────────────────────────────────────────────
APP_ALIASES = {
    "notepad":              "notepad.exe",
    "calculator":           "calc.exe",
    "calc":                 "calc.exe",
    "paint":                "mspaint.exe",
    "file explorer":        "explorer.exe",
    "explorer":             "explorer.exe",
    "files":                "explorer.exe",
    "task manager":         "taskmgr.exe",
    "chrome":               "chrome",
    "google chrome":        "chrome",
    "firefox":              "firefox",
    "edge":                 "msedge",
    "microsoft edge":       "msedge",
    "spotify":              "Spotify",
    "discord":              "Discord",
    "discord app":          "Discord",
    "vs code":              "code",
    "vscode":               "code",
    "visual studio code":   "code",
    "terminal":             "wt",
    "windows terminal":     "wt",
    "powershell":           "powershell",
    "cmd":                  "cmd",
    "command prompt":       "cmd",
    "settings":             "ms-settings:",
    "windows settings":     "ms-settings:",
    "control panel":        "control",
    "word":                 "winword",
    "excel":                "excel",
    "powerpoint":           "powerpnt",
    "outlook":              "outlook",
    "teams":                "msteams",
    "zoom":                 "zoom",
    "vlc":                  "vlc",
    "snipping tool":        "snippingtool",
    "snip":                 "snippingtool",
    "camera":               "microsoft.windows.camera:",
    "clock":                "ms-clock:",
    "maps":                 "bingmaps:",
    "store":                "ms-windows-store:",
    "photos":               "ms-photos:",
    "mail":                 "outlookmail:",
    "calendar":             "outlookcal:",
    "onenote":              "onenote:",
    "notepad++":            "notepad++",
    "sublime":              "sublime_text",
    "steam":                "steam",
    "obs":                  "obs64",
    "slack":                "slack",
    "notion":               "notion",
    "figma":                "figma",
    "postman":              "postman",
    "cursor":               "cursor",
    "riot":                 "riot client",
    "riot client":          "riot client",
    "valorant":             "valorant",
    "league":               "league",
    "league of legends":    "league",
    "lol":                  "league",
    "msi afterburner":      "msi afterburner",
    "afterburner":          "MSIAfterburner",
    "msi afterburner":      "MSIAfterburner",
    "msi":                  "MSIAfterburner",
    # Taskbar / system
    "taskbar":              "taskmgr.exe",
    "task bar":             "taskmgr.exe",
    "taskmgr":              "taskmgr.exe",
    "file manager":         "explorer.exe",
    "filemanager":          "explorer.exe",
    "my computer":          "explorer.exe",
    "this pc":              "explorer.exe",
    # Browsers
    "browser":              "msedge",
    "brave":                "brave",
    # Gaming
    "riot":                 "RiotClientServices",
    "riot client":          "RiotClientServices",
    "valorant":             "VALORANT-Win64-Shipping",
    "league":               "LeagueClient",
    "league of legends":    "LeagueClient",
    "epic games":           "EpicGamesLauncher",
    "epic":                 "EpicGamesLauncher",
    "gta":                  "PlayGTAV",
    # Productivity / misc
    "cursor":               "cursor",
    "winrar":               "winrar",
    "7zip":                 "7zFM",
    "7-zip":                "7zFM",
    "ccleaner":             "CCleaner64",
    "everything":           "Everything",
    "process explorer":     "procexp64",
    "hwinfo":               "HWiNFO64",
    "cpu-z":                "cpuz",
    "gpu-z":                "GPU-Z",
}


# ──────────────────────────────────────────────────────────────────────────
# SOUL WORKDESK — Virtual Desktop scaffold (Windows 10/11)
# SOUL operates on her own virtual desktop so actions don't disrupt user work.
# Falls back silently on non-Windows or if VirtualDesktop helper not found.
# ──────────────────────────────────────────────────────────────────────────

_workdesk_index: int = -1
_WORKDESK_NAME  = "SOUL Workdesk"


def _workdesk_available() -> bool:
    """True if the community VirtualDesktop.exe helper is on PATH."""
    if not WINDOWS:
        return False
    try:
        r = subprocess.run(["where", "VirtualDesktop.exe"],
                           capture_output=True, text=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


def init_workdesk() -> int:
    """
    Create (or find) SOUL's virtual desktop.
    Returns the 0-based desktop index, or -1 if unavailable.
    Idempotent — safe to call multiple times.
    """
    global _workdesk_index
    if _workdesk_index >= 0:
        return _workdesk_index
    if not _workdesk_available():
        return -1
    try:
        r = subprocess.run(["VirtualDesktop.exe", "/list"],
                           capture_output=True, text=True, timeout=5)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        for i, line in enumerate(lines):
            if _WORKDESK_NAME.lower() in line.lower():
                _workdesk_index = i
                print(f"[SOUL] Workdesk found at index {i}")
                return _workdesk_index
        # Not found — create
        subprocess.run(["VirtualDesktop.exe", f"/new:{_WORKDESK_NAME}"],
                       capture_output=True, timeout=5)
        r2 = subprocess.run(["VirtualDesktop.exe", "/list"],
                            capture_output=True, text=True, timeout=5)
        lines2 = [l.strip() for l in r2.stdout.splitlines() if l.strip()]
        for i, line in enumerate(lines2):
            if _WORKDESK_NAME.lower() in line.lower():
                _workdesk_index = i
                print(f"[SOUL] Workdesk created at index {i}")
                return _workdesk_index
    except Exception as e:
        print(f"[SOUL] Workdesk init failed: {e}")
    return -1


def _move_to_workdesk(pid: int) -> bool:
    """Move a process's main window to SOUL Workdesk."""
    if _workdesk_index < 0:
        return False
    try:
        subprocess.run(["VirtualDesktop.exe", f"/process:{pid}",
                        f"/move:{_workdesk_index}"],
                       capture_output=True, timeout=4)
        return True
    except Exception:
        return False


# ── Actions ───────────────────────────────────────────────────────────────

async def _open_app(p: dict) -> str:
    app = p.get("app_name", "").strip()
    if not app:
        raise ValueError("No app name provided")

    if not WINDOWS:
        subprocess.Popen(["open", "-a", app] if platform.system() == "Darwin" else [app])
        return f"Opened {app}"

    key      = app.lower().strip()
    resolved = APP_ALIASES.get(key, app)
    print(f"[SOUL] open_app: '{app}' -> '{resolved}'")

    # ── Check if already running — avoid spawning duplicate instances ─────────
    # Single-instance apps (Notepad, Spotify, etc.) should be focused, not re-spawned.
    _SINGLE_INSTANCE = {
        "notepad", "notepad.exe", "spotify", "discord", "discord.exe",
        "taskmgr", "taskmgr.exe", "task manager",
    }
    if WINDOWS and (key in _SINGLE_INSTANCE or resolved.lower().rstrip('.exe') in _SINGLE_INSTANCE):
        import psutil as _psu
        _exe_stem = resolved.lower().replace('.exe', '')
        for _proc in _psu.process_iter(['name', 'status']):
            try:
                if _proc.info['name'] and _proc.info['name'].lower().replace('.exe','') == _exe_stem:
                    # Already running — try focus instead
                    _focus_ps = f"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class BringFwd {{ [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n); }}
"@
$p = Get-Process -Id {_proc.pid} -ErrorAction SilentlyContinue
if ($p -and $p.MainWindowHandle -ne 0) {{ [BringFwd]::ShowWindow($p.MainWindowHandle, 9) | Out-Null; [BringFwd]::SetForegroundWindow($p.MainWindowHandle) | Out-Null }}
"""
                    subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                                    "-Command", _focus_ps], capture_output=True, timeout=5)
                    return f"{app} already open — brought to front"
            except Exception:
                pass

    # ── taskmgr special case: launch elevated via PowerShell ─────────────────
    if WINDOWS and resolved.lower() in ("taskmgr.exe", "taskmgr"):
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
             "-Command", "Start-Process taskmgr.exe -Verb RunAs"],
            capture_output=True
        )
        await asyncio.sleep(0.6)
        return "Opening Task Manager (elevated)"

    # 0. os.startfile — most reliable on Windows (uses ShellExecute directly)
    if WINDOWS:
        try:
            os.startfile(resolved)
            await asyncio.sleep(0.8)
            return f"Opened {app}"
        except Exception:
            pass  # fall through to other methods

    # 1. URI scheme (ms-settings:, spotify:, etc.)
    if ":" in resolved and not resolved.endswith(".exe"):
        subprocess.Popen(f'start "" "{resolved}"', shell=True)
        return f"Opened {app}"

    # 2. `where` command — finds anything on PATH
    try:
        r = subprocess.run(["where", resolved], capture_output=True, text=True, timeout=4)
        if r.returncode == 0:
            exe = r.stdout.strip().splitlines()[0]
            subprocess.Popen([exe])
            print(f"[SOUL] found via where: {exe}")
            return f"Opened {app}"
    except Exception:
        pass

    # 3. PowerShell Start-Process (handles UWP + PATH apps)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f'Start-Process "{resolved}"'],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            return f"Opened {app}"
    except Exception as e:
        print(f"[SOUL] PS launch fail: {e}")

    # 4. Direct known install paths for common apps
    local   = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    pf      = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86    = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    KNOWN_PATHS = {
        "discord":   [
            os.path.join(local, "Discord", "Update.exe"),
            # find latest app-x.y.z folder
        ],
        "spotify":   [
            os.path.join(appdata, "Spotify", "Spotify.exe"),
            os.path.join(local,   "Microsoft", "WindowsApps", "Spotify.exe"),
        ],
        "steam":     [os.path.join(pf86, "Steam", "steam.exe"),
                      os.path.join(pf,   "Steam", "steam.exe")],
        "slack":     [os.path.join(local, "slack", "slack.exe")],
        "zoom":      [os.path.join(appdata, "Zoom", "bin", "Zoom.exe")],
        "teams":     [os.path.join(local, "Microsoft", "Teams", "current", "Teams.exe"),
                      os.path.join(appdata, "Microsoft", "Teams", "current", "Teams.exe")],
        "notion":    [os.path.join(local, "Programs", "Notion", "Notion.exe")],
        "figma":     [os.path.join(local, "Figma", "Figma.exe")],
        "postman":   [os.path.join(local, "Postman", "Postman.exe")],
        "obs":       [os.path.join(pf,   "obs-studio", "bin", "64bit", "obs64.exe"),
                      os.path.join(pf86, "obs-studio", "bin", "64bit", "obs64.exe")],
        "cursor":    [os.path.join(local, "Programs", "cursor", "Cursor.exe")],
        "riot client": [
            os.path.join(pf, "Riot Games", "Riot Client", "RiotClientServices.exe"),
            os.path.join(pf86, "Riot Games", "Riot Client", "RiotClientServices.exe"),
            os.path.join(local, "Riot Games", "Riot Client", "RiotClientServices.exe"),
        ],
        "valorant":  [
            os.path.join(pf, "Riot Games", "VALORANT", "live", "VALORANT.exe"),
            os.path.join(pf86, "Riot Games", "VALORANT", "live", "VALORANT.exe"),
        ],
        "league":    [
            os.path.join(pf, "Riot Games", "League of Legends", "LeagueClient.exe"),
            os.path.join(pf86, "Riot Games", "League of Legends", "LeagueClient.exe"),
        ],
        "msi afterburner": [
            os.path.join(pf86, "MSI Afterburner", "MSIAfterburner.exe"),
            os.path.join(pf,   "MSI Afterburner", "MSIAfterburner.exe"),
        ],
        "whatsapp":  [os.path.join(local, "WhatsApp", "WhatsApp.exe"),
                      os.path.join(appdata, "WhatsApp", "WhatsApp.exe")],
        "telegram":  [os.path.join(appdata, "Telegram Desktop", "Telegram.exe")],
        "vlc":       [os.path.join(pf,   "VideoLAN", "VLC", "vlc.exe"),
                      os.path.join(pf86, "VideoLAN", "VLC", "vlc.exe")],
    }

    if key in KNOWN_PATHS:
        for path_try in KNOWN_PATHS[key]:
            if os.path.exists(path_try):
                if key == "discord":
                    subprocess.Popen([path_try, "--processStart", "Discord.exe"])
                else:
                    subprocess.Popen([path_try])
                print(f"[SOUL] found via known path: {path_try}")
                return f"Opened {app}"

    # 5. Walk Program Files trees (2 levels deep)
    search_names = {key, key+".exe", resolved.lower(), resolved.lower()+".exe"}
    for base in [pf, pf86, os.path.join(local, "Programs")]:
        if not base or not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            depth = root.replace(base, "").count(os.sep)
            if depth > 2:
                del dirs[:]
                continue
            for fname in files:
                if fname.lower() in search_names:
                    full = os.path.join(root, fname)
                    subprocess.Popen([full])
                    return f"Opened {app}"

    # 6. cmd start as last resort
    subprocess.Popen(f'start "" "{resolved}"', shell=True)
    await asyncio.sleep(0.8)
    return f"Opened {app} (via start)"


async def _close_app(p: dict) -> str:
    name = p.get("app_name", "").strip()
    if not name:
        raise ValueError("No app specified")
    killed = False
    if WINDOWS:
        # Try by exe name
        r1 = subprocess.run(f'taskkill /F /IM "{name}.exe"',
                            shell=True, capture_output=True)
        r2 = subprocess.run(f'taskkill /F /IM "{name}"',
                            shell=True, capture_output=True)
        # Try by window title
        r3 = subprocess.run(f'taskkill /F /FI "WINDOWTITLE eq {name}*"',
                            shell=True, capture_output=True)
        killed = any(r.returncode == 0 for r in [r1, r2, r3])
    else:
        r = subprocess.run(["pkill", "-f", name], capture_output=True)
        killed = r.returncode == 0
    if not killed:
        raise RuntimeError(f"{name} doesn't appear to be running")
    return f"Closed {name}"


async def _kill_process(p: dict) -> str:
    name = p.get("process_name", p.get("app_name", "")).strip()
    pid  = p.get("pid")
    if pid:
        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        return f"Killed PID {pid}"
    if name:
        subprocess.run(f'taskkill /F /IM "{name}"', shell=True, capture_output=True)
        return f"Killed {name}"
    raise ValueError("Specify process_name or pid")


async def _get_running_processes(p: dict) -> str:
    if WINDOWS:
        r = subprocess.run(
            ["powershell", "-Command",
             "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name,CPU,WorkingSet | Format-Table -AutoSize"],
            capture_output=True, text=True, timeout=8
        )
        return r.stdout.strip() or "No process data"
    else:
        r = subprocess.run(["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True)
        lines = r.stdout.strip().split("\n")[:16]
        return "\n".join(lines)


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


async def _take_screenshot(p: dict) -> str:
    from PIL import ImageGrab
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = p.get("save_path",
                 str(Path.home() / "Desktop" / f"screenshot_{ts}.png"))
    img  = ImageGrab.grab()
    img.save(path)
    if WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"', shell=True)
    return f"Screenshot saved: {path}"


async def _set_volume(p: dict) -> str:
    level = max(0, min(100, int(p.get("level", 50))))
    if WINDOWS:
        ps = (f"$obj=New-Object -ComObject WScript.Shell;"
              f"for($i=0;$i-lt50;$i++){{$obj.SendKeys([char]174)}};"
              f"$v=[math]::Round({level}/2);"
              f"for($i=0;$i-lt$v;$i++){{$obj.SendKeys([char]175)}}")
        subprocess.run(["powershell", "-Command", ps],
                       capture_output=True, timeout=5)
    elif platform.system() == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
    else:
        subprocess.run(["amixer", "sset", "Master", f"{level}%"])
    return f"Volume set to {level}%"


async def _move_file(p: dict) -> str:
    src = Path(p.get("source", ""))
    dst = Path(p.get("destination", ""))
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src}")
    shutil.move(str(src), str(dst))
    return f"Moved {src.name} to {dst}"


async def _copy_file(p: dict) -> str:
    src = Path(p.get("source", ""))
    dst = Path(p.get("destination", ""))
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src}")
    shutil.copy2(str(src), str(dst))
    return f"Copied {src.name} to {dst}"


async def _delete_file(p: dict) -> str:
    path = Path(p.get("path", ""))
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    if path.is_dir():
        shutil.rmtree(str(path))
    else:
        path.unlink()
    return f"Deleted {path.name}"


async def _create_file(p: dict) -> str:
    path    = _resolve_path(p.get("path", ""))
    content = p.get("content", "")
    # Always ensure SOUL folder exists
    _soul = Path.home() / "Documents" / "SOUL"
    _soul.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"', shell=True)
    return f"Created {path.name} at {path}"


async def _read_file(p: dict) -> str:
    path = Path(p.get("path", ""))
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    if path.stat().st_size > 50_000:
        raise ValueError("File too large to read (>50KB)")
    return path.read_text(encoding="utf-8", errors="replace")[:2000]


async def _write_file(p: dict) -> str:
    path    = _resolve_path(p.get("path", ""))
    content = p.get("content", "")
    mode    = p.get("mode", "overwrite")  # overwrite | append
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with open(path, "a", encoding="utf-8") as f:
            f.write(content)
    else:
        path.write_text(content, encoding="utf-8")
    return f"Written to {path.name} at {path}"


async def _list_folder(p: dict) -> str:
    path  = Path(p.get("path", str(Path.home())))
    if not path.exists():
        raise FileNotFoundError(f"Not found: {path}")
    entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    lines   = []
    for e in entries[:40]:
        prefix = "[D]" if e.is_dir() else "[F]"
        lines.append(f"{prefix} {e.name}")
    return "\n".join(lines) or "Empty folder"


async def _rename_file(p: dict) -> str:
    src  = Path(p.get("path", ""))
    name = p.get("new_name", "").strip()
    if not src.exists():
        raise FileNotFoundError(f"Not found: {src}")
    dst = src.parent / name
    src.rename(dst)
    return f"Renamed to {name}"


async def _open_folder(p: dict) -> str:
    path = p.get("path", str(Path.home()))
    if WINDOWS:
        subprocess.Popen(f'explorer "{path}"', shell=True)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return f"Opened {path}"


async def _copy_to_clipboard(p: dict) -> str:
    text = p.get("text", "")
    if WINDOWS:
        subprocess.run(["powershell", "-Command",
                        f'Set-Clipboard "{text}"'],
                       capture_output=True)
    elif platform.system() == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode())
    else:
        subprocess.run(["xclip", "-selection", "clipboard"],
                       input=text.encode())
    return f"Copied to clipboard: {text[:40]}"


async def _read_clipboard(p: dict) -> str:
    if WINDOWS:
        r = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True
        )
        return r.stdout.strip() or "(empty)"
    elif platform.system() == "Darwin":
        r = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return r.stdout.strip() or "(empty)"
    else:
        r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                           capture_output=True, text=True)
        return r.stdout.strip() or "(empty)"


async def _get_system_info(p: dict) -> str:
    import psutil
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    lines = [
        f"CPU:  {cpu}%",
        f"RAM:  {ram.percent}% ({ram.used//1024//1024}MB / {ram.total//1024//1024}MB)",
        f"Disk: {disk.percent}% used ({disk.free//1024//1024//1024}GB free)",
    ]
    try:
        batt = psutil.sensors_battery()
        if batt:
            lines.append(f"Battery: {round(batt.percent)}% {'(charging)' if batt.power_plugged else ''}")
    except Exception:
        pass
    return "\n".join(lines)


async def _check_battery(p: dict) -> str:
    import psutil
    batt = psutil.sensors_battery()
    if not batt:
        return "No battery detected (desktop?)"
    status = "charging" if batt.power_plugged else "discharging"
    mins   = int(batt.secsleft / 60) if batt.secsleft > 0 else 0
    return (f"{round(batt.percent)}% — {status}"
            + (f", ~{mins}m remaining" if mins > 0 else ""))


async def _get_time(p: dict) -> str:
    now = datetime.now()
    return now.strftime("%A, %B %-d %Y — %-I:%M %p").replace("%-", "%#") if WINDOWS \
           else now.strftime("%A, %B %-d %Y — %-I:%M %p")


async def _show_notification(p: dict) -> str:
    title   = p.get("title", "SOUL")
    message = p.get("message", "")
    if WINDOWS:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType=WindowsRuntime] > $null\n"
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
            f"$template.GetElementsByTagName('text')[0].InnerText = '{title}'\n"
            f"$template.GetElementsByTagName('text')[1].InnerText = '{message}'\n"
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template)\n"
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('SOUL').Show($toast)"
        )
        subprocess.Popen(["powershell", "-Command", ps], capture_output=True)
    return f"Notification: {title}"


async def _lock_screen(p: dict) -> str:
    if WINDOWS:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
    elif platform.system() == "Darwin":
        subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/"
                        "Contents/Resources/CGSession", "-suspend"])
    return "Screen locked"


async def _empty_trash(p: dict) -> str:
    if WINDOWS:
        subprocess.run(
            ["powershell", "-Command",
             "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True
        )
    elif platform.system() == "Darwin":
        subprocess.run(["osascript", "-e",
                        'tell application "Finder" to empty trash'])
    return "Trash emptied"


async def _play_media(p: dict) -> str:
    path = p.get("file_path", p.get("uri", "")).strip()
    if not path:
        raise ValueError("No file_path or uri provided")
    # Spotify liked songs — open collection then focus window and press play
    if path in ("spotify:user:collection", "spotify:collection",
                "spotify://collection", "liked", "liked songs"):
        import asyncio as _asyncio
        if WINDOWS:
            # Launch liked songs URI and immediately queue a playback keypress
            ps = r"""
Start-Process "spotify://collection/tracks"
Start-Sleep -Seconds 2
Add-Type -AssemblyName Microsoft.VisualBasic
Add-Type @"
using System; using System.Runtime.InteropServices;
public class FW {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
$procs = @(Get-Process -Name Spotify -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
if ($procs.Count -gt 0) {
    $h = $procs[0].MainWindowHandle
    [FW]::ShowWindow($h, 9) | Out-Null
    [FW]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 800
    $wsh = New-Object -ComObject WScript.Shell
    $wsh.SendKeys(' ')
    Start-Sleep -Milliseconds 400
    $wsh.SendKeys(' ')
}
"""
            subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                           capture_output=True, timeout=15)
        else:
            webbrowser.open("spotify://collection/tracks")
            await _asyncio.sleep(3.0)
        return "Playing Spotify Liked Songs"
    # Other Spotify / media URI scheme
    if path.startswith("spotify:") or path.startswith("http"):
        webbrowser.open(path)
        return f"Opened media: {path}"
    fp = Path(path)
    if fp.exists():
        if WINDOWS:
            os.startfile(str(fp))
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(fp)])
        else:
            subprocess.Popen(["xdg-open", str(fp)])
        return f"Playing {fp.name}"
    # Try as URI anyway
    webbrowser.open(path)
    return f"Opened: {path}"


async def _run_command(p: dict) -> str:
    """Full tier only. Runs in cwd or specified path."""
    cmd  = p.get("command", "").strip()
    cwd  = p.get("cwd", str(Path.home()))
    if not cmd:
        raise ValueError("No command specified")
    r = subprocess.run(
        cmd, shell=True, capture_output=True, text=True,
        cwd=cwd, timeout=30
    )
    out = (r.stdout + r.stderr).strip()
    return out[:1500] or f"Command ran (exit {r.returncode})"


async def _focus_window(p: dict) -> str:
    """Bring a window to foreground, retry up to 3x until it lands."""
    title = p.get("title", "").strip()
    if not title:
        raise ValueError("No window title provided")
    if WINDOWS:
        # Retry loop: wait for window to exist then force focus
        for attempt in range(3):
            ps = f"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32 {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}}
"@
$procs = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{title}*' -and $_.MainWindowHandle -ne 0 }}
$proc = $procs | Select-Object -First 1
if ($proc) {{
    [W32]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
    [W32]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
    Start-Sleep -Milliseconds 200
    $fg = [W32]::GetForegroundWindow()
    if ($fg -eq $proc.MainWindowHandle) {{ Write-Output "ok" }} else {{ Write-Output "retry" }}
}} else {{ Write-Output "not_found" }}
"""
            r = subprocess.run(["powershell", "-Command", ps],
                                capture_output=True, text=True, timeout=8)
            out = r.stdout.strip()
            if out == "ok":
                return f"Focused: {title}"
            elif out == "not_found":
                if attempt < 2:
                    import asyncio as _asyncio2
                    await _asyncio2.sleep(1.0)  # window might still be loading
                    continue
                return f"Window '{title}' not found"
            else:
                import asyncio as _asyncio3
                await _asyncio3.sleep(0.6)
        return f"Focused: {title} (best effort)"
    return f"Focus not supported on this OS"


async def _type_text(p: dict) -> str:
    """Type text into a window. If window_title provided, re-focuses it first."""
    text         = p.get("text", "")
    window_title = p.get("window_title", "").strip()
    if not text:
        raise ValueError("No text to type")

    if WINDOWS:
        # Use clipboard-paste approach: works with ALL apps including Win11 Notepad.
        # SendKeys is unreliable for long text in modern Windows apps.
        # Strategy: Set-Clipboard + focus window + Ctrl+V

        # ── SOUL window exclusion guard ────────────────────────────────────────
        # Never type into SOUL's own chat input. If window_title is empty/None,
        # we must NOT fall back to "whatever has focus" because that is usually
        # SOUL's chat bar. Require an explicit target for blind paste.
        _SOUL_TITLES = {"soul", "thinkiee", "soul — device companion", "electron"}
        if not window_title:
            return ("type_text requires a window_title — no target specified. "
                    "Please open the app first and retry with window_title set.")
        if window_title.lower().strip() in _SOUL_TITLES:
            return "Refused: will not type into SOUL's own window."

        # Safely encode text for PowerShell here-string
        text_escaped = text.replace("'", "''")   # escape single quotes for PS

        if window_title:
            # Retry up to 5 times to find and focus the window before pasting.
            # This handles apps that are still loading when focus is attempted.
            ps = f"""
Add-Type @"
using System; using System.Runtime.InteropServices;
public class WinPaste {{
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}}
"@
$ok = $false
for ($i = 0; $i -lt 5; $i++) {{
    $proc = Get-Process | Where-Object {{ $_.MainWindowTitle -like '*{window_title}*' -and $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
    if ($proc) {{
        [WinPaste]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
        [WinPaste]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 500
        if ([WinPaste]::GetForegroundWindow() -eq $proc.MainWindowHandle) {{ $ok = $true; break }}
    }}
    Start-Sleep -Milliseconds 500
}}
if ($ok) {{
    Set-Clipboard -Value '{text_escaped}'
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.SendKeys]::SendWait("^v")
    Write-Output "ok"
}} else {{
    Write-Output "not_found"
}}
"""
        else:
            ps = f"""
Start-Sleep -Milliseconds 800
Set-Clipboard -Value '{text_escaped}'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("^v")
"""
        r = subprocess.run(["powershell", "-Command", ps], capture_output=True,
                            text=True, timeout=22)
        if window_title and "not_found" in (r.stdout or ""):
            return f"Window '{window_title}' not found — text not typed"
        return f"Typed {len(text)} chars into {window_title or 'focused window'}"
    return "Type not supported on this OS"


async def _press_keys(p: dict) -> str:
    """Send keyboard shortcut to active window. e.g. ctrl+v, ctrl+s, alt+f4"""
    keys = p.get("keys", "").lower().strip()
    if not keys:
        raise ValueError("No keys specified")
    await asyncio.sleep(0.3)

    KEY_MAP = {
        "ctrl+v": "^v", "ctrl+c": "^c", "ctrl+x": "^x", "ctrl+z": "^z",
        "ctrl+s": "^s", "ctrl+a": "^a", "ctrl+n": "^n", "ctrl+w": "^w",
        "ctrl+t": "^t", "ctrl+f": "^f", "ctrl+p": "^p", "ctrl+r": "^r",
        "ctrl+shift+s": "^+s", "alt+f4": "%{F4}", "alt+tab": "%{TAB}",
        "enter": "{ENTER}", "escape": "{ESC}", "tab": "{TAB}",
        "f5": "{F5}", "delete": "{DEL}", "backspace": "{BS}",
        "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
        "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pagedown": "{PGDN}",
    }
    sk = KEY_MAP.get(keys, keys)
    if WINDOWS:
        ps = f"""
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{sk}")
"""
        subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=6)
    return f"Sent: {keys}"


async def _media_control(p: dict) -> str:
    """Control media playback: play_pause, next, previous, volume_up, volume_down."""
    action = p.get("action", "play_pause").lower().strip()
    if WINDOWS:
        VK_MAP = {
            "play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
            "stop": 0xB2, "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD,
        }
        vk = VK_MAP.get(action)
        if vk:
            ps = f"""
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class Media {{
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint flags, UIntPtr extra);
}}
"@
[Media]::keybd_event({vk}, 0, 1, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 50
[Media]::keybd_event({vk}, 0, 3, [UIntPtr]::Zero)
"""
            subprocess.run(["powershell", "-Command", ps], capture_output=True, timeout=5)
            return f"Media: {action}"
        raise ValueError(f"Unknown media action: {action}")
    return "Media control not supported"


async def _toggle_screen_capture(p: dict) -> str:
    """Allow LLM to toggle screen capture on/off conversationally."""
    # Broadcast a toggle event; main.py handles the actual state change
    # We use a special marker in the result that main.py detects
    enabled = p.get("enabled", None)
    return f"__TOGGLE_SCREEN_CAPTURE__:{enabled}"

async def _open_file_in_app(p: dict) -> str:
    """Open a specific file directly in an app."""
    file_path = p.get("file_path", "").strip()
    app       = p.get("app_name", "").strip()
    if not file_path:
        raise ValueError("No file_path provided")
    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"Not found: {file_path}")
    if app:
        resolved = APP_ALIASES.get(app.lower(), app)
        if WINDOWS:
            subprocess.Popen(f'start "" "{resolved}" "{file_path}"', shell=True)
            return f"Opened {fp.name} in {app}"
    if WINDOWS:
        os.startfile(file_path)
    return f"Opened {fp.name}"


# ── Registry ──────────────────────────────────────────────────────────────

REGISTRY: Dict[str, Callable] = {
    # App control
    "open_app":               _open_app,
    "close_app":              _close_app,
    "kill_process":           _kill_process,
    "get_running_processes":  _get_running_processes,
    # Web
    "web_search":             _web_search,
    "open_url":               _open_url,
    # Files
    "move_file":              _move_file,
    "copy_file":              _copy_file,
    "delete_file":            _delete_file,
    "create_file":            _create_file,
    "read_file":              _read_file,
    "write_file":             _write_file,
    "list_folder":            _list_folder,
    "rename_file":            _rename_file,
    "open_folder":            _open_folder,
    # Media/system
    "take_screenshot":        _take_screenshot,
    "set_volume":             _set_volume,
    "play_media":             _play_media,
    "lock_screen":            _lock_screen,
    "empty_trash":            _empty_trash,
    # Clipboard
    "copy_to_clipboard":      _copy_to_clipboard,
    "read_clipboard":         _read_clipboard,
    # Info (auto-confirm)
    "get_system_info":        _get_system_info,
    "check_battery":          _check_battery,
    "get_time":               _get_time,
    "show_notification":      _show_notification,
    # Window interaction
    "focus_window":           _focus_window,
    "type_text":              _type_text,
    "press_keys":             _press_keys,
    "media_control":          _media_control,
    "open_file_in_app":       _open_file_in_app,
    # Shell (Full tier)
    "run_command":            _run_command,
    "toggle_screen_capture":  _toggle_screen_capture,
    # Aliases
    "open":                   _open_app,
    "search":                 _web_search,
    "screenshot":             _take_screenshot,
    "volume":                 _set_volume,
    "kill":                   _kill_process,
    "processes":              _get_running_processes,
    "clipboard":              _read_clipboard,
    "ls":                     _list_folder,
    "shell":                  _run_command,
}


class ActionExecutor:
    def __init__(self, on_pending: Callable = None, get_tier: Callable = None):
        self.on_pending = on_pending
        self.get_tier   = get_tier  # callable returns "minimal"|"standard"|"full"
        self._pending: Dict[str, PendingAction] = {}

    def confirm(self, action_id: str):
        if action_id in self._pending:
            self._pending[action_id].accept()

    def reject(self, action_id: str):
        if action_id in self._pending:
            self._pending[action_id].reject()

    async def request(self, action_type: str, params: dict,
                      display_text: str, timeout: int = 30) -> dict:
        atype = action_type.lower().strip()

        if atype not in REGISTRY:
            return {"success": False, "error": f"Unknown action: '{atype}'",
                    "action_id": "none"}

        # Tier check
        tier = self.get_tier() if self.get_tier else "standard"
        if atype in FULL_TIER_ONLY and tier != "full":
            return {"success": False,
                    "error": f"'{atype}' requires Full permission tier.",
                    "action_id": "none"}

        # Auto-confirm: read-only actions OR Full tier (skip all confirms)
        if atype in AUTO_CONFIRM or tier == "full":
            try:
                result = await REGISTRY[atype](params)
                print(f"[SOUL] auto-exec: {atype} -> ok")
                return {"success": True, "message": result,
                        "action_id": "auto", "auto": True}
            except Exception as e:
                print(f"[SOUL] auto-exec fail: {atype} -> {e}")
                return {"success": False, "error": str(e), "action_id": "auto"}

        # Standard/Minimal: needs confirmation
        pending = PendingAction(atype, params, display_text)
        self._pending[pending.id] = pending

        if self.on_pending:
            self.on_pending(pending)

        accepted = await pending.wait(timeout=timeout)

        if not accepted:
            self._pending.pop(pending.id, None)
            return {"success": False, "cancelled": True,
                    "message": "Timed out.", "action_id": pending.id}

        try:
            result = await REGISTRY[atype](params)
            self._pending.pop(pending.id, None)
            print(f"[SOUL] action ok: {atype} -> {result[:60]}")
            return {"success": True, "message": result, "action_id": pending.id}
        except Exception as e:
            self._pending.pop(pending.id, None)
            print(f"[SOUL] action fail: {atype} -> {e}")
            return {"success": False, "error": str(e), "action_id": pending.id}
