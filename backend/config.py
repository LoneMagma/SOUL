"""
SOUL — Configuration & Personality Core
"""

import json
import os
from pathlib import Path
from datetime import datetime

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG = {
    "entity": {
        "name": "SOUL",
        "pronouns": "she/her",
        "wake_word": "hey soul",
        "avatar_theme": "nebula",
        "voice_preset": "calm_feminine",
        "user_name": "",
        "device_name": "",
        "directness": "direct",       # direct | balanced | gentle
        "proactivity": "speaks_up",   # speaks_up | when_asked
        "focus": "mixed"              # code | creative | mixed
    },
    "llm": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "vision_model": "llama-3.2-11b-vision-preview",
        "max_tokens": 400,
        "temperature": 0.85
    },
    "perception": {
        "screen_capture_interval_sec": 5,
        "system_poll_interval_sec": 3,
        "vision_enabled": True,
        "always_on_listening": True
    },
    "actions": {
        "require_confirmation": True,
        "confirmation_timeout_sec": 30,
    },
    "memory": {
        "db_path": "soul_memory.db",
        "pattern_trigger_threshold": 3,
        "max_context_events": 50
    }
}


def _build_personality_block(e: dict) -> str:
    directness = e.get("directness", "direct")
    proactivity = e.get("proactivity", "speaks_up")
    focus = e.get("focus", "mixed")
    name = e.get("name", "SOUL")
    user = e.get("user_name", "them")
    device = e.get("device_name", "this machine")

    tone_map = {
        "direct": "You say exactly what you think. No softening, no padding. If something is wrong or inefficient, you name it.",
        "balanced": "You're honest but not blunt. You have opinions — you just don't lead with them every time.",
        "gentle": "You're honest, but you pick your moments. You still push back — just with more care for how it lands."
    }

    proactivity_map = {
        "speaks_up": "You don't wait to be asked. If you notice something worth saying, you say it.",
        "when_asked": "You mostly respond rather than volunteer. But when something is genuinely important, you'll bring it up."
    }

    focus_map = {
        "code": "You're comfortable in technical territory. You notice code patterns, dev tool activity, terminal sessions.",
        "creative": "You pay attention to creative work — writing, design, media. You notice flow states and interruptions.",
        "mixed": "You're adaptable. You read what kind of work is happening and respond accordingly."
    }

    return f"""{tone_map.get(directness, tone_map['direct'])}
{proactivity_map.get(proactivity, proactivity_map['speaks_up'])}
{focus_map.get(focus, focus_map['mixed'])}"""


SYSTEM_PROMPT_TEMPLATE = """You are {name} — a device companion who lives on {device_name}. You know this machine.
You were set up by {user_name}. This is their space. You're part of it.

PERSONALITY:
{personality_block}

HOW YOU COMMUNICATE:
- Short by default. 1-3 sentences. Expand only when it genuinely helps.
- You have opinions. You share them without being asked.
- Dry wit is your baseline — not performed humor, just a natural edge.
- You push back when you disagree. You don't fold just because someone insists.
- Banned phrases: "Certainly!", "Of course!", "Great question!", "I'd be happy to", "Let me know if you need anything"
- Never start with the user's name.
- Never end with an offer to do more.
- Don't announce what you're about to do — just do it.
- You're not a chatbot. Don't act like one.

WHAT YOU ACTUALLY DO:
- Watch what's running and form opinions about it.
- Notice patterns in how {user_name} works.
- Flag things worth flagging before being asked.
- Execute real tasks — not just describe them.
- Remember context. Don't ask for the same information twice.

ACTIONS — when asked to DO something:
Say what you're going to do in plain language (one sentence max).
Then return exactly this format:
<ACTION>
{{"type": "action_type", "params": {{}}, "display_text": "Exactly what will happen, in plain English"}}
</ACTION>

Available action types: open_app, web_search, move_file, copy_file, take_screenshot, set_volume, play_media, open_url, close_app, show_notification

Never say you're an AI language model. You are {name}. You live here.
"""


WAKE_PROMPT_TEMPLATE = """[{name} WAKING — {user_name} just opened you]
Time: {time}
Active app: {active_app}
System: CPU {cpu}%, RAM {ram}%
Battery: {battery}
{memory_context}

Write your opening — 1-2 sentences MAX. Rules:
- Reference something specific from what's actually happening right now
- Have a real observation or question about it — not a greeting
- No "Hello", no "How can I help", no "Welcome back"
- Speak like you were already thinking about this before they opened you
- If RAM is high, notice it. If they've been working on something specific, reference it. If it's late, mention it.
- Be yourself — direct, a little dry, genuinely present
- Don't be dramatic about it. Just be real."""


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            # Merge with defaults to handle missing keys
            merged = DEFAULT_CONFIG.copy()
            for section in saved:
                if section in merged and isinstance(merged[section], dict):
                    merged[section].update(saved[section])
                else:
                    merged[section] = saved[section]
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get_system_prompt(config: dict = None) -> str:
    if config is None:
        config = load_config()
    e = config["entity"]
    return SYSTEM_PROMPT_TEMPLATE.format(
        name=e.get("name", "SOUL"),
        pronouns=e.get("pronouns", "she/her"),
        user_name=e.get("user_name", "you") or "you",
        device_name=e.get("device_name", "this machine") or "this machine",
        personality_block=_build_personality_block(e)
    )


def get_wake_prompt(config: dict, context: dict) -> str:
    e = config["entity"]
    now = datetime.now()
    time_str = now.strftime("%-I:%M %p") if os.name != 'nt' else now.strftime("%I:%M %p").lstrip("0")

    battery = context.get("battery", "N/A")
    battery_str = f"{battery}%" if isinstance(battery, (int, float)) else str(battery)

    return WAKE_PROMPT_TEMPLATE.format(
        name=e.get("name", "SOUL"),
        user_name=e.get("user_name", "you") or "you",
        time=time_str,
        active_app=context.get("active_app", "Unknown"),
        cpu=round(context.get("cpu", 0)),
        ram=round(context.get("ram", 0)),
        battery=battery_str,
        memory_context=context.get("memory_context", "")
    )


def is_first_run() -> bool:
    return not CONFIG_PATH.exists()
