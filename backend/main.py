"""
SOUL — Main Server
Proactive wake on connect, full context pipeline, screen toggle, notification broadcast.
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

from config import load_config, save_config, is_first_run, DEFAULT_CONFIG
from groq_client import GroqClient
from perception.system import ScreenWatcher, SystemMonitor
from actions.executor import ActionExecutor, PendingAction
from memory.patterns import PatternEngine, format_memory_for_llm, save_exchange, scrub_stale_names


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
        self.voice_listener = None
        self.ws_clients: list[WebSocket] = []
        self.entity_name = self.config["entity"]["name"]
        self.screen_enabled = self.config["perception"].get("vision_enabled", True)
        self.permission_tier = self.config["entity"].get("permission_tier", "standard")

        # Scrub stale names from previous sessions before loading memory
        # Any name that's no longer the configured user_name gets purged
        _current_user = self.config["entity"].get("user_name", "")
        _stale_names = [n for n in ["Aryan", "aryan"] if n.lower() != _current_user.lower()]
        if _stale_names:
            scrub_stale_names(_stale_names)
            print(f"[SOUL] Scrubbed stale names from memory: {_stale_names}")

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
            self.ws_clients.discard(d) if hasattr(self.ws_clients, 'discard') else None
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
        await self.broadcast({"type": "user_message", "text": text})
        await self.broadcast({"type": "thinking", "active": True})

        save_exchange("user", text)

        stats = self.system_monitor.snapshot
        active_task = stats.get("task_label") or stats.get("active_app", "Unknown")
        if self.screen_enabled and self.screen_watcher:
            screen_summary = self.screen_watcher.summary
            import time as _t
            screen_summary_age = _t.time() - getattr(self.screen_watcher, "_last_vision_time", 0)
        else:
            screen_summary = ""
            screen_summary_age = 999

        trigger = self.pattern_engine.check_trigger("app_focus", stats.get("active_app", ""))
        if trigger:
            await self.notify(f"Pattern: {trigger['display_text']}", level="pattern")

        self.pattern_engine.observe("voice_command", text, {"app": active_task})

        context = self.groq.build_context(
            stats=stats,
            screen_summary=screen_summary,
            screen_enabled=self.screen_enabled,
            active_task=active_task,
            pattern_triggers=[trigger["display_text"]] if trigger else [],
            screen_summary_age=screen_summary_age
        )

        try:
            response = await self.groq.chat(text, context_packet=context)
        except Exception as e:
            response = {"text": f"Something broke: {str(e)[:80]}", "action": None}

        await self.broadcast({"type": "thinking", "active": False})
        await self.broadcast({"type": "assistant_message", "text": response["text"]})

        save_exchange("assistant", response["text"])

        actions = response.get("actions") or []
        if not actions and response.get("action"):
            actions = [response["action"]]

        if actions:
            total = len(actions)
            for idx, action in enumerate(actions, 1):
                atype        = action.get("type", "")
                display_text = action.get("display_text", "Performing action…")

                # Broadcast step progress to workspace
                await self.broadcast({
                    "type": "action_step",
                    "step": idx, "total": total,
                    "display_text": display_text
                })

                # Dynamic gap between steps
                if idx > 1:
                    prev_type = actions[idx-2].get("type", "")
                    curr_type = atype
                    if prev_type in ("open_app", "open"):
                        gap = 2.8   # app needs time to render
                    elif curr_type == "type_text":
                        gap = 1.2   # extra settle before typing
                    elif prev_type == "focus_window":
                        gap = 1.0   # focus needs to land before next step
                    else:
                        gap = 0.6
                    await asyncio.sleep(gap)

                result = await self.executor.request(
                    action_type=atype,
                    params=action.get("params", {}),
                    display_text=display_text
                )

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
                    else:
                        if self.screen_watcher:
                            self.screen_watcher.stop()
                    result["message"] = f"Screen capture {'enabled' if new_state else 'disabled'}"
                    result["success"] = True
                    await self.broadcast({"type": "screen_toggled", "enabled": new_state})

                await self.broadcast({
                    "type": "action_result",
                    "result": result,
                    "step": idx,
                    "total": total
                })

                # For auto multi-step: only broadcast text on final step
                # (intermediate step results are visible in workspace, not chat)
                if result.get("auto") and total > 1 and idx < total:
                    # suppress intermediate step messages from chat — workspace shows them
                    pass

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

    from config import CONFIG_PATH
    print(f"[SOUL] Config: {CONFIG_PATH} (exists={CONFIG_PATH.exists()})")
    print(f"[SOUL] {state.entity_name} is online. Model: {state.groq.active_model}")
    yield

    state.system_monitor.stop()
    if state.screen_watcher:
        state.screen_watcher.stop()


app = FastAPI(title="SOUL", lifespan=lifespan)


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
        else:
            # Stop watcher immediately
            if state.screen_watcher:
                state.screen_watcher.stop()
                state.screen_watcher.thumbnail_b64 = ""
                state.screen_watcher.summary = ""
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
