"""
SOUL — Groq LLM Client
"""

import os
import json
import re
import asyncio
import httpx
from config import load_config, get_system_prompt, get_wake_prompt

GROQ_API_BASE = "https://api.groq.com/openai/v1"

MODEL_CHAIN = [
    "llama-3.3-70b-versatile",      # primary (128k ctx, latest)
    "llama-3.1-8b-instant",         # fast fallback (128k ctx)
    "gemma2-9b-it",                  # last resort
]


class GroqClient:
    def __init__(self):
        self.config = load_config()
        raw = os.environ.get("GROQ_API_KEY", "").strip()
        self.api_key = "" if (not raw or raw.startswith("your_") or raw == "paste_your_key_here") else raw
        if not self.api_key:
            print("[SOUL] WARNING: GROQ_API_KEY not set — https://console.groq.com")


    def build_context(self, stats: dict, screen_summary: str, screen_enabled: bool,
                      active_task: str, pattern_triggers: list,
                      screen_summary_age: float = 0) -> str:
        import datetime as _dt
        lines = [f"[{_dt.datetime.now().strftime('%H:%M')}]"]
        if active_task:
            lines.append(f"Active: {active_task}")

        # Screen vision — explicit state always sent so LLM never guesses
        if not screen_enabled:
            lines.append("Screen: OFF — cannot see screen. NEVER describe or guess screen content.")
        elif screen_summary and screen_summary_age < 30 and not screen_summary.startswith("Screen unavail"):
            lines.append(f"Screen: {screen_summary}")
        else:
            lines.append("Screen: ON but vision pending — NEVER describe or guess screen content.")

        # Stats — only inject the numbers silently, don't highlight normal values
        # The LLM should NOT be prompted to comment on these unless critical
        bat = stats.get('battery', '—')
        ram = stats.get('ram', 0)
        cpu = stats.get('cpu', 0)

        stat_parts = [f"CPU:{cpu:.0f}% RAM:{ram:.0f}%"]
        if bat not in ('—', 'N/A', None):
            stat_parts.append(f"BAT:{bat}")

        # Only surface alerts for critical thresholds
        alerts = []
        if isinstance(ram, (int, float)) and ram > 97:
            alerts.append(f"ALERT: RAM critically full at {ram:.0f}%")
        if isinstance(bat, str) and bat.endswith('%'):
            try:
                bat_val = int(bat.rstrip('%'))
                if bat_val < 5:
                    alerts.append(f"ALERT: Battery at {bat_val}%, plug in now")
            except ValueError:
                pass

        lines.append(" | ".join(stat_parts))
        lines.extend(alerts)

        if pattern_triggers:
            lines.append(f"Pattern: {', '.join(pattern_triggers)}")

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
            messages.append({"role": "system", "content": f"<context>\n{context_packet}\n</context>"})
        messages.extend(self.conversation_history[-14:])
        messages.append({"role": "user", "content": user_message})

        result = await self._call(messages, max_tokens=max_tokens)
        if result.get("success"):
            raw = result["text"].strip()

            # Guard: if LLM returned empty, prune stale blank entries and retry
            if not raw:
                # Strip any trailing blank assistant turns — they train the model to return empty
                self.conversation_history = [
                    m for m in self.conversation_history
                    if not (m["role"] == "assistant" and not m["content"].strip())
                ]
                retry_messages = [{"role": "system", "content": get_system_prompt(self.config)}]
                retry_messages += self.conversation_history[-10:]
                retry_messages.append({"role": "user", "content": user_message})
                retry_messages.append({"role": "user",
                    "content": "Please reply. Even a single sentence. Do not return empty."})
                r2 = await self._call(retry_messages, max_tokens=max_tokens)
                raw = r2["text"].strip() if r2.get("success") and r2["text"].strip() else "..."

            # NEVER save blank to history — it teaches the model empty is acceptable
            if raw and raw != "...":
                self.conversation_history.append({"role": "user", "content": user_message})
                self.conversation_history.append({"role": "assistant", "content": raw})
            else:
                # Still record the user turn so context isn't lost, but no blank assistant
                self.conversation_history.append({"role": "user", "content": user_message})

            if len(self.conversation_history) > 40:
                self.conversation_history = self.conversation_history[-40:]
            return self._parse(raw)
        return {"text": result.get("error", "Something went wrong."), "action": None}

    async def _call(self, messages: list, max_tokens: int = None,
                    temperature: float = None) -> dict:
        cfg      = load_config()  # fresh read so token/temp changes take effect
        cfg_temp   = cfg["llm"].get("temperature", 0.85)
        cfg_tokens = cfg["llm"].get("max_tokens", 1024)
        models = [self.active_model] + [m for m in MODEL_CHAIN if m != self.active_model]

        if not self._api_keys:
            return {"success": False, "error": "No API key configured. Add GROQ_API_KEY to .env"}

        # Try each model; on 429 rotate to next key before retrying
        for model in models:
            # Try all available keys for this model before giving up
            keys_tried = 0
            start_idx = self._key_index
            while keys_tried < len(self._api_keys):
                api_key = self._next_key()
                keys_tried += 1
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
                            headers={"Authorization": f"Bearer {api_key}",
                                     "Content-Type": "application/json"},
                            json=payload
                        )
                        r.raise_for_status()
                        data = r.json()

                    if model != self.active_model:
                        print(f"[SOUL] Model switched to {model}")
                        self.active_model = model
                        try:
                            from config import load_config as _lc, save_config as _sc
                            _cfg = _lc()
                            _cfg["llm"]["preferred_model"] = model
                            _sc(_cfg)
                        except Exception:
                            pass

                    return {"success": True, "text": data["choices"][0]["message"]["content"]}

                except httpx.HTTPStatusError as e:
                    code = e.response.status_code
                    if code == 400:
                        print(f"[SOUL] {model} -> 400: {e.response.text[:120]}")
                        break  # malformed request — no point retrying with another key
                    elif code == 401:
                        print(f"[SOUL] Key rejected (401) — trying next key")
                        continue  # try next key
                    elif code == 429:
                        if keys_tried < len(self._api_keys):
                            print(f"[SOUL] Rate limited — rotating to next key ({keys_tried+1}/{len(self._api_keys)})")
                            continue  # try next key immediately
                        else:
                            # All keys rate-limited — wait then retry this model
                            retry_after = int(e.response.headers.get("retry-after", "6"))
                            retry_after = max(3, min(retry_after, 15))
                            print(f"[SOUL] All keys rate-limited on {model}, waiting {retry_after}s...")
                            await asyncio.sleep(retry_after)
                            break  # move to next model
                    else:
                        break
                except httpx.TimeoutException:
                    return {"success": False, "error": "Request timed out."}
                except Exception as e:
                    print(f"[SOUL] {model} error: {e}")
                    break

        return {"success": False, "error": "All models unavailable. Check connection."}

    async def vision_query(self, image_base64: str, prompt: str = "") -> str:
        if not self.api_key:
            return "Vision disabled"
        # Verified active Groq vision models (2025-2026)
        for model in ["llama-3.2-90b-vision-preview", "llama-3.2-11b-vision-preview"]:
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        {"type": "text",
                         "text": prompt or "Describe exactly what's on screen: app name, window title, visible text content, what the user is doing. Be specific about content. 2-3 sentences."}
                    ]}],
                    "max_tokens": 200
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
            except Exception as e:
                print(f"[SOUL] vision {model} error: {e}")
                continue
        return "Screen vision unavailable"

    def _parse(self, raw: str) -> dict:
        actions = []
        # Strip fake roleplay narration ONLY — keep <ACTION> and <ACTIONS> tags
        raw = re.sub(r'<(?!/?ACTIONS?\b)[A-Z][^>]{0,80}>', '', raw).strip()
        raw = re.sub(r'<(?!/?actions?\b)[a-z][^>]{0,80}>', '', raw).strip()

        # ── Try all action formats in order of reliability ──

        # Format 1: <ACTIONS>[...]</ACTIONS>  (proper multi-step)
        multi = re.search(r"<ACTIONS>\s*(\[.*?\])\s*</ACTIONS>", raw, re.DOTALL | re.IGNORECASE)
        if multi:
            try:
                parsed = json.loads(multi.group(1).strip())
                if isinstance(parsed, list):
                    actions = parsed
            except json.JSONDecodeError:
                pass
            text = re.sub(r"<ACTIONS>.*?</ACTIONS>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()

        # Format 2: bare [...]</ACTIONS>  (LLM forgot opening tag)
        elif re.search(r"^\s*\[", raw, re.MULTILINE) and re.search(r"</ACTIONS>", raw, re.IGNORECASE):
            arr_match = re.search(r"(\[.*?\])\s*</ACTIONS>", raw, re.DOTALL | re.IGNORECASE)
            if arr_match:
                try:
                    parsed = json.loads(arr_match.group(1).strip())
                    if isinstance(parsed, list):
                        actions = parsed
                except json.JSONDecodeError:
                    pass
                text = re.sub(r"\[.*?\]\s*</ACTIONS>", "", raw, flags=re.DOTALL | re.IGNORECASE).strip()
            else:
                text = raw.strip()

        # Format 3: <ACTION>{...}</ACTION> or with lowercase closing </action>
        else:
            single = re.search(r"<ACTION>\s*(\{.*?\})\s*</[Aa][Cc][Tt][Ii][Oo][Nn]>", raw, re.DOTALL)
            if single:
                try:
                    a = json.loads(single.group(1).strip())
                    actions = [a]
                except json.JSONDecodeError:
                    pass
                text = re.sub(r"<ACTION>.*?</[Aa][Cc][Tt][Ii][Oo][Nn]>", "", raw, flags=re.DOTALL).strip()

            # Format 4: bare JSON object with "type" key (no tags at all)
            else:
                obj_match = re.search(r"(\{\s*\"type\"\s*:.*?\})", raw, re.DOTALL)
                if obj_match:
                    try:
                        a = json.loads(obj_match.group(1).strip())
                        if isinstance(a, dict) and "type" in a:
                            actions = [a]
                            text = raw[:obj_match.start()].strip() + raw[obj_match.end():].strip()
                        else:
                            text = raw.strip()
                    except json.JSONDecodeError:
                        text = raw.strip()
                else:
                    # Format 5: bare JSON array (no tags)
                    arr_bare = re.search(r"(\[\s*\{\s*\"type\".*?\}\s*\])", raw, re.DOTALL)
                    if arr_bare:
                        try:
                            parsed = json.loads(arr_bare.group(1).strip())
                            if isinstance(parsed, list) and parsed and "type" in parsed[0]:
                                actions = parsed
                                text = raw[:arr_bare.start()].strip() + raw[arr_bare.end():].strip()
                            else:
                                text = raw.strip()
                        except json.JSONDecodeError:
                            text = raw.strip()
                    else:
                        text = raw.strip()

        # Clean up: strip "Opening application..." / "Notepad is now open." narration
        # that leaks when LLM writes setup prose before an action block
        if actions and text:
            # If text is just narration (long setup paragraph) trim it
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            # Keep only lines that aren't just announcing the action
            action_announce = {"opening", "i'm opening", "launching", "starting",
                               "i'll", "let me", "opening application", "notepad is now open",
                               "nopening", "opening app"}
            clean = [l for l in lines if not any(
                l.lower().startswith(a) for a in action_announce)]
            text = " ".join(clean).strip()

        # Fallback: if only action block and no prose, use display_text
        if not text and actions:
            first = actions[0]
            text = first.get("display_text", "")

        # Return single action for back-compat, plus full list
        return {
            "text": text,
            "action": actions[0] if len(actions) == 1 else None,
            "actions": actions  # empty list if no actions
        }

    def reset(self):
        self.conversation_history = []

    def inject_memory(self, summary: str):
        if summary:
            self.conversation_history.insert(0, {
                "role": "system",
                "content": f"[MEMORY FROM PREVIOUS SESSIONS]\n{summary}"
            })
