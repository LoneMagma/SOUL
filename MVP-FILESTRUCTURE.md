pacificia-mvp/
│
├── main.py                          # Phase 1: Core conversation loop
├── .env                             # API keys (gitignored)
├── .gitignore                       # Git ignore rules
├── requirements.txt                 # Python dependencies
├── README.md                        # Project documentation
│
├── core/                            # Brain logic
│   ├── __init__.py
│   ├── brain.py                     # Future: Advanced brain with memory
│   └── config.py                    # Future: Configuration management
│
├── voice/                           # Voice I/O (Phase 2+)
│   ├── __init__.py
│   ├── text_to_speech.py           # Phase 2: TTS (pyttsx3)
│   ├── speech_to_text.py           # Phase 3: STT (Whisper API)
│   └── wake_word.py                # Phase 3: Wake word detection
│
├── actions/                         # Task execution (Phase 4+)
│   ├── __init__.py
│   ├── parser.py                   # Action detection
│   ├── executor.py                 # Task router
│   └── tools/
│       ├── __init__.py
│       ├── spotify.py              # Music control
│       ├── app_launcher.py         # Open applications
│       └── web_search.py           # Google search
│
├── monitors/                        # System monitoring (Phase 5+)
│   ├── __init__.py
│   ├── battery.py                  # Battery monitoring
│   ├── cpu.py                      # CPU monitoring
│   └── monitor_loop.py             # Background monitor thread
│
├── ui/                              # Visual interface (Phase 6+)
│   ├── __init__.py
│   └── overlay.py                  # Tkinter mascot overlay
│
├── personas/                        # Personality definitions
│   └── pacify/
│       └── pacificia.json          # From your Pacify & Defy project
│
├── assets/                          # Visual/audio resources
│   └── pacificia.png               # Future: Mascot image
│
└── logs/                            # Debug logs (gitignored)
    └── .gitkeep
