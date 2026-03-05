# SOUL — Device Companion AI

> An always-on AI that lives on your PC. Not a chatbot. Not a copilot widget. A persistent companion that knows your machine, watches your screen, and actually executes tasks.

Built with Electron + Python (FastAPI) + Groq (Llama 3.3 70B).

---

## What it does

SOUL runs in the background as a small floating window. You talk to it. It acts.

- Opens apps, types text, writes files, searches the web
- Watches your screen and understands context
- Plays Spotify, controls media
- Remembers past sessions and learns your patterns
- Proactively greets you when you open it — not "Hello, how can I help?" but something that actually references what you were doing
- Ambient mode: collapses to a tiny 100×100 orb that pulses when it needs your attention
- Workspace panel: full task history, action queue, system stats, permission controls

---

## Stack

| Layer | Tech |
|---|---|
| Shell | Electron 28 |
| Backend | Python 3.11 · FastAPI · WebSocket |
| LLM | Groq API (llama-3.3-70b-versatile) |
| Vision | Groq Vision (llama-3.2-90b-vision-preview) |
| Memory | SQLite (`soul_memory.db`) |
| Actions | PowerShell · Win32 API · pyautogui |

---

## Setup

### Requirements
- Windows 10/11
- Node.js 18+
- Python 3.11+
- A [Groq API key](https://console.groq.com) (free)

### Install

```bash
git clone https://github.com/LoneMagma/SOUL.git
cd SOUL
```

**Backend:**
```bash
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

**Environment:**
```bash
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

`.env` format:
```
GROQ_API_KEY=your_key_here
```

### Run
```bash
cd frontend
npm start
```

The first launch opens an onboarding screen to name your companion and configure personality.

---

## Project structure

```
SOUL/
├── backend/
│   ├── main.py              # FastAPI server, WebSocket hub, action pipeline
│   ├── config.py            # Config management, system prompt, wake prompt
│   ├── groq_client.py       # LLM client, model chain fallback, context builder
│   ├── actions/
│   │   └── executor.py      # 25+ action handlers (open_app, type_text, play_media…)
│   ├── memory/
│   │   └── patterns.py      # SQLite memory, session history, pattern engine
│   └── perception/
│       └── system.py        # System stats, screen watcher, active window
├── frontend/
│   ├── main.js              # Electron main process, IPC, shortcuts
│   ├── preload.js           # Context bridge
│   └── renderer/
│       ├── index.html       # Main chat UI
│       ├── workspace.html   # Task log / workspace panel
│       ├── orb.html         # Ambient orb window
│       └── onboarding.html  # First-run setup
├── .env.example
├── requirements.txt
└── README.md
```

---

## Actions

SOUL can execute 25+ actions across these categories:

| Category | Actions |
|---|---|
| Apps | `open_app`, `close_app`, `kill_process`, `get_running_processes` |
| Window | `focus_window`, `type_text`, `press_keys` |
| Web | `web_search`, `open_url` |
| Files | `create_file`, `read_file`, `write_file`, `open_file_in_app`, `list_folder`, `open_folder`, `rename_file` |
| Media | `play_media`, `media_control`, `set_volume` |
| System | `take_screenshot`, `lock_screen`, `empty_trash`, `toggle_screen_capture` |
| Clipboard | `copy_to_clipboard`, `read_clipboard` |
| Info | `get_system_info`, `check_battery`, `get_time`, `show_notification` |
| Shell | `run_command` *(Full tier only)* |

---

## Permission tiers

| Tier | What's allowed |
|---|---|
| **Minimal** | Read-only — info, clipboard, screenshots |
| **Standard** | Apps, files, media, typing *(default)* |
| **Full** | Everything including `run_command`, `delete_file`, `kill_process` |

Change in the Workspace panel → Settings.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Alt+S` | Summon / focus window |
| `Alt+Z` | Toggle ambient orb mode |
| `Alt+E` | Toggle screen awareness |
| `Alt+X` | Clear chat history |
| `Alt+T` | Focus input (talk) |
| `Alt+W` | Toggle workspace panel |

---

## Configuration

Stored in `%APPDATA%/soul-app/config.json` after first run. Editable in the Settings tab of the Workspace panel or directly.

Key settings:

```json
{
  "entity": {
    "name": "SOUL",
    "user_name": "LoneMagma",
    "pronouns": "she/her",
    "directness": "direct",
    "proactivity": "speaks_up",
    "focus": "mixed",
    "permission_tier": "standard"
  }
}
```

---

## Development notes

- Backend runs on `ws://127.0.0.1:8765` — Electron spawns it on launch
- LLM model chain: `llama-3.3-70b-versatile → llama-3.1-8b-instant → gemma2-9b-it`
- Memory DB: `soul_memory.db` in the project root — gitignored
- Screen capture: JPEG thumbnails at 400×225, q88, every 2s; full vision analysis every 6s
- `SOUL_patch.ps1` is a dev utility — not for distribution

---

## License

MIT — see `LICENSE`

---

*Built by LoneMagma.*
