"""
SOUL — Vision Observer  v1.0
perception/observer.py

The closed loop between eyes and hands.

What this does:
  - Runs as a background async task alongside ScreenWatcher
  - Every 15s: compares new screen summary to previous
  - Scores whether the change is worth SOUL mentioning
  - If yes: asks the LLM (fast model, minimal tokens) for a short observation
  - Broadcasts proactive_message to frontend

Triggers proactive speech when:
  - An error dialog / crash appears
  - Active application changes unexpectedly
  - A build / compile result lands in a terminal
  - A notification badge appears
  - Screen goes from content to lock / sleep

Does NOT trigger when:
  - Screen content is just updating (video, animation, scrolling)
  - Change is cosmetic (minor text reflow, cursor blink region)
  - User has typed in the last 45s (don't interrupt flow)
  - A proactive message was sent in the last 3 minutes
  - Vision is OFF
  - No WebSocket clients are connected

Ambient mode auto-switch:
  - Separate loop polls every 30s
  - If no user message for >= AMBIENT_IDLE_SEC (300 = 5 min), broadcasts enter_ambient
  - Resets on any user message
"""

import asyncio
import re
import time
from difflib import SequenceMatcher
from typing import Optional, Callable, Awaitable

# ── Tuneable constants ────────────────────────────────────────────────────────

POLL_INTERVAL_SEC    = 15     # how often the observer wakes up
USER_IDLE_MIN_SEC    = 45     # min seconds since last user msg before she speaks
PROACTIVE_COOLDOWN   = 180    # min seconds between consecutive proactive messages
SIMILARITY_THRESHOLD = 0.82   # above this → screens are "the same", skip
AMBIENT_IDLE_SEC     = 300    # 5 minutes inactivity → ambient mode
AMBIENT_POLL_SEC     = 30     # how often idle-checker runs

# Phrases that mark a screen change as high-priority regardless of similarity score
_PRIORITY_PATTERNS = re.compile(
    r"\b("
    r"error|exception|traceback|crash|fail(?:ed|ure)?|"
    r"critical|warning|alert|blocked|denied|"
    r"unhandled|undefined|cannot|couldn't|"
    r"build fail|compilation error|syntax error|"
    r"stack overflow|segfault|killed|"
    r"new message|unread|notification|"
    r"install(?:ation)? complete|download complete|"
    r"restart required|update available"
    r")\b",
    re.IGNORECASE,
)

# Phrases that indicate a boring/expected screen state — don't bother mentioning
_BORING_PATTERNS = re.compile(
    r"\b("
    r"desktop|wallpaper|taskbar|clock|"
    r"cursor|mouse pointer|scrolling|"
    r"video playing|music playing|spotify|"
    r"screensaver|sleep|idle"
    r")\b",
    re.IGNORECASE,
)


def _similarity(a: str, b: str) -> float:
    """Normalized 0-1 text similarity. 1.0 = identical."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _extract_app(summary: str) -> str:
    """Try to pull the primary app name from a vision summary."""
    # Vision model usually says "The screen shows X" or "X is open"
    for pat in [
        r"(?:shows?|displaying|open(?:ed)?|running|active)[:\s]+([A-Z][A-Za-z0-9 ]+)",
        r"^([A-Z][A-Za-z0-9 ]{2,30})\s+(?:is|window|app)",
    ]:
        m = re.search(pat, summary)
        if m:
            return m.group(1).strip().lower()
    return ""


def _is_meaningful_change(prev: str, curr: str) -> tuple[bool, str]:
    """
    Returns (is_meaningful, reason).

    Priority check first (errors etc.) — these always fire.
    Then similarity gate — screens that are ~identical don't fire.
    Then app-change check — different active app is worth noting.
    """
    if not prev:
        # First real summary — no comparison possible, skip
        return False, "first capture"

    # Priority: error/crash/notification signals always fire
    prev_prio = bool(_PRIORITY_PATTERNS.search(prev))
    curr_prio = bool(_PRIORITY_PATTERNS.search(curr))
    if curr_prio and not prev_prio:
        return True, "priority_signal"

    # Similarity gate: if screens look basically the same, skip
    sim = _similarity(prev, curr)
    if sim >= SIMILARITY_THRESHOLD:
        return False, f"similarity={sim:.2f}"

    # App change: different primary app opened
    prev_app = _extract_app(prev)
    curr_app = _extract_app(curr)
    if prev_app and curr_app and prev_app != curr_app:
        return True, f"app_change: {prev_app} → {curr_app}"

    # Boring content filter: if both old and new are boring, skip
    if _BORING_PATTERNS.search(curr) and not curr_prio:
        return False, "boring_content"

    # Enough changed and not boring — worth evaluating
    return True, f"content_change: sim={sim:.2f}"


class VisionObserver:
    """
    Background observer that combines screen vision with proactive messaging.

    Usage in main.py lifespan:
        state.observer = VisionObserver(
            groq_client=state.groq,
            screen_watcher=state.screen_watcher,
            get_last_user_time=lambda: state._last_user_msg_time,
            get_ws_clients=lambda: state.ws_clients,
            broadcast=state.broadcast,
            get_screen_enabled=lambda: state.screen_enabled,
            save_exchange_fn=save_exchange,
        )
        asyncio.create_task(state.observer.start())
    """

    def __init__(
        self,
        groq_client,
        screen_watcher,
        get_last_user_time: Callable[[], float],
        get_ws_clients: Callable[[], list],
        broadcast: Callable[[dict], Awaitable],
        get_screen_enabled: Callable[[], bool],
        save_exchange_fn: Callable,
        get_current_context: Optional[Callable[[], str]] = None,
    ):
        self.groq               = groq_client
        self.screen_watcher     = screen_watcher
        self._get_last_user_time = get_last_user_time
        self._get_ws_clients    = get_ws_clients
        self._broadcast         = broadcast
        self._get_screen_enabled = get_screen_enabled
        self._save_exchange     = save_exchange_fn
        self._get_current_context = get_current_context

        self._running            = False
        self._last_summary       = ""
        self._last_proactive_at  = 0.0
        self._ambient_sent       = False   # tracks if we've already sent enter_ambient

    # ── Public controls ───────────────────────────────────────────────────────

    def notify_user_active(self):
        """Call this every time a user message arrives."""
        self._ambient_sent = False   # reset ambient flag on any activity

    async def start(self):
        self._running = True
        await asyncio.gather(
            self._vision_loop(),
            self._ambient_loop(),
        )

    def stop(self):
        self._running = False

    # ── Vision observation loop ───────────────────────────────────────────────

    async def _vision_loop(self):
        while self._running:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            try:
                await self._tick_vision()
            except Exception as ex:
                print(f"[SOUL] observer vision tick error: {ex}")

    async def _tick_vision(self):
        # Bail fast on any inactive condition
        if not self._get_screen_enabled():
            return
        if not self._get_ws_clients():
            return

        summary = getattr(self.screen_watcher, "summary", "") if self.screen_watcher else ""
        if not summary or summary.startswith("Screen vision unavail"):
            return

        # Don't interrupt active conversation
        idle_sec = time.time() - self._get_last_user_time()
        if idle_sec < USER_IDLE_MIN_SEC:
            return

        # Proactive cooldown
        if time.time() - self._last_proactive_at < PROACTIVE_COOLDOWN:
            return

        meaningful, reason = _is_meaningful_change(self._last_summary, summary)
        self._last_summary = summary

        if not meaningful:
            return

        print(f"[SOUL] observer: meaningful change ({reason}) — evaluating")

        # Ask LLM: is this worth saying something about?
        observation = await self._evaluate(summary, reason)
        if not observation:
            return

        self._last_proactive_at = time.time()
        print(f"[SOUL] observer: proactive → {observation[:80]}")

        await self._broadcast({
            "type":        "proactive_message",
            "text":        observation,
            "source":      "vision_observer",
            "change_type": reason,
        })
        self._save_exchange("assistant", observation)

        # Inject into LLM history so follow-up questions have context
        self.groq.conversation_history.append({
            "role":    "assistant",
            "content": observation,
        })

    async def _evaluate(self, screen_summary: str, change_reason: str) -> Optional[str]:
        """
        Asks the LLM whether this screen state is worth a proactive comment.
        Uses the fast 8B model, minimal token budget.
        Returns a short natural message, or None if not worth mentioning.
        """
        from groq_client import _FAST_MODEL, GROQ_API_BASE
        import httpx, json as _json

        entity_name = self.groq.config.get("entity", {}).get("name", "SOUL")
        user_name   = self.groq.config.get("entity", {}).get("user_name", "the user") or "the user"

        # Include recent context if available
        recent_ctx = ""
        if self._get_current_context:
            recent_ctx = self._get_current_context() or ""

        is_priority = "priority_signal" in change_reason

        prompt = f"""\
You are {entity_name}, a device companion AI on {user_name}'s computer.

Current screen: {screen_summary}
Change type: {change_reason}
{f"Recent context: {recent_ctx}" if recent_ctx else ""}

Task: Decide if what you see is worth a SHORT proactive comment to {user_name}.

Rules:
- Only comment if something genuinely actionable or interesting changed.
- Errors, crashes, build failures, unexpected dialogs → YES, worth saying something.
- App quietly opened in background, minor text change → NO.
- If YES: write ONE short natural sentence in your voice. No preamble. No "I notice". Just say it.
- If NO: reply with exactly: SKIP

Examples:
  Screen shows Python traceback → "there's a traceback in your terminal — ImportError on line 12."
  Screen shows build completed → "build finished clean."
  Screen shows new Discord message → "discord notification, if you care."
  Screen shows desktop wallpaper → SKIP
  Screen shows Spotify → SKIP
"""

        pool = (self.groq._chat_keys + self.groq._misc_keys) or self.groq._all_keys
        if not pool:
            return None

        for _key in pool:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as c:
                    r = await c.post(
                        f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {_key}",
                                 "Content-Type": "application/json"},
                        json={
                            "model":       _FAST_MODEL,
                            "messages":    [{"role": "user", "content": prompt}],
                            "max_tokens":  60,
                            "temperature": 0.6,
                        },
                    )
                    if r.status_code == 429:
                        continue
                    if r.status_code == 200:
                        text = r.json()["choices"][0]["message"]["content"].strip()
                        if text.upper() == "SKIP" or text.upper().startswith("SKIP"):
                            return None
                        # Sanity check — must be short
                        if len(text) > 200:
                            text = text[:200].rsplit(".", 1)[0] + "."
                        return text
            except Exception as ex:
                print(f"[SOUL] observer evaluate error: {ex}")
                continue

        return None

    # ── Ambient idle loop ─────────────────────────────────────────────────────

    async def _ambient_loop(self):
        while self._running:
            await asyncio.sleep(AMBIENT_POLL_SEC)
            try:
                await self._tick_ambient()
            except Exception as ex:
                print(f"[SOUL] observer ambient tick error: {ex}")

    async def _tick_ambient(self):
        if not self._get_ws_clients():
            return

        idle_sec = time.time() - self._get_last_user_time()

        if idle_sec >= AMBIENT_IDLE_SEC and not self._ambient_sent:
            print(f"[SOUL] observer: {idle_sec:.0f}s idle — entering ambient mode")
            self._ambient_sent = True
            await self._broadcast({"type": "enter_ambient"})

        elif idle_sec < AMBIENT_IDLE_SEC and self._ambient_sent:
            # User became active again — reset flag (don't re-send ambient until
            # they go idle again, notify_user_active() handles this too)
            self._ambient_sent = False
