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
from memory.patterns import PatternEngine, format_memory_for_llm, save_exchange


class SOULState:
    def __init__(self):
        self.config = load_config()
        self.groq = GroqClient()
        self.system_monitor = SystemMonitor()
        self.pattern_engine = PatternEngine(
            threshold=self.config["memory"]["pattern_trigger_threshold"]
        )
        self.executor = ActionExecutor(on_pending=self._on_pending)
        self.screen_watcher: Optional[ScreenWatcher] = None
        self.voice_listener = None
        self.ws_clients: list[WebSocket] = []
        self.entity_name = self.config["entity"]["name"]
        self.screen_enabled = self.config["perception"].get("vision_enabled", True)

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
        """User message → LLM → response/action."""
        await self.broadcast({"type": "user_message", "text": text})
        await self.broadcast({"type": "thinking", "active": True})

        save_exchange("user", text)

        stats = self.system_monitor.snapshot
        active_task = stats.get("task_label") or stats.get("active_app", "Unknown")
        screen_summary = (self.screen_watcher.summary
                          if self.screen_enabled and self.screen_watcher else "")

        trigger = self.pattern_engine.check_trigger("app_focus", stats.get("active_app", ""))
        if trigger:
            await self.notify(f"Pattern: {trigger['display_text']}", level="pattern")

        self.pattern_engine.observe("voice_command", text, {"app": active_task})

        context = self.groq.build_context(
            stats=stats,
            screen_summary=screen_summary,
            screen_enabled=self.screen_enabled,
            active_task=active_task,
            pattern_triggers=[trigger["display_text"]] if trigger else []
        )

        try:
            response = await self.groq.chat(text, context_packet=context)
        except Exception as e:
            response = {"text": f"Something broke: {str(e)[:80]}", "action": None}

        await self.broadcast({"type": "thinking", "active": False})
        await self.broadcast({"type": "assistant_message", "text": response["text"]})

        save_exchange("assistant", response["text"])

        if response.get("action"):
            action = response["action"]
            result = await self.executor.request(
                action_type=action.get("type", ""),
                params=action.get("params", {}),
                display_text=action.get("display_text", "Performing action…")
            )
            await self.broadcast({"type": "action_result", "result": result})


state = SOULState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(state.system_monitor.start())

    if state.config["perception"]["vision_enabled"]:
        state.screen_watcher = ScreenWatcher(
            state.groq,
            interval_sec=state.config["perception"]["screen_capture_interval_sec"]
        )
        asyncio.create_task(state.screen_watcher.start())

    print(f"[SOUL] {state.entity_name} is online. Model: {state.groq.active_model}")
    yield

    state.system_monitor.stop()
    if state.screen_watcher:
        state.screen_watcher.stop()


app = FastAPI(title="SOUL", lifespan=lifespan)
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
    await websocket.send_json({
        "type": "init",
        "entity_name": state.entity_name,
        "screen_enabled": state.screen_enabled,
        "active_model": state.groq.active_model,
        "task_label": stats.get("task_label", ""),
        "stats": stats,
        "computer_name": computer_name,
    })

    # She speaks first — proactive wake
    if not is_first_run():
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
            await state.process(text)
    elif t == "action_confirm":
        state.executor.confirm(data.get("action_id", ""))
    elif t == "action_reject":
        state.executor.reject(data.get("action_id", ""))
    elif t == "system_status":
        await state.broadcast({"type": "system_stats", "stats": state.system_monitor.snapshot})
    elif t == "toggle_screen":
        state.screen_enabled = data.get("enabled", True)
        cfg = load_config()
        cfg["perception"]["vision_enabled"] = state.screen_enabled
        save_config(cfg)
        await state.broadcast({"type": "screen_toggled", "enabled": state.screen_enabled})
    elif t == "clear_history":
        state.groq.reset()
        memory = format_memory_for_llm(limit=4)
        if memory:
            state.groq.inject_memory(memory)
    elif t == "ping":
        await state.broadcast({"type": "pong"})


# ── REST ──────────────────────────────────────

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
