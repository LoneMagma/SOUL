<div align="center">

<!-- ────────────────────────────────
     HERO (animated, no ASCII)
     Replace later with your own GIF(s) in /assets
     ──────────────────────────────── -->

<!-- Option A (recommended now): animated typing SVG (no assets needed) -->
<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&weight=700&size=48&pause=900&color=8B7CF8&center=true&vCenter=true&width=900&lines=SOUL;Not+a+chatbot.;Not+an+assistant.;A+presence." alt="Typing SVG" />

<br/>

<strong>she lives on your machine. she's not waiting for you.</strong>

<br/><br/>

<!-- Option B (later): swap this for your own title GIF -->
<!-- <img src="assets/soul-title-animated.gif" alt="SOUL Animated Title" width="70%" /> -->

<img src="assets/soul-banner.gif" alt="SOUL Banner" width="100%" />
<br/><br/>

<a href="https://github.com/LoneMagma/SOUL">
  <img src="https://img.shields.io/badge/status-active%20development-8b7cf8?style=for-the-badge&labelColor=07090e" />
</a>
<a href="https://github.com/LoneMagma/SOUL">
  <img src="https://img.shields.io/badge/repo-LoneMagma%2FSOUL-4de89c?style=for-the-badge&labelColor=07090e" />
</a>
<a href="https://electronjs.org">
  <img src="https://img.shields.io/badge/Electron-28-47848f?style=for-the-badge&logo=electron&logoColor=white&labelColor=07090e" />
</a>
<a href="https://python.org">
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776ab?style=for-the-badge&logo=python&logoColor=white&labelColor=07090e" />
</a>
<a href="https://fastapi.tiangolo.com">
  <img src="https://img.shields.io/badge/FastAPI-0.111-009688?style=for-the-badge&logo=fastapi&logoColor=white&labelColor=07090e" />
</a>
<a href="https://console.groq.com">
  <img src="https://img.shields.io/badge/LLM-Groq%20%2F%20Llama%203.3-f55036?style=for-the-badge&labelColor=07090e" />
</a>
<a href="LICENSE">
  <img src="https://img.shields.io/badge/license-MIT-4de89c?style=for-the-badge&labelColor=07090e" />
</a>
<a href="https://microsoft.com">
  <img src="https://img.shields.io/badge/Windows-10%2F11-0078d4?style=for-the-badge&logo=windows&logoColor=white&labelColor=07090e" />
</a>

<br/><br/>

> *Not a chatbot. Not an assistant. A presence.*

<p>
  <a href="#what-is-this">What is this</a> •
  <a href="#what-she-can-do">What she can do</a> •
  <a href="#setup">Setup</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#roadmap">Roadmap</a> •
  <a href="#contributing">Contributing</a>
</p>

</div>

---

<div align="center">
  <img src="assets/demo-main.gif" alt="SOUL Main Interface" width="420" />
</div>

<br/>

## What is this

**SOUL** is a device companion that runs natively on Windows.  
She watches what you're working on, reads your system state, and **speaks first** — you don't have to prompt her.

She has opinions. She pushes back. She executes real tasks.  
She lives in the corner of your screen as a floating signal mark and wakes up when you need her.

This is **not** a wrapper around an existing LLM.  
This is an attempt to build something that actually **feels like it belongs on your machine**.

---

## What she can do

> **Rule #1:** she doesn’t run anything without your confirmation.

### RIGHT NOW
```
◉ Proactive opening — she speaks first on every summon
◉ Reads CPU, RAM, GPU, network, battery, disk I/O
◉ Knows what app you're in and what you're working on
◉ Screen awareness via vision model (toggleable)
◉ Opens apps, searches the web, takes screenshots
◉ Persistent memory across sessions
◉ Ambient mode — 72px floating orb with micro-actions
◉ Global shortcuts from any app
◉ Conversational onboarding with personality setup
```

### COMING IN v0.6
```
○ SOUL Workspace — her own panel, task queue, live log
○ Permission tiers — Minimal / Standard / Full autonomy
○ Voice input / output
○ Pattern recognition — she learns your habits
```

---

## Setup

### Prerequisites
- Windows 10 / 11
- Python 3.11+
- Node.js 18+
- Free Groq API key: https://console.groq.com

### Install
```bash
git clone https://github.com/LoneMagma/SOUL.git
cd SOUL

# Python dependencies
pip install -r requirements.txt

# Electron / frontend dependencies
cd frontend
npm install
cd ..
```

### Configure
```bash
# Copy example environment file
cp .env.example .env
```

Edit `.env` and add your key:
```env
GROQ_API_KEY=your_key_here
```

### Run
```bash
cd frontend
npm start
```

First launch starts onboarding (~60 seconds). After that — just `npm start`.

---

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **Alt + S** | Summon / hide SOUL |
| **Alt + Z** | Toggle ambient mode |
| **Alt + E** | Toggle screen awareness on/off |
| **Alt + X** | Clear current conversation |
| **Alt + T** | Focus text input |

---

## Ambient mode

<div align="center">
  <img src="assets/demo-ambient.gif" alt="SOUL Ambient Mode" width="220" />
</div>

72px floating orb that stays always-on-top.  
Hover to reveal micro-actions: expand, toggle screen awareness, close.  
Pulses gently when she wants to say something.

---

## Personality system

During onboarding she asks three real questions that actually change her behavior (not just labels):

```
directness  →  direct / balanced / gentle     (how bluntly she gives opinions)
proactivity →  speaks_up / when_asked         (whether she volunteers thoughts)
focus       →  mixed / code / creative        (what she pays closest attention to)
```

---

## How actions actually work (safety first)

```
You say: "open spotify"

          ↓
LLM decides → outputs structured ACTION block
          ↓
Executor resolves alias → finds Spotify.exe
          ↓
Yellow confirmation card appears (30-second auto-deny)
          ↓
You click Accept
          ↓
Windows → Start-Process "Spotify.exe"
          ↓
Result / feedback sent back to UI
```

**She never runs anything without your confirmation.**

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────┐
│                   ELECTRON FRONTEND                         │
│   main.js  •  preload.js  •  renderer/                      │
│   (window mgmt, shortcuts, ambient mode)                    │
└────────────────────────┬────────────────────────────────────┘
│ WebSocket ws://127.0.0.1:8765
┌────────────────────────┴────────────────────────────────────┐
│                     PYTHON BACKEND                          │
│   main.py  (FastAPI + WebSocket + orchestration)            │
│   ├── groq_client.py     (LLM calls + wake logic)           │
│   ├── config.py          (personality & system prompts)     │
│   ├── perception/        (system stats + screen vision)     │
│   ├── actions/           (task executor)                    │
│   ├── memory/            (SQLite + pattern storage)         │
│   └── voice/             (STT/TTS pipeline — planned)       │
└─────────────────────────────────────────────────────────────┘
```

---

## Project structure
```text
SOUL/
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── groq_client.py
│   ├── actions/executor.py
│   ├── memory/patterns.py
│   ├── perception/system.py
│   └── voice/listener.py       # (planned)
├── frontend/
│   ├── main.js
│   ├── preload.js
│   └── renderer/
│       ├── index.html
│       └── onboarding.html
├── .env.example
├── requirements.txt
└── START.md
```

---

## Models used (all free tier)

| Task | Model | Provider |
|---|---|---|
| Chat / Reasoning | `llama-3.3-70b-versatile` | Groq |
| Screen vision | `llama-3.2-11b-vision-preview` | Groq |
| Wake fallbacks | `mixtral-8x7b`, `gemma2-9b` | Groq |
| Speech-to-text | Whisper base | Local |

No OpenAI. No paid subscriptions required.

---

## Screenshots

> Add your screenshots here when ready.

- Main UI — `assets/screenshot-main.png`
- Ambient mode — `assets/screenshot-ambient.png`
- Onboarding — `assets/screenshot-onboarding.png`

---

## Roadmap

- Proactive wake message
- Screen awareness toggle
- Ambient mode + micro-actions
- Conversational onboarding
- Persistent memory
- Global hotkeys
- Windows task execution (with confirmation)
- **v0.6:** SOUL Workspace panel + task queue + logs
- Voice input & output
- Habit / pattern learning
- macOS port
- Plugin system

---

## Contributing

Open experiment — issues, PRs, ideas welcome.  
If you're building something similar or want to fork/extend SOUL, feel free to start a discussion.

---

## License

MIT — do whatever you want with it.

---

<div align="center">
  built by <a href="https://github.com/LoneMagma">LoneMagma</a> • she's not done yet.
</div>

---

## How to add your own animated hero (GIF) later

You said you’ll add the GIFs later — here’s the clean path:

1) Put your files here:
- `assets/soul-title-animated.gif` (title/logo animation)
- `assets/soul-banner.gif` (wide banner / vibe strip)

2) Replace **Option A** at the top with **Option B**:
- Uncomment:
  ```html
  <img src="assets/soul-title-animated.gif" alt="SOUL Animated Title" width="70%" />
  ```
- (Optional) remove the typing SVG line.

3) Keep GIF sizes reasonable so GitHub loads fast:
- Try to keep each GIF **< 5–8 MB**
- Export at ~**900–1200px** wide (title) and **1200–1600px** wide (banner)
- Use dithering carefully; GitHub markdown pages can look banded if you over-compress

4) If the GIF is too heavy, use MP4 + fallback (advanced):
- GitHub README doesn’t autoplay `<video>` reliably everywhere, so prefer GIF for now.
- If you *do* want MP4 later, put it in `assets/` and link it from a thumbnail image.

That’s it. Drop your GIFs in `/assets` and you’re done.
