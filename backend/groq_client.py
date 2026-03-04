"""
SOUL — Groq LLM Client
"""

import os
import json
import re
import httpx
from config import load_config, get_system_prompt, get_wake_prompt

GROQ_API_BASE = "https://api.groq.com/openai/v1"

MODEL_CHAIN = [
    "llama-3.3-70b-versatile",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]


class GroqClient:
    def __init__(self):
        self.config = load_config()
        raw = os.environ.get("GROQ_API_KEY", "").strip()
        self.api_key = "" if (not raw or raw.startswith("your_") or raw == "paste_your_key_here") else raw
        if not self.api_key:
            print("[SOUL] WARNING: GROQ_API_KEY not set — https://console.groq.com")
        self.active_model = MODEL_CHAIN[0]
        self.conversation_history = []

    def build_context(self, stats: dict, screen_summary: str, screen_enabled: bool,
                      active_task: str, pattern_triggers: list) -> str:
        lines = [f"[LIVE — {__import__('datetime').datetime.now().strftime('%H:%M')}]"]
        lines.append(f"Task: {active_task or 'Unknown'}")
        if screen_enabled and screen_summary:
            lines.append(f"Screen: {screen_summary}")
        lines.append(f"CPU {stats.get('cpu',0):.0f}% · RAM {stats.get('ram',0):.0f}% · "
                     f"GPU {stats.get('gpu','—')} · "
                     f"Net ↑{stats.get('net_sent','0')} ↓{stats.get('net_recv','0')} · "
                     f"Battery {stats.get('battery','—')}")
        if stats.get('disk_read') or stats.get('disk_write'):
            lines.append(f"Disk R:{stats.get('disk_read','0')} W:{stats.get('disk_write','0')}")
        if pattern_triggers:
            lines.append(f"Patterns: {', '.join(pattern_triggers)}")
        return "\n".join(lines)

    async def wake(self, context: dict) -> dict:
        """Generate proactive opening message when user opens SOUL."""
        if not self.api_key:
            return {"text": "API key not configured. Add GROQ_API_KEY to your .env file.", "action": None}

        from memory.patterns import format_memory_for_llm
        memory = format_memory_for_llm(limit=4)
        context["memory_context"] = memory

        prompt = get_wake_prompt(self.config, context)
        messages = [
            {"role": "system", "content": get_system_prompt(self.config)},
            {"role": "user", "content": prompt}
        ]

        result = await self._call(messages, max_tokens=120, temperature=0.9)
        if result.get("success"):
            text = result["text"].strip()
            # Store wake message in history so she remembers the opening
            self.conversation_history.append({"role": "assistant", "content": text})
            return {"text": text, "action": None}
        return {"text": result.get("error", "..."), "action": None}

    async def chat(self, user_message: str, context_packet: str = "",
                   max_tokens: int = None) -> dict:
        if not self.api_key:
            return {"text": "No API key. Add GROQ_API_KEY to .env and restart.", "action": None}

        messages = [{"role": "system", "content": get_system_prompt(self.config)}]
        if context_packet:
            messages.append({"role": "system", "content": context_packet})
        messages.extend(self.conversation_history[-14:])
        messages.append({"role": "user", "content": user_message})

        result = await self._call(messages, max_tokens=max_tokens)
        if result.get("success"):
            raw = result["text"]
            self.conversation_history.append({"role": "user", "content": user_message})
            self.conversation_history.append({"role": "assistant", "content": raw})
            if len(self.conversation_history) > 40:
                self.conversation_history = self.conversation_history[-40:]
            return self._parse(raw)
        return {"text": result.get("error", "Something went wrong."), "action": None}

    async def _call(self, messages: list, max_tokens: int = None,
                    temperature: float = None) -> dict:
        cfg_temp = self.config["llm"]["temperature"]
        cfg_tokens = self.config["llm"]["max_tokens"]
        models = [self.active_model] + [m for m in MODEL_CHAIN if m != self.active_model]

        for model in models:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens or cfg_tokens,
                    "temperature": temperature if temperature is not None else cfg_temp,
                }
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.post(
                        f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "Content-Type": "application/json"},
                        json=payload
                    )
                    r.raise_for_status()
                    data = r.json()

                if model != self.active_model:
                    print(f"[SOUL] Model switched to {model}")
                    self.active_model = model

                return {"success": True, "text": data["choices"][0]["message"]["content"]}

            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 400:
                    print(f"[SOUL] {model} → 400, trying next...")
                    continue
                elif code == 401:
                    return {"success": False, "error": "API key rejected. Check .env file."}
                elif code == 429:
                    return {"success": False, "error": "Rate limited — give me a moment."}
                else:
                    continue
            except httpx.TimeoutException:
                return {"success": False, "error": "Request timed out."}
            except Exception as e:
                print(f"[SOUL] {model} error: {e}")
                continue

        return {"success": False, "error": "All models unavailable. Check connection."}

    async def vision_query(self, image_base64: str, prompt: str = "") -> str:
        if not self.api_key:
            return "Vision disabled"
        for model in ["llama-3.2-11b-vision-preview", "llava-v1.5-7b-4096-preview"]:
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        {"type": "text",
                         "text": prompt or "What app is active and what is the user doing? One sentence, specific."}
                    ]}],
                    "max_tokens": 100
                }
                async with httpx.AsyncClient(timeout=20) as client:
                    r = await client.post(
                        f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}",
                                 "Content-Type": "application/json"},
                        json=payload
                    )
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"]
            except Exception:
                continue
        return "Screen vision unavailable"

    def _parse(self, raw: str) -> dict:
        action = None
        match = re.search(r"<ACTION>(.*?)</ACTION>", raw, re.DOTALL)
        if match:
            try:
                action = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass
            text = re.sub(r"<ACTION>.*?</ACTION>", "", raw, flags=re.DOTALL).strip()
        else:
            text = raw.strip()
        return {"text": text, "action": action}

    def reset(self):
        self.conversation_history = []

    def inject_memory(self, summary: str):
        if summary:
            self.conversation_history.insert(0, {
                "role": "system",
                "content": f"[MEMORY FROM PREVIOUS SESSIONS]\n{summary}"
            })
