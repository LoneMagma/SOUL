"""
SOUL — Perception Layer
"""

import asyncio
import base64
import ctypes
import ctypes.wintypes
import platform
import re
import time
from datetime import datetime
from io import BytesIO
from typing import Optional

import psutil


def get_active_window_title() -> str:
    try:
        if platform.system() != "Windows":
            return ""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


TASK_PATTERNS = [
    (r"(.+) - Visual Studio Code", "Coding · {}"),
    (r"Visual Studio Code[- ]+(.+)", "Coding · {}"),
    (r"(.+) — Cursor", "Coding · {}"),
    (r"(.+) - Notepad\+\+", "Editing · {}"),
    (r"(.+) - Notepad", "Editing · {}"),
    (r"(.+) - Microsoft Word", "Writing · {}"),
    (r"(.+) - Google Docs", "Writing · {}"),
    (r"(.+) - YouTube", "Watching · {}"),
    (r"(.+) - Netflix", "Watching · {}"),
    (r"Google Chrome$", "Chrome"),
    (r"(.+) - Google Chrome", "Browser · {}"),
    (r"(.+) - Mozilla Firefox", "Browser · {}"),
    (r"Discord", "Discord"),
    (r"Slack", "Slack"),
    (r"Spotify", "Spotify"),
    (r"Terminal|Command Prompt|PowerShell|Windows PowerShell", "Terminal"),
    (r"Task Manager", "Task Manager"),
    (r"File Explorer", "Files"),
    (r"Figma", "Design · Figma"),
    (r"Adobe Photoshop", "Design · Photoshop"),
]


def _get_soul_patterns():
    patterns = ["soul", "electron", "pacify"]
    try:
        from config import load_config
        cfg = load_config()
        name = cfg.get("entity", {}).get("name", "")
        device = cfg.get("entity", {}).get("device_name", "")
        if name:
            patterns.append(name.lower())
        if device:
            patterns.append(device.lower())
    except Exception:
        pass
    return patterns


def parse_task_label(title: str) -> str:
    if not title:
        return ""
    lower = title.lower()
    if any(p in lower for p in _get_soul_patterns()):
        return ""
    for pattern, template in TASK_PATTERNS:
        m = re.match(pattern, title, re.IGNORECASE)
        if m:
            if m.lastindex and m.lastindex >= 1:
                detail = m.group(1).strip()
                if "/" in detail or "\\" in detail:
                    detail = detail.split("/")[-1].split("\\")[-1]
                if len(detail) > 24:
                    detail = detail[:24] + "…"
                return template.format(detail)
            return template.replace("{}", "").strip()
    cleaned = re.sub(r"\s*[-–—]\s*(Microsoft|Google|Mozilla|Apple|Adobe)\S*", "", title).strip()
    if len(cleaned) > 28:
        cleaned = cleaned[:28] + "…"
    return cleaned


class SystemMonitor:
    def __init__(self):
        self._snapshot = {}
        self._running = False
        self._last_net = psutil.net_io_counters()
        self._last_disk = psutil.disk_io_counters()
        self._last_time = time.time()

    @property
    def snapshot(self) -> dict:
        return self._snapshot.copy()

    def collect_now(self) -> dict:
        try:
            self._snapshot = self._collect()
        except Exception as e:
            print(f"[SOUL] collect_now error: {e}")
        return self._snapshot.copy()

    async def start(self, interval: float = 3.0):
        self._running = True
        while self._running:
            await asyncio.sleep(interval)
            try:
                self._snapshot = self._collect()
            except Exception as e:
                print(f"[SOUL] monitor error: {e}")

    def stop(self):
        self._running = False

    def _collect(self) -> dict:
        now = time.time()
        elapsed = max(now - self._last_time, 0.1)

        # First call always returns 0.0 (no baseline) — use 0.1s interval
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent

        gpu_str = "N/A"
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                gpu_str = r.stdout.strip() + "%"
        except Exception:
            pass

        net = psutil.net_io_counters()
        sent_kb = (net.bytes_sent - self._last_net.bytes_sent) / elapsed / 1024
        recv_kb = (net.bytes_recv - self._last_net.bytes_recv) / elapsed / 1024
        self._last_net = net

        def fmt_kb(kb: float) -> str:
            if kb > 1024:
                return f"{kb/1024:.1f}MB/s"
            return f"{kb:.0f}KB/s"

        disk_r = "—"
        disk_w = "—"
        try:
            disk = psutil.disk_io_counters()
            if disk and self._last_disk:
                dr = (disk.read_bytes - self._last_disk.read_bytes) / elapsed / 1024
                dw = (disk.write_bytes - self._last_disk.write_bytes) / elapsed / 1024
                disk_r = fmt_kb(dr)
                disk_w = fmt_kb(dw)
            self._last_disk = disk
        except Exception:
            pass

        battery_str = "—"
        battery_val = None
        try:
            batt = psutil.sensors_battery()
            if batt:
                battery_val = round(batt.percent)
                plug = "⚡" if batt.power_plugged else ""
                battery_str = f"{battery_val}%{plug}"
        except Exception:
            pass

        self._last_time = now

        raw_title = get_active_window_title()
        # Filter out Windows OS chrome and SOUL's own windows
        _os_noise = {
            "task switching", "search", "start", "action center",
            "notification", "desktop window manager", "program manager",
            "windows input experience", "cortana", "", "—"
        }
        _soul_own = {"thinkiee", "soul", "workspace", "pacify"}
        raw_lower = raw_title.lower()
        if raw_lower in _os_noise or any(s in raw_lower for s in _soul_own):
            raw_title = ""
        task_label = parse_task_label(raw_title)
        if not task_label:
            task_label = "—"

        return {
            "cpu": cpu,
            "ram": ram,
            "gpu": gpu_str,
            "net_sent": fmt_kb(sent_kb),
            "net_recv": fmt_kb(recv_kb),
            "disk_read": disk_r,
            "disk_write": disk_w,
            "battery": battery_str,
            "battery_pct": battery_val,
            "active_app": raw_title,
            "task_label": task_label,
            "timestamp": datetime.now().isoformat(),
        }


class ScreenWatcher:
    def __init__(self, groq_client, thumb_interval: int = 2, vision_interval: int = 6):
        self.groq = groq_client
        self.thumb_interval  = thumb_interval   # seconds between thumbnail captures
        self.vision_interval = vision_interval  # seconds between vision API calls
        self.summary         = ""
        self.thumbnail_b64      = ""
        self._running           = False
        self._last_vision_time  = 0.0  # unix timestamp of last successful vision capture
        self._vision_counter = 0  # increments each thumb cycle, triggers vision every N

    async def start(self):
        self._running = True
        vision_every = max(1, self.vision_interval // self.thumb_interval)
        cycle = 0
        while self._running:
            try:
                await self._capture_thumb()
                cycle += 1
                if cycle >= vision_every:
                    cycle = 0
                    await self._capture_vision()
            except Exception as e:
                print(f"[SOUL] screen watcher error: {e}")
            await asyncio.sleep(self.thumb_interval)

    def stop(self):
        self._running = False

    async def _capture_thumb(self):
        """Fast: grab screen, build 160x90 JPEG thumbnail only."""
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=False)
            thumb = img.copy()
            thumb.thumbnail((400, 225))
            tbuf = BytesIO()
            thumb.save(tbuf, format="JPEG", quality=88, optimize=True)
            self.thumbnail_b64 = base64.b64encode(tbuf.getvalue()).decode()
        except Exception as e:
            print(f"[SOUL] thumbnail FAILED: {type(e).__name__}: {e}")
            self.thumbnail_b64 = ""

    async def _capture_vision(self):
        """Slower: grab screen, encode PNG, call vision API."""
        import time as _time
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=False)
            vis = img.copy()
            vis.thumbnail((1280, 720))
            buf = BytesIO()
            vis.save(buf, format="JPEG", quality=85, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            summary = await self.groq.vision_query(b64)
            if summary and not summary.startswith("Screen vision unavail"):
                self.summary = summary
                self._last_vision_time = _time.time()
                print(f"[SOUL] vision: {self.summary[:100]}")
            else:
                print(f"[SOUL] vision empty/unavail: {summary}")
        except Exception as e:
            print(f"[SOUL] vision FAILED: {type(e).__name__}: {e}")
            self.summary = f"Screen unavailable: {e}"
