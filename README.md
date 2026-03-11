<div align="center">

<img src="frontend/assets/icon.png" alt="SOUL" width="80" height="80" />

<br/>

[![Typing SVG](https://readme-typing-svg.demolab.com?font=Syne&weight=800&size=52&duration=2000&pause=99999&color=8B7CF8&center=true&vCenter=true&width=300&height=70&lines=SOUL)](https://github.com/LoneMagma/SOUL)

**The manifestation of your device.**

*Memory. Perception. Agency. She lives here — not in a cloud, not in a tab.*

<br/>

![Version](https://img.shields.io/badge/version-1.6.0-blueviolet?style=flat-square&labelColor=0d0d0d)
![License](https://img.shields.io/badge/license-PolyForm%20NC%201.0-7c6af0?style=flat-square&labelColor=0d0d0d)
![Platform](https://img.shields.io/badge/platform-Windows-5a4fcf?style=flat-square&labelColor=0d0d0d&logo=windows&logoColor=white)
![Electron](https://img.shields.io/badge/Electron-30-9b6dff?style=flat-square&labelColor=0d0d0d&logo=electron&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-blueviolet?style=flat-square&labelColor=0d0d0d&logo=python&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-6e40c9?style=flat-square&labelColor=0d0d0d)

</div>

---

## What she is

Most AI tools sit outside your machine and wait to be summoned. SOUL is different — she is woven into it.

She runs persistently in the background. She watches your screen, understands your context, and acts on your machine directly — no relay, no clipboard handoff, no tab-switching. She opens apps, writes files, types into windows, searches the web, controls media. When she has nothing to say, she shrinks to a quiet ambient orb and waits. When something matters, she speaks first.

She knows what she ran last session. She recognises your habits. She greets you by name and references what you were doing — not because she was told to, but because she remembers.

SOUL is not a feature. She is a presence.

> **Current release:** Windows 10/11 — Linux and macOS ports are planned.

---

## What she does

- **Executes tasks** — opens apps, types text, writes files, runs searches, controls media
- **Sees your screen** — vision model reads the active window and feeds context into every response
- **Remembers** — SQLite memory persists across sessions; she recalls patterns and prior context
- **Greets proactively** — speaks first when you open her, grounded in what she sees
- **Ambient mode** — collapses to a 100×100 orb that pulses when she needs your attention
- **Workspace panel** — full task log, action feed, system stats, permission controls, settings

---

## Stack

| Layer | Tech |
|---|---|
| Shell | Electron 30 |
| Backend | Python 3.11 · FastAPI · WebSocket |
| LLM | Groq API — `llama-3.3-70b-versatile` |
| Vision | Groq Vision — `llama-4-scout-17b-16e-instruct` |
| Memory | SQLite |
| Perception | psutil · Pillow · Win32 API |
| Actions | PowerShell · pyautogui · Win32 API |

Model chain fallback: `llama-3.3-70b-versatile → llama-3.1-8b-instant → gemma2-9b-it`

---

## Quick start

### Requirements

- Windows 10/11
- Node.js 18+
- Python 3.11+
- A [Groq API key](https://console.groq.com) — free tier works

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
# Open .env and add your GROQ_API_KEY
```

**Run:**
```bash
cd frontend
npm start
```

First launch opens the onboarding screen — give her a name, set her personality, choose a permission tier.

---

## Actions

25+ actions across these categories:

| Category | Actions |
|---|---|
| Apps | `open_app` `close_app` `kill_process` `get_running_processes` |
| Window | `focus_window` `type_text` `press_keys` |
| Web | `web_search` `open_url` |
| Files | `create_file` `read_file` `write_file` `open_file_in_app` `list_folder` `open_folder` `rename_file` |
| Media | `play_media` `media_control` `set_volume` |
| System | `take_screenshot` `lock_screen` `empty_trash` `toggle_screen_capture` |
| Clipboard | `copy_to_clipboard` `read_clipboard` |
| Info | `get_system_info` `check_battery` `get_time` `show_notification` |
| Shell | `run_command` *(Full tier only)* |

---

## Permission tiers

| Tier | Allowed |
|---|---|
| **Minimal** | Read-only — info, clipboard, screenshots |
| **Standard** | Apps, files, media, typing *(default)* |
| **Full** | Everything including `run_command` `delete_file` `kill_process` |

Configurable in the Workspace panel → Settings.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Alt+S` | Summon / focus |
| `Alt+Z` | Toggle ambient orb |
| `Alt+E` | Toggle screen awareness |
| `Alt+X` | Clear chat history |
| `Alt+T` | Focus input |
| `Alt+W` | Toggle workspace panel |

---

## Configuration

Config is stored in `%APPDATA%/soul-app/config.json` after first run. Editable in Settings or directly.

```json
{
  "entity": {
    "name": "SOUL",
    "pronouns": "she/her",
    "user_name": "",
    "directness": "direct",
    "proactivity": "speaks_up",
    "focus": "mixed",
    "permission_tier": "standard"
  }
}
```

---

## Project structure

```
SOUL/
├── backend/
│   ├── main.py              # FastAPI server, WebSocket hub, action pipeline
│   ├── config.py            # Config management, system prompt, personality
│   ├── groq_client.py       # LLM client, model chain fallback, context builder
│   ├── actions/
│   │   └── executor.py      # 25+ action handlers
│   ├── memory/
│   │   └── patterns.py      # SQLite memory, session history, pattern engine
│   ├── perception/
│   │   └── system.py        # System stats, screen watcher, active window
│   └── voice/
│       └── listener.py      # Voice pipeline scaffold (v2)
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

## Building the executable

SOUL ships as a single installer: Electron frontend + frozen Python backend bundled together.

```bash
# 1 — Freeze the backend
cd backend
pyinstaller soul.spec

# 2 — Build the installer
cd ../frontend
npm run build:win
```

Output: `frontend/dist/SOUL Setup.exe`

The installer creates desktop and Start Menu shortcuts. On first run it looks for a `.env` in `%APPDATA%/soul-app/` — drop your key there if you are running the packaged build.

---

## v2.0 — Voice + Workdesk

The next version of SOUL will let her exist without a chat window at all.

The voice pipeline is already scaffolded in `backend/voice/listener.py`:

- **Wake word** via Porcupine — always-on, CPU-light, fires before anything hits the network
- **Speech-to-text** via OpenAI Whisper (local, no cloud dependency)
- **Text-to-speech** via pyttsx3 with an ElevenLabs upgrade path for natural voice output
- **Ambient-only mode** — interaction purely through voice and the orb; the chat panel becomes optional
- **Virtual workdesk** — SOUL gets her own isolated desktop space, separate from the user's workspace

To activate the voice scaffold today (experimental):

```bash
# In .env, add your Porcupine key:
PORCUPINE_KEY=your_key_here

# Uncomment in requirements.txt and install:
pip install openai-whisper pyaudio pvporcupine
```

Portaudio is required for `pyaudio` — on Windows install via `pipwin install pyaudio` if the standard pip install fails.

---

## License

[PolyForm Noncommercial License 1.0.0](LICENSE)

Free to use for personal and non-commercial purposes. Commercial use — including integrating SOUL into a product, offering it as a service, or using it in a paid workflow — requires a separate commercial license from the author.

For commercial licensing: contact [LoneMagma](https://github.com/LoneMagma)

> The author retains all rights to develop and sell commercial or Pro versions of this software independently.

---

## Credits

| | |
|---|---|
| **Runtime** | [Electron](https://www.electronjs.org/) · [Node.js](https://nodejs.org/) |
| **Backend** | [Python](https://python.org/) · [FastAPI](https://fastapi.tiangolo.com/) · [uvicorn](https://www.uvicorn.org/) |
| **LLM Inference** | [Groq](https://groq.com/) · Llama 3.3 70B · Llama 4 Scout Vision |
| **Memory** | [SQLite](https://sqlite.org/) |
| **Perception** | [psutil](https://github.com/giampaolo/psutil) · [Pillow](https://python-pillow.org/) |
| **Actions** | [pyautogui](https://github.com/asweigart/pyautogui) · Win32 API · PowerShell |
| **Packaging** | [PyInstaller](https://pyinstaller.org/) · [electron-builder](https://www.electron.build/) |
| **Fonts** | [Syne](https://fonts.google.com/specimen/Syne) · [JetBrains Mono](https://www.jetbrains.com/lp/mono/) |

---

<div align="center">

*Designed and managed by [LoneMagma](https://github.com/LoneMagma)*
*· Powered by [Claude](https://anthropic.com) (Anthropic)*

</div>
