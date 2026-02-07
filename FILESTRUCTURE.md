pacificia-mvp/
│
├── 📄 main.py                      # Main orchestration loop
├── 📄 requirements.txt             # Python dependencies
├── 📄 .env                         # API keys (gitignored)
├── 📄 README.md                    # Setup instructions
│
├── 📁 core/                        # Brain & persona logic
│   ├── 📄 __init__.py
│   ├── 📄 brain.py                 # Groq API wrapper + Pacificia persona
│   ├── 📄 memory.py                # Session memory (future: persistence)
│   ├── 📄 config.py                # Configuration constants
│   └── 📄 api_pool.py              # Your multi-key Groq pool system
│
├── 📁 voice/                       # Voice input/output
│   ├── 📄 __init__.py
│   ├── 📄 wake_word.py             # Picovoice wake word detection
│   ├── 📄 speech_to_text.py        # Whisper API integration
│   └── 📄 text_to_speech.py        # pyttsx3 TTS
│
├── 📁 actions/                     # Task execution tools
│   ├── 📄 __init__.py
│   ├── 📄 parser.py                # Detects actions from text (regex)
│   ├── 📄 executor.py              # Routes to correct tool
│   └── 📁 tools/
│       ├── 📄 __init__.py
│       ├── 📄 spotify.py           # Spotify controller
│       ├── 📄 app_launcher.py      # Open applications
│       └── 📄 web_search.py        # Google search
│
├── 📁 monitors/                    # Passive system monitoring
│   ├── 📄 __init__.py
│   ├── 📄 battery.py               # Battery level checker
│   ├── 📄 cpu.py                   # CPU usage monitor
│   └── 📄 monitor_loop.py          # Background monitoring thread
│
├── 📁 ui/                          # Visual interface
│   ├── 📄 __init__.py
│   └── 📄 overlay.py               # Tkinter mascot + speech bubble
│
├── 📁 personas/                    # Personality definitions
│   └── 📁 pacify/
│       └── 📄 pacificia.json       # Pacificia persona (from your project)
│
├── 📁 assets/                      # Visual/audio resources
│   ├── 📄 pacificia.png            # 200x200px mascot image
│   └── 📁 sounds/ (future)
│       └── 📄 notification.wav
│
├── 📁 logs/                        # Debug logs (gitignored)
│   └── 📄 .gitkeep
│
└── 📁 docs/                        # Documentation
    ├── 📄 VISION.md                # This document
    └── 📄 SETUP.md                 # Installation guide
