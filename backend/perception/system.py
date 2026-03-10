"""
SOUL — Perception Layer  v1.6.0

Changes from v1.0:
  - ScreenWatcher._capture_vision: on exception, preserve last good summary instead
    of overwriting self.summary with the error string. That error string was flowing
    into build_context and giving the LLM contradictory signals ("Screen: ON" + error text).
  - ScreenWatcher: added `capture_error` property — build_context can check this to
    show "capture unavailable" vs "no capture yet" vs a real description.
  - ScreenWatcher: added `summary_age` property — seconds since last successful vision.
  - ScreenWatcher: added `has_fresh_capture` property — True if capture is <30s old.
  - Both _capture_thumb and _capture_vision: OSError fallback already present (v1.5.x patch),
    kept as-is. Added broader exception guard for display driver failures.
  - SystemMonitor: no changes — was solid.
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
    (r"(.+) - Visual Studio Code",  "Coding · {}"),
    (r"Visual Studio Code[- ]+(.+)", "Coding · {}"),
    (r"(.+) — Cursor",              "Coding · {}"),
    (r"(.+) - Notepad\+\+",         "Editing · {}"),
    (r"(.+) - Notepad",             "Editing · {}"),
    (r"(.+) - Microsoft Word",      "Writing · {}"),
    (r"(.+) - Google Docs",         "Writing · {}"),
    (r"(.+) - YouTube",             "Watching · {}"),
    (r"(.+) - Netflix",             "Watching · {}"),
    (r"Google Chrome$",             "Chrome"),
    (r"(.+) - Google Chrome",       "Browser · {}"),
    (r"(.+) - Mozilla Firefox",     "Browser · {}"),
    (r"Discord",                    "Discord"),
    (r"Slack",                      "Slack"),
    (r"Spotify",                    "Spotify"),
    (r"Terminal|Command Prompt|PowerShell|Windows PowerShell", "Terminal"),
    (r"Task Manager",               "Task Manager"),
    (r"File Explorer",              "Files"),
    (r"Figma",                      "Design · Figma"),
    (r"Adobe Photoshop",            "Design · Photoshop"),
]


def _get_soul_patterns():
    patterns = ["soul", "electron", "pacify"]
    try:
        from config import load_config
        cfg = load_config()
        name   = cfg.get("entity", {}).get("name", "")
        device = cfg.get("entity", {}).get("device_name", "")
        if name:   patterns.append(name.lower())
        if device: patterns.append(device.lower())
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
    cleaned = re.sub(
        r"\s*[-–—]\s*(Microsoft|Google|Mozilla|Apple|Adobe)\S*", "", title).strip()
    if len(cleaned) > 28:
        cleaned = cleaned[:28] + "…"
    return cleaned


class SystemMonitor:
    def __init__(self):
        self._snapshot  = {}
        self._running   = False
        self._last_net  = psutil.net_io_counters()
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
        now     = time.time()
        elapsed = max(now - self._last_time, 0.1)

        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent

        gpu_str = "N/A"
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2
            )
            if r.returncode == 0:
                gpu_str = r.stdout.strip() + "%"
        except Exception:
            pass

        net      = psutil.net_io_counters()
        sent_kb  = (net.bytes_sent - self._last_net.bytes_sent) / elapsed / 1024
        recv_kb  = (net.bytes_recv - self._last_net.bytes_recv) / elapsed / 1024
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
                dr = (disk.read_bytes  - self._last_disk.read_bytes)  / elapsed / 1024
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
                plug        = "⚡" if batt.power_plugged else ""
                battery_str = f"{battery_val}%{plug}"
        except Exception:
            pass

        self._last_time = now

        raw_title = get_active_window_title()
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
            "cpu":        cpu,
            "ram":        ram,
            "gpu":        gpu_str,
            "net_sent":   fmt_kb(sent_kb),
            "net_recv":   fmt_kb(recv_kb),
            "disk_read":  disk_r,
            "disk_write": disk_w,
            "battery":    battery_str,
            "battery_pct": battery_val,
            "active_app": raw_title,
            "task_label": task_label,
            "timestamp":  datetime.now().isoformat(),
        }


class ScreenWatcher:
    """
    Captures screen thumbnails and calls vision API for a text summary.

    Key design principles (v1.6):
    - summary always holds the LAST SUCCESSFUL description, not an error string.
      Error strings in summary caused contradictory context ("Screen: ON\nScreen unavailable:…").
    - capture_error holds the most recent failure reason (or "" if last capture succeeded).
    - build_context in groq_client.py reads capture_error to show "capture unavailable"
      instead of passing error text as if it were a real description.
    - summary_age tells context builder how stale the description is.
    """

    def __init__(self, groq_client, thumb_interval: int = 2, vision_interval: int = 6):
        self.groq           = groq_client
        self.thumb_interval  = thumb_interval   # seconds between thumbnail captures
        self.vision_interval = vision_interval  # seconds between vision API calls

        # Public state — read by main.py and groq_client.build_context
        self.summary       = ""   # last SUCCESSFUL vision description — never an error string
        self.thumbnail_b64 = ""   # last JPEG thumbnail, base64 encoded

        # Tracking
        self._running           = False
        self._last_vision_time  = 0.0   # unix timestamp of last successful vision capture
        self._last_thumb_time   = 0.0   # unix timestamp of last successful thumbnail
        self._capture_error     = ""    # most recent capture failure reason ("" = none)

    # ── Public helper properties ──────────────────────────────────────────────

    @property
    def capture_error(self) -> str:
        """Most recent capture failure reason. Empty string if last capture succeeded."""
        return self._capture_error

    @property
    def summary_age(self) -> float:
        """Seconds since last successful vision capture. 999 if never captured."""
        if self._last_vision_time > 0:
            return time.time() - self._last_vision_time
        return 999.0

    @property
    def has_fresh_capture(self) -> bool:
        """True if a vision description was captured within the last 30 seconds."""
        return self.summary_age < 30

    @property
    def has_any_capture(self) -> bool:
        """True if we've ever gotten a successful vision description."""
        return bool(self.summary) and self._last_vision_time > 0

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def start(self):
        self._running = True
        vision_every  = max(1, self.vision_interval // self.thumb_interval)
        cycle         = 0
        while self._running:
            try:
                await self._capture_thumb()
                cycle += 1
                if cycle >= vision_every:
                    cycle = 0
                    await self._capture_vision()
            except Exception as e:
                print(f"[SOUL] screen watcher loop error: {e}")
            await asyncio.sleep(self.thumb_interval)

    def stop(self):
        self._running = False

    # ── Thumbnail capture ─────────────────────────────────────────────────────

    async def _capture_thumb(self):
        """
        Fast: grab screen → 400×225 JPEG thumbnail.
        On failure: clears thumbnail but does NOT corrupt summary or capture_error
        (thumbnail failures are frequent and expected on some GPU configs).
        """
        try:
            from PIL import ImageGrab
            img = self._grab_screen()
            if img is None or img.size[0] <= 0 or img.size[1] <= 0:
                self.thumbnail_b64 = ""
                return
            thumb = img.copy()
            thumb.thumbnail((400, 225))
            tbuf = BytesIO()
            thumb.save(tbuf, format="JPEG", quality=88, optimize=True)
            self.thumbnail_b64    = base64.b64encode(tbuf.getvalue()).decode()
            self._last_thumb_time = time.time()
            # Clear error on success
            if self._capture_error and "thumb" in self._capture_error:
                self._capture_error = ""
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"[SOUL] thumbnail FAILED: {err}")
            self.thumbnail_b64 = ""
            # Only set capture_error for thumbnail if it's the only thing failing
            # (don't overwrite a vision error with a thumbnail error)
            if not self._capture_error:
                self._capture_error = f"thumb: {err}"

    # ── Vision capture ────────────────────────────────────────────────────────

    async def _capture_vision(self):
        """
        Slower: grab screen → call vision API → update self.summary.

        CRITICAL: on any failure, we preserve the last good self.summary.
        We do NOT overwrite it with error strings. Error tracking is in
        self._capture_error for the context builder to use.

        This was the root cause of the "Screen: ON\nScreen unavailable: [Errno 22]"
        contradiction that made SOUL oscillate about screen state every message.
        """
        try:
            img = self._grab_screen()
            if img is None or img.size[0] <= 0 or img.size[1] <= 0:
                # Screen couldn't be grabbed but that's not an error we surface in summary
                self._capture_error = "capture returned empty image"
                return

            vis = img.copy()
            vis.thumbnail((1280, 720))
            buf = BytesIO()
            vis.save(buf, format="JPEG", quality=85, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode()

            summary = await self.groq.vision_query(b64)

            if summary and not summary.startswith("Screen vision unavail"):
                # Success — update summary and clear any previous error
                self.summary          = summary
                self._last_vision_time = time.time()
                self._capture_error   = ""
                print(f"[SOUL] vision: {self.summary[:100]}")
            else:
                # Vision API returned nothing useful — keep last good summary
                # Update error state so context builder knows capture is unreliable
                self._capture_error = "vision API unavailable"
                print(f"[SOUL] vision returned empty/unavail — keeping last summary")

        except OSError as e:
            # Common on some Windows GPU/DPI configs — [Errno 22] Invalid argument
            # Keep last good summary. Update error state.
            err = f"OSError: {e}"
            print(f"[SOUL] vision FAILED (OS): {err}")
            self._capture_error = err
            # Do NOT set self.summary = error string

        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"[SOUL] vision FAILED: {err}")
            self._capture_error = err
            # Do NOT set self.summary = error string

    # ── Screen grab helper ────────────────────────────────────────────────────

    def _grab_screen(self):
        """
        Wrapper around ImageGrab.grab() with fallback for GPU/DPI driver issues.
        Returns a PIL Image or None.
        """
        from PIL import ImageGrab
        try:
            img = ImageGrab.grab(all_screens=False)
            return img
        except OSError:
            # [Errno 22] Invalid argument — try without the all_screens param
            # Happens on certain Windows display driver + DPI configurations
            try:
                img = ImageGrab.grab()
                return img
            except Exception:
                return None
        except Exception:
            return None
