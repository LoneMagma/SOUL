"""
SOUL — Action Verifier  v1.0
backend/verifier.py

The closed loop: eyes confirm what hands did.

  pre_capture()                 → snapshot screen before action fires
  verify_and_fallback(...)      → post-capture, compare, adapt if needed
  VerificationResult            → what actually happened, grounded in vision

Flow per action:
  1. pre_capture() — store current screen state
  2. executor fires the action
  3. verify_and_fallback() — wait for UI to settle → force fresh vision capture
     → compare pre/post similarity
     → if changed as expected: visual_confirmed = True
     → if not: try one fallback action, check again
  4. groq.inject_visual_result() — LLM gets grounded truth, not just Python bools

Fallback chains (one level deep, no loops):
  open_app       → focus_window  (app may already be running)
  focus_window   → open_app      (app may not be running yet)

Actions that skip visual verification (unverifiable — no screen signal):
  type_text, press_keys, copy_to_clipboard, read_*, get_*, check_*, media_control
  These trust the executor return value directly.

The delta LLM call (what changed in one sentence) is best-effort:
  if it 429s or times out, we fall back to generic strings.
  The core loop (pre/post compare) works without it.
"""

import asyncio
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Optional

# ── Timing ────────────────────────────────────────────────────────────────────
# How long to wait after action fires before taking the post-capture screenshot.
# Apps vary wildly in how long they take to paint.
POST_WAIT: dict[str, float] = {
    "open_app":        2.8,
    "web_search":      2.2,
    "open_url":        2.2,
    "open_folder":     1.8,
    "open_file_in_app":1.8,
    "play_media":      1.6,
    "run_command":     2.0,
    "create_file":     1.2,
    "write_file":      1.2,
    "take_screenshot": 1.0,
    "lock_screen":     1.4,
    "close_app":       1.6,
    "focus_window":    1.0,
    "default":         1.4,
}

# Screen-change threshold: similarity below this = "something meaningfully changed"
CHANGE_THRESHOLD = 0.88

# Actions where screen gives us useful signal
VERIFIABLE = {
    "open_app", "close_app", "focus_window",
    "web_search", "open_url", "open_folder", "open_file_in_app",
    "play_media", "run_command", "create_file", "write_file",
    "take_screenshot", "lock_screen",
}

# Actions where screen gives no useful signal — trust executor return value
UNVERIFIABLE = {
    "copy_to_clipboard", "read_clipboard", "get_system_info",
    "get_running_processes", "check_battery", "get_time",
    "show_notification", "press_keys", "media_control",
    "toggle_screen_capture", "empty_trash", "rename_file",
    "list_folder", "read_file", "type_text", "set_volume",
    "kill_process", "delete_file",
}

# Fallback chains: what to try once if the primary action fails visually
# Each value is a callable: params → fallback_action_dict (or None to skip)
FALLBACK_CHAINS: dict[str, Callable[[dict], Optional[dict]]] = {
    "open_app": lambda p: {
        "type":         "focus_window",
        "params":       {"title": p.get("app_name", "")},
        "display_text": "App may be running — focusing",
    },
    "focus_window": lambda p: {
        "type":         "open_app",
        "params":       {"app_name": p.get("title", "")},
        "display_text": "Not focused — opening",
    },
}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    action_type:      str
    executor_ok:      bool           # what the Python executor returned
    visual_confirmed: bool           # did the screen actually change as expected?
    success:          bool           # final verdict used by inject_visual_result
    pre_summary:      str  = ""
    post_summary:     str  = ""
    delta:            str  = ""      # one-sentence human description of what changed
    fallback_used:    Optional[dict] = None   # fallback action dict if we used one
    skipped_verify:   bool = False   # True for unverifiable actions


# ── Verifier ──────────────────────────────────────────────────────────────────

class ActionVerifier:
    """
    Attach one instance to SOULState.

    Usage:
        # Before action fires:
        await state.verifier.pre_capture()

        # Run the action (existing executor logic unchanged):
        result = await state.executor.request(...)

        # Close the loop:
        final_ok, vr = await state.verifier.verify_and_fallback(
            action      = action,
            executor_ok = result.get("success", False),
            execute_fn  = lambda a: state.executor.request(
                              action_type=a["type"],
                              params=a.get("params", {}),
                              display_text=a.get("display_text", ""),
                          ),
        )
        state.groq.inject_visual_result(action, result, vr)
    """

    def __init__(self, screen_watcher, groq_client):
        self.screen       = screen_watcher   # may be None if vision disabled; update later
        self.groq         = groq_client
        self._pre_summary = ""

    # ── Public ────────────────────────────────────────────────────────────────

    async def pre_capture(self):
        """Snapshot screen state before the action fires. Call immediately before executor."""
        self._pre_summary = getattr(self.screen, "summary", "") if self.screen else ""

    async def verify_and_fallback(
        self,
        action:      dict,
        executor_ok: bool,
        execute_fn:  Callable,   # async fn(action_dict) → dict with "success" key
    ) -> tuple[bool, VerificationResult]:
        """
        Full closed loop with one fallback attempt.

        Returns (final_success, VerificationResult).

        Steps:
          1. Verify the original action via post-capture + compare
          2. If failed and a fallback exists: pre-capture → run fallback → verify fallback
          3. Return the best result
        """
        vr = await self._verify_one(action, executor_ok)
        if vr.success:
            return True, vr

        # Attempt fallback
        atype   = action.get("type", "")
        params  = action.get("params", {})
        fb_fn   = FALLBACK_CHAINS.get(atype)
        if not fb_fn:
            return False, vr

        fallback = fb_fn(params)
        if not fallback:
            return False, vr

        print(f"[SOUL] verifier: '{atype}' failed — fallback → '{fallback['type']}'")

        await self.pre_capture()
        try:
            fb_result = await execute_fn(fallback)
            fb_ok = fb_result.get("success", False) if isinstance(fb_result, dict) else bool(fb_result)
        except Exception as e:
            print(f"[SOUL] verifier fallback execute error: {e}")
            fb_ok = False

        fb_vr = await self._verify_one(fallback, fb_ok)
        fb_vr.fallback_used = fallback   # record that we used a fallback

        return fb_vr.success, fb_vr

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _verify_one(self, action: dict, executor_ok: bool) -> VerificationResult:
        atype  = action.get("type", "")
        params = action.get("params", {})

        # Unverifiable: trust executor directly, skip screen check
        if atype in UNVERIFIABLE or atype not in VERIFIABLE:
            return VerificationResult(
                action_type=atype,
                executor_ok=executor_ok,
                visual_confirmed=False,
                success=executor_ok,
                skipped_verify=True,
            )

        # No screen available: degrade gracefully, trust executor
        if not self.screen:
            return VerificationResult(
                action_type=atype,
                executor_ok=executor_ok,
                visual_confirmed=False,
                success=executor_ok,
                skipped_verify=True,
            )

        wait       = POST_WAIT.get(atype, POST_WAIT["default"])
        post       = await self._post_capture(wait)
        pre        = self._pre_summary
        sim        = _sim(pre, post)
        changed    = sim < CHANGE_THRESHOLD

        # ── Decision tree ─────────────────────────────────────────────────────

        if executor_ok and changed:
            # Both agree: success
            delta = await self._delta(atype, params, pre, post)
            return VerificationResult(
                action_type=atype, executor_ok=True, visual_confirmed=True, success=True,
                pre_summary=pre, post_summary=post, delta=delta,
            )

        if executor_ok and not changed:
            # Executor said OK but screen didn't move
            # Could be app already open/focused → check if expected thing is visible
            hint = (params.get("app_name") or params.get("title") or "").lower()
            if hint and _hint_visible(hint, post):
                return VerificationResult(
                    action_type=atype, executor_ok=True, visual_confirmed=True, success=True,
                    pre_summary=pre, post_summary=post,
                    delta=f"{hint} was already active",
                )
            # Screen unchanged and hint not visible → suspicious failure
            return VerificationResult(
                action_type=atype, executor_ok=True, visual_confirmed=False, success=False,
                pre_summary=pre, post_summary=post,
                delta="screen unchanged after action",
            )

        if not executor_ok and changed:
            # Executor failed but screen moved anyway (happens with some Win32 API quirks)
            delta = await self._delta(atype, params, pre, post)
            return VerificationResult(
                action_type=atype, executor_ok=False, visual_confirmed=True, success=True,
                pre_summary=pre, post_summary=post, delta=delta,
            )

        # Both say no: genuine failure
        return VerificationResult(
            action_type=atype, executor_ok=False, visual_confirmed=False, success=False,
            pre_summary=pre, post_summary=post,
            delta="no change detected",
        )

    async def _post_capture(self, wait_sec: float) -> str:
        """Wait for UI to settle, then force a fresh vision capture. Returns new summary."""
        await asyncio.sleep(wait_sec)
        if not self.screen:
            return ""
        try:
            await self.screen._capture_vision()
        except Exception as e:
            print(f"[SOUL] verifier post_capture error: {e}")
        return getattr(self.screen, "summary", "")

    async def _delta(self, atype: str, params: dict, pre: str, post: str) -> str:
        """
        One-sentence LLM description of what changed on screen.
        Uses fast 8B model, 40-token cap. Falls back to 'screen changed' on any failure.
        """
        from groq_client import _FAST_MODEL, GROQ_API_BASE
        import httpx

        pool = (self.groq._chat_keys + self.groq._misc_keys) or self.groq._all_keys
        if not pool:
            return "screen changed"

        prompt = (
            f"Action: {atype} | params: {params}\n"
            f"Before: {pre[:260]}\n"
            f"After:  {post[:260]}\n\n"
            "In ONE short sentence: what changed on screen? "
            "Be specific. If nothing meaningful changed, say 'no visible change'."
        )

        for key in pool:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(7.0)) as c:
                    r = await c.post(
                        f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json"},
                        json={
                            "model":       _FAST_MODEL,
                            "messages":    [{"role": "user", "content": prompt}],
                            "max_tokens":  40,
                            "temperature": 0.2,
                        },
                    )
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"].strip()
                    if r.status_code == 429:
                        continue
            except Exception as e:
                print(f"[SOUL] verifier delta error: {e}")
                continue

        return "screen changed"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sim(a: str, b: str) -> float:
    """Normalized similarity 0-1. Caps at 800 chars each for speed."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower()[:800], b.lower()[:800]).ratio()


def _hint_visible(hint: str, summary: str) -> bool:
    """
    Check if a short app name hint appears in a vision summary.
    Uses first 5 chars to be tolerant of suffix differences (Chrome vs Chromium etc).
    """
    if not hint or not summary:
        return False
    h = hint[:5].lower()
    return h in summary.lower()
