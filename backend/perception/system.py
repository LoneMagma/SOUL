"""
SOUL — Perception Layer
Expanded: disk I/O, network, battery, active window title, smart task label.
Active window via ctypes (no extra deps on Windows).
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


# ─────────────────────────────────────────────
# ACTIVE WINDOW — ctypes, zero deps
# ─────────────────────────────────────────────

def get_active_window_title() -> str:
    """Get foreground window title on Windows."""
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


# App name patterns → clean label
TASK_PATTERNS = [
    (r"Visual Studio Code[- ]+(.+)", "Coding · {}"),
    (r"(.+) - Visual Studio Code", "Coding · {}"),
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
    (r"Adobe Premiere", "Video · Premiere"),
]

def _get_soul_patterns():
    """Load entity name from config so custom names are always filtered."""
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

SOUL_WINDOW_PATTERNS = ["soul", "electron", "pacify"]


def parse_task_label(title: str) -> str:
    """Convert raw window title to clean task label."""
    if not title:
        return ""

    # Filter out SOUL's own window (dynamic — includes custom name)
    lower = title.lower()
    patterns = _get_soul_patterns()
    if any(p in lower for p in patterns):
        return ""

    for pattern, template in TASK_PATTERNS:
        m = re.match(pattern, title, re.IGNORECASE)
        if m:
            if m.lastindex and m.lastindex >= 1:
                detail = m.group(1).strip()
                # Truncate long file paths to just filename
                if "/" in detail or "\\" in detail:
                    detail = detail.split("/")[-1].split("\\")[-1]
                if len(detail) > 24:
                    detail = detail[:24] + "…"
                return template.format(detail)
            return template.format("") if "{}" in template else template

    # Fallback: strip common suffixes and return clean title
    cleaned = re.sub(r"\s*[-–—]\s*(Microsoft|Google|Mozilla|Apple|Adobe)\S*", "", title)
    cleaned = cleaned.strip()
    if len(cleaned) > 28:
        cleaned = cleaned[:28] + "…"
    return cleaned


# ─────────────────────────────────────────────
# SYSTEM MONITOR
# ─────────────────────────────────────────────

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

    async def start(self, interval: float = 3.0):
        self._running = True
        while self._running:
            try:
                self._snapshot = self._collect()
            except Exception as e:
                print(f"[SOUL] System monitor error: {e}")
            await asyncio.sleep(interval)

    def stop(self):
        self._running = False

    def _collect(self) -> dict:
        now = time.time()
        elapsed = max(now - self._last_time, 0.1)

        # CPU / RAM / GPU
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent

        gpu_str = "—"
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

        # Network delta
        net = psutil.net_io_counters()
        sent_kb = (net.bytes_sent - self._last_net.bytes_sent) / elapsed / 1024
        recv_kb = (net.bytes_recv - self._last_net.bytes_recv) / elapsed / 1024
        self._last_net = net

        def fmt_kb(kb: float) -> str:
            if kb > 1024:
                return f"{kb/1024:.1f}MB/s"
            return f"{kb:.0f}KB/s"

        # Disk delta
        disk_str_r = "—"
        disk_str_w = "—"
        try:
            disk = psutil.disk_io_counters()
            if disk and self._last_disk:
                dr = (disk.read_bytes - self._last_disk.read_bytes) / elapsed / 1024
                dw = (disk.write_bytes - self._last_disk.write_bytes) / elapsed / 1024
                disk_str_r = fmt_kb(dr)
                disk_str_w = fmt_kb(dw)
            self._last_disk = disk
        except Exception:
            pass

        # Battery
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

        # Active window
        raw_title = get_active_window_title()
        task_label = parse_task_label(raw_title)
        if not task_label:
            task_label = "—"

        return {
            "cpu": cpu,
            "ram": ram,
            "gpu": gpu_str,
            "net_sent": fmt_kb(sent_kb),
            "net_recv": fmt_kb(recv_kb),
            "disk_read": disk_str_r,
            "disk_write": disk_str_w,
            "battery": battery_str,
            "battery_pct": battery_val,
            "active_app": raw_title,
            "task_label": task_label,
            "timestamp": datetime.now().isoformat()
        }


# ─────────────────────────────────────────────
# SCREEN WATCHER
# ─────────────────────────────────────────────

class ScreenWatcher:
    def __init__(self, groq_client, interval_sec: int = 5):
        self.groq = groq_client
        self.interval = interval_sec
        self.summary = ""
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            try:
                await self._capture()
            except Exception as e:
                print(f"[SOUL] Screen capture error: {e}")
            await asyncio.sleep(self.interval)

    def stop(self):
        self._running = False

    async def _capture(self):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            img.thumbnail((1280, 720))
            buf = BytesIO()
            img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()
            self.summary = await self.groq.vision_query(b64)
        except Exception as e:
            self.summary = f"Screen unavailable: {e}"
