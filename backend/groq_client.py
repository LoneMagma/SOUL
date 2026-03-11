"""
SOUL — Groq LLM Client  v1.7.0

Changes from v1.6.0:
  - inject_visual_result(): new method that replaces inject_action_result() for
    execution actions. Instead of injecting raw executor booleans, SOUL now injects
    visually-grounded results from ActionVerifier (verifier.py).

    Old: "[ACTION FAILED] focus_window: Win32 SetForegroundWindow returned False"
    New: "[ACTION OK — visually confirmed via fallback (open_app)] Focus Chrome: Chrome window appeared."

    This closes the loop between eyes and hands — the LLM learns what actually
    happened on screen, not what the Python executor guessed.

  - All other behavior (streaming, parsing, key rotation, history, trivial path)
    unchanged from v1.6.0.
"""

import os, json, re, asyncio, random, httpx
from config import load_config, get_system_prompt, get_wake_prompt

GROQ_API_BASE = "https://api.groq.com/openai/v1"

MODEL_CHAIN = [
    "llama-3.3-70b-versatile",  # primary   6K TPM free tier
    "llama-3.1-8b-instant",     # fallback  20K TPM
    "gemma2-9b-it",             # last line
]

_FAST_MODEL = "llama-3.1-8b-instant"

VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
]

# ── Trivial message pattern ──────────────────────────────────────────────────
_TRIVIAL_RE = re.compile(
    r"^(?:"
    r"hi+|hey+|hello+|heyy+|yo+|sup|wassup|wsp|"
    r"ok|okay|k|aight|alright|"
    r"lol|lmao|lmfao|haha+|xd|omg|bruh|"
    r"cool|nice|wow|damn|dang|sick|fire|crazy|"
    r"thanks|thank you|ty|thx|"
    r"fine|good|great|amazing|awesome|"
    r"w\??|gg|fr|ngl|nah|mhm|"
    r"stop|shut\s*up|shutup|stfu|"
    r"yeah|yep|yup|nope|"
    r"\?{1,3}|\.{1,3}|!{1,3}"
    r")[\s!?.]*$",
    re.IGNORECASE,
)


def _ck(k):
    k = (k or "").strip()
    return "" if (not k or k.startswith("your_") or k == "paste_your_key_here") else k


class GroqClient:
    def __init__(self):
        self.config       = load_config()
        self._chat_keys   = [k for k in [_ck(os.environ.get("GROQ_API_KEY")),
                                          _ck(os.environ.get("GROQ_API_KEY_2"))] if k]
        self._vision_keys = [k for k in [_ck(os.environ.get("GROQ_VISION_KEY")),
                                          _ck(os.environ.get("GROQ_VISION_KEY_2"))] if k]
        self._misc_keys   = [k for k in [_ck(os.environ.get("GROQ_API_KEY_3"))] if k]
        if not self._chat_keys:
            fb = _ck(os.environ.get("GROQ_API_KEY"))
            if fb:
                self._chat_keys = [fb]
        self.api_key  = self._chat_keys[0] if self._chat_keys else ""
        self._all_keys = list(dict.fromkeys(
            self._chat_keys + self._vision_keys + self._misc_keys))
        self._cidx = self._vidx = 0
        self.conversation_history: list[dict] = []
        self.active_model = MODEL_CHAIN[0]
        if not self.api_key:
            print("[SOUL] WARNING: No API key — add GROQ_API_KEY to .env")

    # ── Key rotation ─────────────────────────────────────────────────────────
    def _next_chat_key(self):
        pool = self._chat_keys or self._all_keys
        if not pool: return ""
        k = pool[self._cidx % len(pool)]; self._cidx += 1; return k

    def _next_vision_key(self):
        pool = self._vision_keys or self._misc_keys or self._chat_keys
        if not pool: return ""
        k = pool[self._vidx % len(pool)]; self._vidx += 1; return k

    def _next_key(self): return self._next_chat_key()  # compat

    # ── Context builder ───────────────────────────────────────────────────────
    def build_context(
        self,
        stats: dict,
        screen_summary: str,
        screen_enabled: bool,
        active_task: str,
        pattern_triggers: list,
        screen_summary_age: int = 0,
        capture_error: str = "",        # NEW: from ScreenWatcher.capture_error
        force_stats: bool = False,
    ) -> str:
        """
        Builds the <context> packet sent alongside each message.

        Screen state is one of four mutually exclusive strings:
          SCREEN_OFF          — screen capture toggled off by user
          SCREEN_ON_FRESH     — have a description <30s old → include it
          SCREEN_ON_STALE     — have a description but it's old → include with age
          SCREEN_ON_NO_CAPTURE — screen on but no successful capture yet or failed

        The LLM receives exactly one of these states, never two at once.
        This eliminates the "Screen: ON" + "Screen unavailable: [Errno 22]"
        contradiction that caused SOUL to oscillate about screen state every message.

        capture_error is from ScreenWatcher.capture_error (new v1.6 property).
        screen_summary is guaranteed by system.py v1.6 to be a real description
        or "" — never an error string.
        """
        import datetime as _dt
        lines = [f"[{_dt.datetime.now().strftime('%H:%M')}]"]

        if active_task:
            lines.append(f"Active: {active_task}")

        # ── Screen state — four clean cases ──────────────────────────────────
        if not screen_enabled:
            # User toggled screen capture off
            lines.append("Screen: OFF")

        elif screen_summary:
            # We have a real description — show it with staleness if needed
            if screen_summary_age > 30:
                lines.append(f"Screen: ON ({screen_summary_age:.0f}s ago)\n{screen_summary}")
            else:
                lines.append(f"Screen: ON\n{screen_summary}")

        elif capture_error:
            # Screen is on but capture is failing — say so cleanly
            # Don't include the raw error string: it's noise to the LLM.
            # A brief hint is enough for debugging without confusing the model.
            hint = ""
            if "OSError" in capture_error or "Errno 22" in capture_error:
                hint = " (display driver issue)"
            elif "vision API" in capture_error:
                hint = " (vision API unavailable)"
            lines.append(f"Screen: ON — capture unavailable{hint}")

        else:
            # Screen on, no capture yet (just started, or first cycle pending)
            lines.append("Screen: ON — no capture yet")

        # ── System stats ──────────────────────────────────────────────────────
        if stats:
            ram     = stats.get("ram", stats.get("ram_percent", 0)) or 0
            cpu     = stats.get("cpu", stats.get("cpu_percent", 0)) or 0
            bat_pct = stats.get("battery_pct", stats.get("battery_percent"))
            bat_str = stats.get("battery", "")
            plug    = stats.get("plugged", "⚡" in str(bat_str))

            if force_stats:
                parts = [f"CPU:{cpu:.0f}% RAM:{ram:.0f}%"]
                if bat_str and bat_str not in ("—", "N/A"):
                    parts.append(f"BAT:{bat_str}")
                lines.append(" | ".join(parts))
            else:
                crits = []
                if isinstance(ram, (int, float)) and ram > 95:
                    crits.append(f"RAM critical: {ram:.0f}%")
                if isinstance(bat_pct, (int, float)) and bat_pct < 5 and not plug:
                    crits.append(f"Battery critical: {bat_pct:.0f}%")
                if crits:
                    lines.append("⚠ " + " | ".join(crits))

        if pattern_triggers:
            lines.append(f"Patterns: {', '.join(pattern_triggers[:2])}")

        return "\n".join(lines)

    # ── Main streaming entrypoint ─────────────────────────────────────────────
    async def stream_chat(self, user_message: str, context_packet: str = "",
                          on_token=None, max_tokens: int = None) -> dict:
        if not self.api_key:
            err = {"text": "No API key. Add GROQ_API_KEY to .env", "action": None}
            if on_token: await on_token(err["text"])
            return err

        cfg      = load_config()
        cfg_temp = cfg["llm"].get("temperature", 0.85)
        cfg_tok  = cfg["llm"].get("max_tokens", 1024)

        if _TRIVIAL_RE.match(user_message.strip()):
            return await self._stream_trivial(
                user_message, context_packet, on_token, cfg_temp)

        msgs = [{"role": "system", "content": get_system_prompt(self.config)}]
        if context_packet:
            msgs.append({"role": "system",
                         "content": f"<context>\n{context_packet}\n</context>"})
        msgs.extend(self.conversation_history[-8:])
        msgs.append({"role": "user", "content": user_message})

        models    = [self.active_model] + [m for m in MODEL_CHAIN
                                           if m != self.active_model]
        pool      = (self._chat_keys + self._misc_keys) or self._all_keys
        full_text = ""
        succeeded = False

        for model in models:
            if succeeded: break
            tried = 0
            while tried < len(pool):
                api_key     = self._next_chat_key()
                tried      += 1
                _need_retry = False
                try:
                    payload = {
                        "model":       model,
                        "messages":    msgs,
                        "max_tokens":  max_tokens or cfg_tok,
                        "temperature": cfg_temp,
                        "stream":      True,
                    }
                    async with httpx.AsyncClient(
                            timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                        async with client.stream(
                            "POST", f"{GROQ_API_BASE}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}",
                                     "Content-Type": "application/json"},
                            json=payload,
                        ) as resp:
                            if resp.status_code in (429, 401):
                                _need_retry = True
                            else:
                                resp.raise_for_status()
                                async for line in resp.aiter_lines():
                                    if not line.startswith("data: "): continue
                                    chunk = line[6:].strip()
                                    if chunk == "[DONE]": break
                                    try:
                                        tok = json.loads(chunk)["choices"][0][
                                            "delta"].get("content", "")
                                        if tok:
                                            full_text += tok
                                            if on_token and not self._is_action_token(
                                                    tok, full_text):
                                                await on_token(tok)
                                    except Exception:
                                        pass

                    if _need_retry: continue
                    if model != self.active_model:
                        self.active_model = model
                    succeeded = True
                    break

                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (401, 429) and tried < len(pool):
                        continue
                    break
                except httpx.TimeoutException:
                    break
                except Exception as ex:
                    print(f"[SOUL] stream {model}: {ex}"); break

        if not succeeded or not full_text:
            for _wait in (2.5, 5.0):
                print(f"[SOUL] all keys 429 — waiting {_wait}s")
                await asyncio.sleep(_wait)
                for _key in pool:
                    try:
                        _r = await httpx.AsyncClient(
                            timeout=httpx.Timeout(20.0)).post(
                            f"{GROQ_API_BASE}/chat/completions",
                            json={"model": _FAST_MODEL, "messages": msgs,
                                  "max_tokens": max_tokens or 400,
                                  "temperature": 0.7},
                            headers={"Authorization": f"Bearer {_key}",
                                     "Content-Type": "application/json"})
                        if _r.status_code == 200:
                            full_text = _r.json()["choices"][0]["message"]["content"]
                            succeeded = True
                            break
                    except Exception:
                        pass
                if succeeded: break

        if not succeeded or not full_text:
            return {"text": "All models unavailable. Check connection.", "action": None}

        parsed     = self._parse(full_text)
        clean_text = parsed.get("text", "").strip() or "..."
        self._save_to_history(user_message, clean_text)
        return parsed

    # ── Trivial message fast-path ─────────────────────────────────────────────
    async def _stream_trivial(self, user_message: str, context_packet: str,
                               on_token, cfg_temp: float) -> dict:
        """8B model, minimal context, 80-token cap."""
        msgs = [{"role": "system", "content": get_system_prompt(self.config)}]

        if context_packet:
            slim = "\n".join(
                l for l in context_packet.splitlines()
                if not any(x in l for x in ["CPU:", "RAM:", "BAT:", "Patterns:"])
            ).strip()
            if slim:
                msgs.append({"role": "system",
                              "content": f"<context>\n{slim}\n</context>"})

        msgs.extend(self.conversation_history[-4:])
        msgs.append({"role": "user", "content": user_message})

        pool      = (self._chat_keys + self._misc_keys) or self._all_keys
        full_text = ""

        for _key in pool:
            try:
                payload = {
                    "model":       _FAST_MODEL,
                    "messages":    msgs,
                    "max_tokens":  80,
                    "temperature": min(cfg_temp + 0.05, 1.0),
                    "stream":      True,
                }
                async with httpx.AsyncClient(
                        timeout=httpx.Timeout(12.0, connect=4.0)) as c:
                    async with c.stream(
                        "POST", f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {_key}",
                                 "Content-Type": "application/json"},
                        json=payload,
                    ) as resp:
                        if resp.status_code in (429, 401): continue
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "): continue
                            chunk = line[6:].strip()
                            if chunk == "[DONE]": break
                            try:
                                tok = json.loads(chunk)["choices"][0][
                                    "delta"].get("content", "")
                                if tok:
                                    full_text += tok
                                    if on_token and not self._is_action_token(
                                            tok, full_text):
                                        await on_token(tok)
                                        await asyncio.sleep(0.018)
                            except Exception:
                                pass
                if full_text: break
            except Exception as ex:
                print(f"[SOUL] trivial fast-path: {ex}")
                continue

        if not full_text:
            fallback = random.choice([".", "yeah.", "ok.", "hey.", "what's up?"])
            full_text = fallback
            if on_token: await on_token(full_text)

        parsed = self._parse(full_text)
        clean  = parsed.get("text", full_text).strip() or full_text.strip()
        self._save_to_history(user_message, clean)
        return parsed

    # ── Non-streaming chat ────────────────────────────────────────────────────
    async def chat(self, user_message: str, context_packet: str = "",
                   max_tokens: int = None) -> dict:
        if not self.api_key:
            return {"text": "No API key. Add GROQ_API_KEY to .env", "action": None}
        cfg      = load_config()
        cfg_tok  = cfg["llm"].get("max_tokens", 1024)
        msgs     = [{"role": "system", "content": get_system_prompt(self.config)}]
        if context_packet:
            msgs.append({"role": "system",
                         "content": f"<context>\n{context_packet}\n</context>"})
        msgs.extend(self.conversation_history[-8:])
        msgs.append({"role": "user", "content": user_message})
        r = await self._call(msgs, max_tokens=max_tokens)
        if r.get("success"):
            raw    = r["text"].strip() or "..."
            parsed = self._parse(raw)
            clean  = parsed.get("text", "").strip() or raw
            self._save_to_history(user_message, clean)
            return parsed
        return {"text": r.get("error", "Something went wrong."), "action": None}

    # ── Low-level HTTP call ───────────────────────────────────────────────────
    async def _call(self, messages: list, max_tokens: int = None,
                    temperature: float = None) -> dict:
        cfg      = load_config()
        cfg_temp = cfg["llm"].get("temperature", 0.85)
        cfg_tok  = cfg["llm"].get("max_tokens", 1024)
        models   = [self.active_model] + [m for m in MODEL_CHAIN
                                          if m != self.active_model]
        pool     = (self._chat_keys + self._misc_keys) or self._all_keys
        if not pool:
            return {"success": False, "error": "No API key configured."}

        for model in models:
            tried = 0
            while tried < len(pool):
                api_key = self._next_chat_key(); tried += 1
                try:
                    payload = {
                        "model":       model,
                        "messages":    messages,
                        "max_tokens":  max_tokens or cfg_tok,
                        "temperature": temperature if temperature is not None else cfg_temp,
                    }
                    async with httpx.AsyncClient(
                            timeout=httpx.Timeout(25.0, connect=5.0)) as c:
                        r = await c.post(
                            f"{GROQ_API_BASE}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}",
                                     "Content-Type": "application/json"},
                            json=payload)
                        r.raise_for_status()
                        data = r.json()
                    if model != self.active_model:
                        self.active_model = model
                    return {"success": True,
                            "text": data["choices"][0]["message"]["content"]}
                except httpx.HTTPStatusError as e:
                    code = e.response.status_code
                    if code == 400: break
                    if code == 401: continue
                    if code == 429:
                        if tried < len(pool): continue
                        ra = 0
                        try: ra = int(e.response.headers.get("retry-after", "0"))
                        except Exception: pass
                        if not ra:
                            try:
                                ra = int(e.response.json().get("error", {})
                                         .get("message", "")
                                         .split("try again in ")[1].split("s")[0]) + 1
                            except Exception: ra = 8
                        await asyncio.sleep(max(4, min(ra, 20))); break
                    break
                except httpx.TimeoutException:
                    return {"success": False, "error": "Request timed out."}
                except Exception as ex:
                    print(f"[SOUL] _call {model}: {ex}"); break

        return {"success": False, "error": "All models unavailable. Check connection."}

    # ── Vision ────────────────────────────────────────────────────────────────
    async def vision_query(self, image_base64: str, prompt: str = "") -> str:
        pool = self._vision_keys + self._misc_keys + self._chat_keys
        if not pool: return "Vision disabled"

        try:
            import base64 as _b64
            from PIL import Image
            from io import BytesIO
            raw = _b64.b64decode(image_base64)
            if len(raw) > 1_200_000:
                img = Image.open(BytesIO(raw))
                img.thumbnail((1024, 1024))
                buf = BytesIO(); img.save(buf, format="PNG", optimize=True)
                image_base64 = _b64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass

        default_prompt = ("Describe what's on this screen. "
                          "Specific and factual. 2-3 sentences max.")
        for model in VISION_MODELS:
            tried = 0
            while tried < len(pool):
                api_key = self._next_vision_key(); tried += 1
                try:
                    payload = {
                        "model": model,
                        "messages": [{"role": "user", "content": [
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"}},
                            {"type": "text", "text": prompt or default_prompt},
                        ]}],
                        "max_tokens": 250,
                    }
                    async with httpx.AsyncClient(
                            timeout=httpx.Timeout(20.0, connect=5.0)) as c:
                        r = await c.post(
                            f"{GROQ_API_BASE}/chat/completions",
                            headers={"Authorization": f"Bearer {api_key}",
                                     "Content-Type": "application/json"},
                            json=payload)
                        if r.status_code == 429:
                            if tried < len(pool): continue
                            break
                        r.raise_for_status()
                        return r.json()["choices"][0]["message"]["content"]
                except Exception as ex:
                    print(f"[SOUL] vision {model}: {ex}"); continue
        return "Screen vision unavailable"

    # ── Wake greeting ─────────────────────────────────────────────────────────
    async def wake(self, context: dict) -> dict:
        text = await self.wake_greeting(context)
        return {"text": text, "action": None}

    async def wake_greeting(self, context: dict) -> str:
        cfg    = load_config()
        prompt = get_wake_prompt(cfg, context)
        pool   = (self._chat_keys + self._misc_keys) or self._all_keys
        if not pool: return "hey."
        for _key in pool:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as c:
                    r = await c.post(
                        f"{GROQ_API_BASE}/chat/completions",
                        headers={"Authorization": f"Bearer {_key}",
                                 "Content-Type": "application/json"},
                        json={"model": _FAST_MODEL,
                              "messages": [{"role": "user", "content": prompt}],
                              "max_tokens": 40, "temperature": 0.9})
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"].strip()
            except Exception:
                pass
        return "hey."

    # ── Streaming action-token filter ─────────────────────────────────────────
    def _is_action_token(self, tok: str, full_text: str) -> bool:
        _opens  = len(re.findall(r'<\s*ACTIONS?\s*>',  full_text, re.IGNORECASE))
        _closes = len(re.findall(r'</\s*ACTIONS?\s*>', full_text, re.IGNORECASE))
        if _opens != _closes:
            return True
        if _opens == 0:
            if re.search(r'(?:^|\n)\s*\[\s*\{\s*["\']?type["\']?\s*:', full_text):
                return True
            if re.search(r'(?:^|\n)\s*\{\s*["\']?type["\']?\s*:', full_text):
                return True
        if re.search(r'</?(?:ACTION|ACTIONS?)?\s*$', tok.strip()):
            return True
        if re.search(r'^\s*[\[{]\s*["\']?type["\']?\s*:', tok):
            return True
        return False

    # ── Response parser ───────────────────────────────────────────────────────
    def _parse(self, raw: str) -> dict:
        actions = []
        text    = raw.strip()

        clean = re.sub(r'<[A-Z][A-Z_]{2,}[^>]{0,200}/?>', '', raw)
        clean = re.sub(
            r'<(?!/?ACTIONS?\b)(?!/?ACTION\b)[A-Za-z][^>]{0,80}>', '', clean)
        clean = re.sub(r'<\s*/?ACTIONS?\s*>', '', clean, flags=re.IGNORECASE)

        dec = json.JSONDecoder()
        bp = be = len(clean); bo = None

        for pos, ch in enumerate(clean):
            if ch not in '[{': continue
            la = clean[pos:pos + 500]
            if ch == '[' and '"type"' not in la: continue
            if ch == '{' and '"type"' not in la[:200]: continue
            try:
                obj, end = dec.raw_decode(clean, pos)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, list):
                if obj and isinstance(obj[0], dict) and "type" in obj[0]:
                    bp, be, bo = pos, end, obj; break
            elif isinstance(obj, dict) and "type" in obj:
                if pos < bp:
                    bp, be, bo = pos, end, obj; break

        if bo is not None:
            actions = bo if isinstance(bo, list) else [bo]
            text    = (clean[:bp] + clean[be:]).strip()

        if actions and text:
            _narr = ("opening", "i'm opening", "launching", "starting",
                     "i'll open", "let me open", "executing", "focusing",
                     "writing", "saving", "playing", "closing", "navigating",
                     "typing", "pressing", "searching", "checking", "creating",
                     "reading", "copying", "pasting", "here's the action")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            kept  = [l for l in lines
                     if not any(l.lower().startswith(p) for p in _narr)]
            text  = " ".join(kept).strip()

        if text:
            text = re.sub(r'ACTIONS?\s*\[.*', '', text, flags=re.DOTALL).strip()
            text = re.sub(r'\[\s*,.*',        '', text, flags=re.DOTALL).strip()
            text = re.sub(r'```[a-z]*\s*[\s\S]*?```', '', text).strip()
            text = re.sub(r'`[^`\n]{0,200}`', '', text).strip()
            text = re.sub(r'<[A-Z][A-Z_]{2,}[^>]{0,200}/?>', '', text).strip()
            text = re.sub(r'\[\s*\{\s*["\']?type["\']?.*', '', text,
                          flags=re.DOTALL).strip()
            text = re.sub(r'\{\s*["\']?type["\']?[^}]+\}\s*', '', text).strip()

        if not text and actions:
            text = actions[0].get("display_text", "")

        return {"text": text, "action": actions[0] if actions else None,
                "actions": actions}

    # ── History ───────────────────────────────────────────────────────────────
    def _save_to_history(self, user_msg: str, assistant_text: str):
        self.conversation_history.append({"role": "user",      "content": user_msg})
        self.conversation_history.append({"role": "assistant", "content": assistant_text})
        if len(self.conversation_history) > 20:
            if (self.conversation_history[0].get("role") == "system"
                    and "MEMORY" in self.conversation_history[0].get("content", "")):
                self.conversation_history = (
                    self.conversation_history[:1] + self.conversation_history[-19:])
            else:
                self.conversation_history = self.conversation_history[-20:]

    def reset(self):
        self.conversation_history = []

    def inject_visual_result(self, action: dict, exec_result: dict, vr) -> None:
        """
        Inject a visually-grounded action result into LLM history.

        Replaces the raw inject_action_result call for execution actions.
        The LLM now gets ground truth from what SOUL actually saw — not just
        what the Python executor returned.

        Examples of what goes into history:
          [ACTION OK — visually confirmed] Open Chrome: Chrome window appeared in foreground.
          [ACTION OK] Open Notepad: was already active.
          [ACTION FAILED] Focus Terminal: screen unchanged after action. Tried open_app — also failed.
          [ACTION FAILED] Open Spotify: no change detected.
        """
        atype = action.get("type", "")
        label = action.get("display_text") or atype

        if vr.skipped_verify:
            # Unverifiable action — use executor return value as before
            ok  = exec_result.get("success", False) if isinstance(exec_result, dict) else bool(exec_result)
            msg = (exec_result.get("message") or exec_result.get("text")
                   or ("OK" if ok else "Failed")) if isinstance(exec_result, dict) else ("OK" if ok else "Failed")
            line = f"[ACTION {'OK' if ok else 'FAILED'}] {label}: {msg}"

        elif vr.success and vr.visual_confirmed:
            # Screen confirmed it — strongest possible signal
            delta = vr.delta or "done"
            if vr.fallback_used:
                fb_label = vr.fallback_used.get("display_text") or vr.fallback_used.get("type", "fallback")
                line = f"[ACTION OK — visually confirmed via fallback ({fb_label})] {label}: {delta}"
            else:
                line = f"[ACTION OK — visually confirmed] {label}: {delta}"

        elif vr.success and not vr.visual_confirmed:
            # Executor OK, screen ambiguous (e.g. already-open app)
            msg = vr.delta or (exec_result.get("message") if isinstance(exec_result, dict) else "OK") or "OK"
            line = f"[ACTION OK] {label}: {msg}"

        elif not vr.success and vr.fallback_used:
            # Both original and fallback failed
            fb_type = vr.fallback_used.get("type", "fallback")
            reason  = vr.delta or "failed"
            line = f"[ACTION FAILED] {label}: {reason}. Fallback ({fb_type}) also failed."

        else:
            # Clean failure, no fallback attempted
            reason = vr.delta or "failed"
            line = f"[ACTION FAILED] {label}: {reason}"

        self.conversation_history.append({"role": "system", "content": line})
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]

    def inject_memory(self, summary: str):
        if summary:
            self.conversation_history.insert(0, {
                "role":    "system",
                "content": f"[MEMORY FROM PREVIOUS SESSIONS]\n{summary}"})

    def inject_action_result(self, action_type: str, result_text: str):
        if not result_text: return
        label = {
            "get_running_processes": "RUNNING PROCESSES",
            "get_system_info":       "SYSTEM INFO",
            "check_battery":         "BATTERY STATUS",
            "get_time":              "CURRENT TIME",
            "read_file":             "FILE CONTENT",
            "read_clipboard":        "CLIPBOARD CONTENT",
            "web_search":            "WEB SEARCH OPENED",
        }.get(action_type, action_type.upper())
        trimmed = result_text[:1200] + ("…" if len(result_text) > 1200 else "")
        self.conversation_history.append({
            "role":    "system",
            "content": f"[ACTION RESULT — {label}]\n{trimmed}"})
        if len(self.conversation_history) > 20:
            self.conversation_history = self.conversation_history[-20:]
