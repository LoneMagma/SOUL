

"""
SOUL — Main Server  v1.7
Adds: closed action loop via ActionVerifier (verifier.py)
  - pre_capture() before every action fires
  - post_capture + screen compare after every verifiable action
  - one automatic fallback attempt on visual failure
  - inject_visual_result() replaces raw inject_action_result() for exec actions
  - /reset endpoint: wipes config + memory DB, returns to onboarding
"""

import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
sys.path.insert(0, os.path.dirname(__file__))
from perception.observer import VisionObserver

from config import load_config, save_config, is_first_run, DEFAULT_CONFIG
from groq_client import GroqClient
import time
import time
from perception.system import ScreenWatcher, SystemMonitor
from perception.observer import VisionObserver
from actions.executor import ActionExecutor, PendingAction
from memory.patterns import PatternEngine, format_memory_for_llm, save_exchange, scrub_stale_names
from verifier import ActionVerifier, VERIFIABLE


class SOULState:
    def __init__(self):
        self.config = load_config()
        self.groq = GroqClient()
        self.system_monitor = SystemMonitor()
        self.pattern_engine = PatternEngine(
            threshold=self.config["memory"]["pattern_trigger_threshold"]
        )
        self.executor = ActionExecutor(on_pending=self._on_pending, get_tier=lambda: self.permission_tier)
        self.screen_watcher: Optional[ScreenWatcher] = None
        self.observer: Optional[VisionObserver] = None
        self.verifier: Optional[ActionVerifier] = None   # set in lifespan after screen_watcher
        self._last_user_msg_time: float = time.time()
        self.voice_listener = None
        self.ws_clients: list[WebSocket] = []
        self.entity_name = self.config["entity"]["name"]
        self.screen_enabled = self.config["perception"].get("vision_enabled", True)
        self.permission_tier  = self.config["entity"].get("permission_tier", "standard")
        self._has_woken       = False
        self._last_wake_time  = 0.0

        # Name scrub removed in v1.6 -- no hardcoded names in distribution builds.
        # scrub_stale_names() remains available for a future Settings rename flow.

        # Inject persistent memory into LLM on boot
        memory = format_memory_for_llm(limit=8)
        patterns = self.pattern_engine.summary_for_llm()
        combined = "\n\n".join(x for x in [memory, patterns] if x and "No patterns" not in x)
        if combined:
            self.groq.inject_memory(combined)
            print(f"[SOUL] Memory loaded")

    def _on_pending(self, pending: PendingAction):
        asyncio.create_task(self._broadcast({
            "type": "action_pending",
            "action_id": pending.id,
            "action_type": pending.action_type,
            "display_text": pending.display_text
        }))

    async def _broadcast(self, message: dict):
        dead = []
        for ws in self.ws_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for d in dead:
            if d in self.ws_clients:
                self.ws_clients.remove(d)

    async def broadcast(self, msg: dict):
        await self._broadcast(msg)

    async def notify(self, text: str, level: str = "info"):
        await self._broadcast({"type": "notification", "text": text, "level": level})

    async def wake(self, ws: WebSocket):
        """Proactive opening — she speaks first after a brief thinking pause."""
        stats = self.system_monitor.snapshot
        active_task = stats.get("task_label", stats.get("active_app", ""))

        context = {
            "active_app": active_task or stats.get("active_app", "Unknown"),
            "cpu": stats.get("cpu", 0),
            "ram": stats.get("ram", 0),
            "battery": stats.get("battery", "—"),
        }

        # Brief thinking state — feels like she's actually reading the room
        await ws.send_json({"type": "thinking", "active": True})
        await asyncio.sleep(1.8)

        response = await self.groq.wake(context)

        await ws.send_json({"type": "thinking", "active": False})
        await ws.send_json({"type": "assistant_message", "text": response["text"], "is_wake": True})

        save_exchange("assistant", response["text"])

    async def process(self, text: str):
        """User message -> LLM -> response/action."""
        # Track activity time for ambient idle + observer cooldown
        self._last_user_msg_time = time.time()
        if self.observer:
            self.observer.notify_user_active()
        await self.broadcast({"type": "user_message", "text": text})
        await self.broadcast({"type": "thinking", "active": True})

        save_exchange("user", text)

        stats = self.system_monitor.snapshot
        active_task = stats.get("task_label") or stats.get("active_app", "Unknown")
        if self.screen_enabled and self.screen_watcher:
            screen_summary = self.screen_watcher.summary
            import time as _t
            _lvt = getattr(self.screen_watcher, "_last_vision_time", 0)
            # If watcher has never fired (_lvt==0), treat as 20s old (not 1.7 billion)
            # so build_context shows "ON — no fresh screenshot" not "vision pending forever"
            screen_summary_age = (_t.time() - _lvt) if _lvt > 0 else 20
        else:
            screen_summary = ""
            screen_summary_age = 999

        trigger = self.pattern_engine.check_trigger("app_focus", stats.get("active_app", ""))
        if trigger:
            await self.notify(f"Pattern: {trigger['display_text']}", level="pattern")

        self.pattern_engine.observe("voice_command", text, {"app": active_task})

        # ── Screen watcher health check ─────────────────────────────────────
        # Watcher can be _running=True but silently stuck (no new captures).
        # If last capture was >90s ago with screen enabled, restart it.
        if self.screen_enabled and self.screen_watcher:
            import time as _tw
            _lwt = getattr(self.screen_watcher, '_last_vision_time', 0)
            _wstuck = (_tw.time() - _lwt) > 90 if _lwt > 0 else False
            if _wstuck and getattr(self.screen_watcher, '_running', False):
                print("[SOUL] Screen watcher appears stuck, restarting...")
                self.screen_watcher.stop()
                await asyncio.sleep(0.3)
                asyncio.create_task(self.screen_watcher.start())

        _cap_err = ""
        if self.screen_watcher and self.screen_enabled:
            _cap_err = getattr(self.screen_watcher, "capture_error", "")

        context = self.groq.build_context(
            stats=stats,
            screen_summary=screen_summary,
            screen_enabled=self.screen_enabled,
            active_task=active_task,
            pattern_triggers=[trigger["display_text"]] if trigger else [],
            screen_summary_age=screen_summary_age,
            capture_error=_cap_err,
        )

        # ── Streaming response ─────────────────────────────────────────────
        # stream_chat() fires on_token for each chunk → frontend animates in real-time.
        # stream_start tells frontend to create the message bubble and start typing.
        stream_buf = []
        _streaming_started = False

        async def _on_token(tok: str):
            nonlocal _streaming_started
            if not _streaming_started:
                _streaming_started = True
                await self.broadcast({"type": "thinking", "active": False})
                await self.broadcast({"type": "stream_start"})
            stream_buf.append(tok)
            await self.broadcast({"type": "stream_token", "token": tok})

        try:
            response = await self.groq.stream_chat(
                text, context_packet=context, on_token=_on_token)
        except Exception as e:
            err_msg = str(e)
            if "asyncio" in err_msg and "not defined" in err_msg:
                try:
                    from actions.executor import ActionExecutor
                    self.executor = ActionExecutor(
                        on_pending=self._on_pending, get_tier=lambda: self.permission_tier)
                    print("[SOUL] Executor recreated — retrying")
                    response = await self.groq.stream_chat(
                        text, context_packet=context, on_token=_on_token)
                except Exception as _e2:
                    response = {"text": "Action handler restarted. Please try again.", "action": None}
            else:
                response = {"text": f"Something broke: {err_msg[:80]}", "action": None}

        if not _streaming_started:
            await self.broadcast({"type": "thinking", "active": False})

        # Signal stream complete — frontend finalises the bubble
        await self.broadcast({"type": "stream_end", "text": response.get("text", "")})

        save_exchange("assistant", response.get("text", ""))

        actions = response.get("actions") or []
        if not actions and response.get("action"):
            actions = [response["action"]]

        if actions:
            total = len(actions)
            # App weight tables for smarter timing
            _HEAVY = {"chrome","firefox","edge","code","discord","steam","spotify",
                      "obs","photoshop","premiere","blender","slack","teams","zoom"}
            _UWP   = {"calculator","store","photos","mail","calendar","maps",
                       "notepad","snipping tool","xbox","settings","terminal"}
            _LIGHT = {"paint","wordpad","cmd","powershell","terminal"}
            # Result threading: previous step's output available as {prev} / {clipboard} in params
            _ctx: dict           = {}
            _last_focus_ok:   bool = True   # assume focus until proven otherwise
            _last_focus_title: str = ""

            # ── executor_fn: callable for verifier fallbacks ──────────────────
            async def _execute_for_verifier(a: dict) -> dict:
                """Simple one-shot executor call used by ActionVerifier for fallbacks."""
                try:
                    return await self.executor.request(
                        action_type  = a["type"],
                        params       = a.get("params", {}),
                        display_text = a.get("display_text", ""),
                    )
                except Exception as _e:
                    return {"success": False, "message": str(_e)}

            for idx, action in enumerate(actions, 1):
                atype        = action.get("type", "")
                display_text = action.get("display_text", "Performing action…")

                # Resolve context substitutions in params ({prev}, {clipboard}, etc.)
                raw_params = action.get("params", {})
                params: dict = {}
                for k, v in raw_params.items():
                    if isinstance(v, str) and "{" in v and _ctx:
                        for ck, cv in _ctx.items():
                            v = v.replace("{" + ck + "}", str(cv))
                    params[k] = v

                # Broadcast step progress to workspace
                await self.broadcast({
                    "type": "action_step",
                    "step": idx, "total": total,
                    "display_text": display_text
                })

                # Dynamic gap between steps (app-aware)
                if idx > 1:
                    prev_type = actions[idx-2].get("type", "")
                    prev_app  = actions[idx-2].get("params", {}).get("app_name", "").lower()
                    curr_type = atype
                    if prev_type in ("open_app", "open"):
                        if   prev_app in _HEAVY: gap = 4.5
                        elif prev_app in _UWP:   gap = 3.2
                        elif prev_app in _LIGHT: gap = 1.6
                        else:                    gap = 2.8
                    elif curr_type == "type_text":
                        gap = 1.2
                    elif prev_type == "focus_window":
                        gap = 1.0
                    else:
                        gap = 0.6
                    await asyncio.sleep(gap)

                # ── PRE-CAPTURE: snapshot screen before action fires ──────────
                # Verifier needs to know what the screen looked like before.
                # We do this for all verifiable actions regardless of type.
                if self.verifier and atype in VERIFIABLE:
                    await self.verifier.pre_capture()

                # ── EXECUTE ACTION ────────────────────────────────────────────

                if atype == "focus_window":
                    # focus_window: retry up to 3× with backoff (window may not be ready)
                    result = None
                    for _attempt in range(3):
                        try:
                            result = await self.executor.request(
                                action_type=atype,
                                params=params,
                                display_text=display_text
                            )
                        except Exception as _ex:
                            result = {"success": False, "message": str(_ex)}
                        if result.get("success"):
                            _last_focus_ok   = True
                            _last_focus_title = params.get("title", "").lower()
                            break
                        if _attempt < 2:
                            await asyncio.sleep(0.7 * (_attempt + 1))
                    result = result or {"success": False, "message": "focus_window failed"}
                    if not result.get("success"):
                        _last_focus_ok = False

                elif atype == "type_text":
                    # SAFETY: type_text can only reach the target window if focus succeeded.
                    # If focus failed, we'd type into SOUL's own input field — that auto-submits
                    # the text as a fake user message. Re-attempt focus first if needed.
                    target_title = params.get("window_title", "").lower()
                    if target_title and not _last_focus_ok:
                        _refocus = await self.executor.request(
                            action_type="focus_window",
                            params={"title": target_title},
                            display_text=f"Re-focusing {target_title}"
                        )
                        if _refocus.get("success"):
                            _last_focus_ok    = True
                            _last_focus_title = target_title
                            await asyncio.sleep(0.8)
                        else:
                            result = {"success": False,
                                      "message": f"Skipped type_text: window '{target_title}' not in focus"}
                            await self.broadcast({
                                "type": "notification",
                                "text": f"Couldn't focus '{target_title}' — text not typed",
                                "level": "warn"
                            })
                    if _last_focus_ok or not target_title:
                        try:
                            result = await self.executor.request(
                                action_type=atype,
                                params=params,
                                display_text=display_text
                            )
                        except Exception as _ex:
                            result = {"success": False, "message": str(_ex)}

                else:
                    try:
                        result = await self.executor.request(
                            action_type=atype,
                            params=params,
                            display_text=display_text
                        )
                    except Exception as _ex:
                        result = {"success": False, "message": str(_ex)}

                # ── POST-EXECUTE: closed loop verification ────────────────────
                # For verifiable actions: check screen, attempt one fallback if failed,
                # then inject visually-grounded result into LLM history.
                # For unverifiable actions: inject raw executor result as before.

                _used_visual_inject = False

                if self.verifier and self.screen_enabled and atype in VERIFIABLE:
                    final_ok, vr = await self.verifier.verify_and_fallback(
                        action      = {**action, "params": params},
                        executor_ok = result.get("success", False),
                        execute_fn  = _execute_for_verifier,
                    )

                    # If verifier ran a fallback that succeeded, update result so
                    # downstream code (focus tracking, chain-stop) sees the real outcome
                    if final_ok and not result.get("success"):
                        result["success"] = True
                        result["message"] = vr.delta or "succeeded via fallback"

                    # Broadcast visual confirmation info to frontend
                    if vr.visual_confirmed:
                        await self.broadcast({
                            "type":   "action_verified",
                            "step":   idx,
                            "delta":  vr.delta,
                            "fallback_used": vr.fallback_used is not None,
                        })

                    # Update focus-tracking if focus_window succeeded via fallback
                    if atype == "focus_window" and final_ok:
                        _last_focus_ok    = True
                        _last_focus_title = params.get("title", "").lower()
                    elif atype == "focus_window" and not final_ok:
                        _last_focus_ok = False

                    # Inject visually-grounded result into LLM history
                    self.groq.inject_visual_result({**action, "params": params}, result, vr)
                    _used_visual_inject = True

                # Thread result value into context for subsequent steps
                for _key in ("content", "value", "data", "text", "message"):
                    _val = result.get(_key)
                    if _val and isinstance(_val, str) and not _val.startswith("__"):
                        _ctx["prev"] = _val
                        if _key == "content":
                            _ctx["clipboard"] = _val
                        break

                # Handle special toggle_screen_capture result
                msg_val = result.get("message", "")
                if isinstance(msg_val, str) and msg_val.startswith("__TOGGLE_SCREEN_CAPTURE__:"):
                    requested = msg_val.split(":")[-1]
                    new_state = False if requested == "False" else (
                        True if requested == "True" else (not self.screen_enabled))
                    self.screen_enabled = new_state
                    cfg = load_config()
                    cfg["perception"]["vision_enabled"] = new_state
                    save_config(cfg)
                    if new_state:
                        if self.screen_watcher and not self.screen_watcher._running:
                            asyncio.create_task(self.screen_watcher.start())
                        if self.screen_watcher and not self.observer:
                            self.observer = VisionObserver(
                                groq_client         = self.groq,
                                screen_watcher      = self.screen_watcher,
                                get_last_user_time  = lambda: self._last_user_msg_time,
                                get_ws_clients      = lambda: self.ws_clients,
                                broadcast           = self.broadcast,
                                get_screen_enabled  = lambda: self.screen_enabled,
                                save_exchange_fn    = save_exchange,
                                get_current_context = lambda: next(
                                    (m["content"] for m in reversed(self.groq.conversation_history)
                                     if m.get("role") == "assistant"), ""
                                ),
                            )
                            asyncio.create_task(self.observer.start())
                        # Update verifier's screen reference
                        if self.verifier and self.screen_watcher:
                            self.verifier.screen = self.screen_watcher
                    else:
                        if self.screen_watcher:
                            self.screen_watcher.stop()
                        if self.observer:
                            self.observer.stop()
                            self.observer = None
                        if self.verifier:
                            self.verifier.screen = None
                    result["message"] = f"Screen capture {'enabled' if new_state else 'disabled'}"
                    result["success"] = True
                    await self.broadcast({"type": "screen_toggled", "enabled": new_state})

                await self.broadcast({
                    "type": "action_result",
                    "result": result,
                    "step": idx,
                    "total": total
                })

                # ── Inject into LLM history (non-visual path) ─────────────────
                # Visual injection already done above for verifiable actions.
                # This block handles data-read actions and unverifiable exec actions.
                if not _used_visual_inject:
                    _DATA_ACTIONS = {
                        "get_running_processes", "get_system_info", "check_battery",
                        "get_time", "read_file", "read_clipboard", "web_search",
                    }
                    _EXEC_ACTIONS = {
                        "open_app", "close_app", "focus_window", "type_text",
                        "press_keys", "play_media", "run_command", "kill_process",
                        "create_file", "write_file", "open_folder", "open_url",
                        "lock_screen", "set_volume", "take_screenshot",
                        "rename_file", "delete_file", "copy_to_clipboard",
                    }

                    if atype in _DATA_ACTIONS and result.get("success"):
                        _result_text = (result.get("content")
                                        or result.get("data")
                                        or result.get("message")
                                        or result.get("text", ""))
                        if _result_text:
                            self.groq.inject_action_result(atype, str(_result_text))

                    elif atype in _EXEC_ACTIONS:
                        _ok   = result.get("success", False)
                        _msg  = (result.get("message") or result.get("text") or
                                 result.get("content") or ("OK" if _ok else "Failed"))
                        _label = action.get("display_text") or atype
                        self.groq.inject_action_result(
                            atype, f"[ACTION {'OK' if _ok else 'FAILED'}] {_label}: {_msg}")

                # Stop chain on failure (unless it's an info step)
                if not result.get("success") and not result.get("auto") and total > 1:
                    if atype not in ("get_running_processes","get_system_info","check_battery","get_time"):
                        break


state = SOULState()
_last_wake_time: float = 0.0   # unix timestamp of last proactive wake
_WAKE_COOLDOWN_SEC = 900        # 15 minutes minimum between wake messages



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Collect stats NOW before any WebSocket connects
    state.system_monitor.collect_now()
    asyncio.create_task(state.system_monitor.start())

    if state.config["perception"]["vision_enabled"]:
        state.screen_watcher = ScreenWatcher(state.groq, thumb_interval=2, vision_interval=6)
        asyncio.create_task(state.screen_watcher.start())

    # ── Action Verifier — closed loop between eyes and hands ────────────────
    # Created with whatever screen_watcher we have (may be None if vision off).
    # The verifier degrades gracefully: if screen is None, all verifications
    # skip visual check and trust executor return values directly.
    state.verifier = ActionVerifier(
        screen_watcher = state.screen_watcher,
        groq_client    = state.groq,
    )
    print(f"[SOUL] Action verifier ready (vision={'on' if state.screen_watcher else 'off'})")

    # ── Vision Observer — eyes + proactive awareness loop ───────────────────
    if state.config["perception"]["vision_enabled"] and state.screen_watcher:
        state.observer = VisionObserver(
            groq_client         = state.groq,
            screen_watcher      = state.screen_watcher,
            get_last_user_time  = lambda: state._last_user_msg_time,
            get_ws_clients      = lambda: state.ws_clients,
            broadcast           = state.broadcast,
            get_screen_enabled  = lambda: state.screen_enabled,
            save_exchange_fn    = save_exchange,
            get_current_context = lambda: next(
                (m["content"] for m in reversed(state.groq.conversation_history)
                 if m.get("role") == "assistant"), ""
            ),
        )
        asyncio.create_task(state.observer.start())
        print("[SOUL] Vision observer started")

    # Try to initialise SOUL's virtual workdesk (best-effort — no crash if unavailable)
    try:
        from executor import init_workdesk
        _desk = init_workdesk()
        if _desk >= 0:
            print(f"[SOUL] Workdesk ready at desktop index {_desk}")
        else:
            print("[SOUL] Workdesk not available — running in single-desktop mode")
    except Exception as _e:
        print(f"[SOUL] Workdesk init skipped: {_e}")

    from config import CONFIG_PATH
    print(f"[SOUL] Config: {CONFIG_PATH} (exists={CONFIG_PATH.exists()})")
    print(f"[SOUL] {state.entity_name} is online. Model: {state.groq.active_model}")
    yield

    state.system_monitor.stop()
    if state.observer:
        state.observer.stop()
    if state.screen_watcher:
        state.screen_watcher.stop()



app = FastAPI(title="SOUL", lifespan=lifespan)


@app.post("/reset")
async def reset_all():
    """
    Fresh slate: wipe config, memory DB, and in-memory state.
    Electron reloads to onboarding.html after calling this.
    """
    from config import CONFIG_PATH
    from pathlib import Path as _P
    import os as _os

    wiped  = []
    errors = []

    # 1. Delete config
    try:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
            wiped.append("config")
    except Exception as e:
        errors.append(f"config: {e}")

    # 2. Delete memory DB (+ SQLite WAL/SHM side files)
    try:
        cfg      = state.config
        db_name  = cfg.get("memory", {}).get("db_path", "soul_memory.db")
        data_dir = _os.environ.get("SOUL_DATA_DIR", "").strip()
        db_path  = _P(data_dir) / db_name if data_dir else _P(__file__).parent.parent / db_name
        for ext in ["", "-wal", "-shm"]:
            p = _P(str(db_path) + ext) if ext else db_path
            if p.exists():
                p.unlink()
        wiped.append("memory_db")
    except Exception as e:
        errors.append(f"memory_db: {e}")

    # 3. Reset in-memory LLM state
    state.groq.reset()
    state.groq.conversation_history = []

    # 4. Reset config to defaults (in-memory — file is already gone)
    state.config      = DEFAULT_CONFIG.copy()
    state.groq.config = state.config
    state.entity_name = state.config["entity"]["name"]

    print(f"[SOUL] Reset complete. Wiped: {wiped}. Errors: {errors}")
    return {"success": True, "wiped": wiped, "errors": errors}


@app.get("/export-log")
async def export_log():
    from memory.patterns import get_db
    from fastapi.responses import PlainTextResponse
    conn = get_db()
    rows = conn.execute(
        "SELECT timestamp, role, content FROM session_history ORDER BY id ASC"
    ).fetchall()
    conn.close()
    cfg  = load_config()
    name = cfg["entity"].get("name", "SOUL")
    user = cfg["entity"].get("user_name", "User")
    now  = __import__("datetime").datetime.now()
    lines = [f"# {name} Debug Chat Log",
             f"Exported: {now.strftime('%Y-%m-%d %H:%M:%S')}",
             f"Entity: {name}  |  User: {user}", "---", ""]
    for r in rows:
        ts   = r["timestamp"][:19].replace("T", " ")
        role = name if r["role"] == "assistant" else user
        lines.append(f"[{ts}] **{role}**")
        lines.append(r["content"])
        lines.append("")
    fname = f"soul_log_{now.strftime('%Y%m%d_%H%M%S')}.md"
    return PlainTextResponse("\n".join(lines), media_type="text/markdown",
                              headers={"Content-Disposition": f'attachment; filename="{fname}"'})
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.ws_clients.append(websocket)

    # Send init metadata
    import os as _os
    stats = state.system_monitor.snapshot
    computer_name = _os.environ.get("COMPUTERNAME", "") or _os.environ.get("HOSTNAME", "") or ""
    # Get pronoun object for input placeholder
    from config import load_config as _lc2
    _pronouns = _lc2()["entity"].get("pronouns", "she/her")
    _obj_map = {"she/her": "her", "he/him": "him", "they/them": "them", "it/its": "it"}
    _pron_object = _obj_map.get(_pronouns, "her")

    await websocket.send_json({
        "type": "init",
        "entity_name": state.entity_name,
        "screen_enabled": state.screen_enabled,
        "active_model": state.groq.active_model,
        "task_label": stats.get("task_label", ""),
        "stats": stats,
        "computer_name": computer_name,
        "pronoun_object": _pron_object,
    })

    # She speaks first — but only once per 15 minutes
    global _last_wake_time
    import time as _time
    if not is_first_run() and (_time.time() - _last_wake_time) > _WAKE_COOLDOWN_SEC:
        _last_wake_time = _time.time()
        asyncio.create_task(state.wake(websocket))

    try:
        while True:
            data = await websocket.receive_json()
            await _handle(data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[SOUL] WS error: {e}")
    finally:
        if websocket in state.ws_clients:
            state.ws_clients.remove(websocket)


async def _handle(data: dict):
    t = data.get("type")
    if t == "user_text":
        text = data.get("text", "").strip()
        if text:
            # MUST be a task — process() can block waiting for action confirmation
            # If we await directly, WS loop can't receive action_confirm -> deadlock
            asyncio.create_task(state.process(text))
    elif t == "action_confirm":
        state.executor.confirm(data.get("action_id", ""))
    elif t == "action_reject":
        state.executor.reject(data.get("action_id", ""))
    elif t == "system_status":
        thumb = state.screen_watcher.thumbnail_b64 if state.screen_watcher else ""
        await state.broadcast({"type": "system_stats",
                                "stats": state.system_monitor.snapshot,
                                "thumbnail": thumb})
    elif t == "toggle_screen":
        enabled = data.get("enabled", True)
        state.screen_enabled = enabled
        cfg = load_config()
        cfg["perception"]["vision_enabled"] = enabled
        save_config(cfg)
        if enabled:
            # Restart watcher if not running
            if state.screen_watcher:
                if not state.screen_watcher._running:
                    asyncio.create_task(state.screen_watcher.start())
            else:
                state.screen_watcher = ScreenWatcher(state.groq, thumb_interval=2, vision_interval=6)
                asyncio.create_task(state.screen_watcher.start())
            # Restart observer with full context wiring (Brain->Eyes link)
            if state.screen_watcher and not state.observer:
                state.observer = VisionObserver(
                    groq_client         = state.groq,
                    screen_watcher      = state.screen_watcher,
                    get_last_user_time  = lambda: state._last_user_msg_time,
                    get_ws_clients      = lambda: state.ws_clients,
                    broadcast           = state.broadcast,
                    get_screen_enabled  = lambda: state.screen_enabled,
                    save_exchange_fn    = save_exchange,
                    get_current_context = lambda: next(
                        (m["content"] for m in reversed(state.groq.conversation_history)
                         if m.get("role") == "assistant"), ""
                    ),
                )
                asyncio.create_task(state.observer.start())
            # Sync verifier with new screen_watcher
            if state.verifier:
                state.verifier.screen = state.screen_watcher
        else:
            # Stop watcher + observer immediately
            if state.screen_watcher:
                state.screen_watcher.stop()
                state.screen_watcher.thumbnail_b64 = ""
                state.screen_watcher.summary = ""
            if state.observer:
                state.observer.stop()
                state.observer = None
            # Verifier degrades gracefully with screen=None
            if state.verifier:
                state.verifier.screen = None
        await state.broadcast({"type": "screen_toggled", "enabled": enabled})
    elif t == "clear_history":
        state.groq.reset()
        memory = format_memory_for_llm(limit=4)
        if memory:
            state.groq.inject_memory(memory)
    elif t == "set_permission_tier":
        tier = data.get("tier", "standard")
        state.permission_tier = tier
        cfg = load_config()
        cfg["entity"]["permission_tier"] = tier
        save_config(cfg)
        await state.broadcast({"type": "tier_changed", "tier": tier})
    elif t == "ping":
        await state.broadcast({"type": "pong"})


# ── REST ──────────────────────────────────────

@app.get("/processes")
async def get_processes():
    """Top 8 processes by RAM for workspace widget."""
    import psutil
    procs = []
    for p in psutil.process_iter(["name","cpu_percent","memory_percent","pid"]):
        try:
            info = p.info
            if info["memory_percent"] and info["memory_percent"] > 0.1:
                procs.append(info)
        except Exception:
            pass
    procs.sort(key=lambda x: x.get("memory_percent", 0), reverse=True)
    return {"processes": procs[:8]}

@app.get("/status")
async def status():
    import os as _os
    return {
        "online": True,
        "entity_name": state.entity_name,
        "active_model": state.groq.active_model,
        "screen_enabled": state.screen_enabled,
        "system": state.system_monitor.snapshot,
        "patterns": len(state.pattern_engine.get_active_patterns()),
        "computer_name": _os.environ.get("COMPUTERNAME", "") or _os.environ.get("HOSTNAME", ""),
    }

@app.get("/config")
async def get_config():
    return state.config

@app.post("/config")
async def update_config(body: dict):
    cfg = load_config()
    for section, vals in body.items():
        if section in cfg and isinstance(cfg[section], dict):
            cfg[section].update(vals)
        else:
            cfg[section] = vals
    save_config(cfg)
    state.config = cfg
    state.entity_name = cfg["entity"]["name"]
    return {"success": True}

@app.post("/onboarding")
async def onboarding(body: dict):
    cfg = DEFAULT_CONFIG.copy()
    cfg["entity"].update({
        "name": body.get("name", "SOUL"),
        "pronouns": body.get("pronouns", "she/her"),
        "avatar_theme": "nebula",
        "voice_preset": "calm_feminine",
        "user_name": body.get("user_name", ""),
        "device_name": body.get("device_name", ""),
        "directness": body.get("directness", "direct"),
        "proactivity": body.get("proactivity", "speaks_up"),
        "focus": body.get("focus", "mixed"),
    })
    save_config(cfg)
    state.config = cfg
    state.entity_name = cfg["entity"]["name"]
    state.groq.config = cfg
    return {"success": True, "name": state.entity_name}

@app.post("/action/{action_id}/confirm")
async def confirm(action_id: str):
    state.executor.confirm(action_id)
    return {"confirmed": True}

@app.post("/action/{action_id}/reject")
async def reject(action_id: str):
    state.executor.reject(action_id)
    return {"rejected": True}

@app.get("/memory")
async def memory():
    return {"history": format_memory_for_llm(10),
            "patterns": state.pattern_engine.get_active_patterns()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
