# SOUL - Pacificia MVP

[![Development Status](https://img.shields.io/badge/status-in%20development-yellow)](https://github.com/LoneMagma/SOUL.git)
[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Groq](https://img.shields.io/badge/powered%20by-Groq-orange)](https://groq.com/)

> **A manisfestation of you device, with a personality of its own and action taking capabilities**

SOUL is an AI assistant with a defined personality that integrates conversational intelligence to your desktop. This repository contains the foundational MVP (Phase 1) - a text-based chat interface that will evolve into a voice-enabled desktop companion.

---

## Current Status

**Phase 1: Core Conversation Engine** (In Progress)

This is an active development project. The current implementation provides basic conversational functionality through a terminal interface. Voice interaction, system monitoring, and visual components are planned for future phases.

## Features

- Personality-driven responses using JSON persona definitions
- Groq API integration with Llama 3.3 70B model
- Multi-key API pooling system for extended usage
- Configurable conversational style and behavior

## Installation

```bash
# Clone repository
git clone https://github.com/LoneMagma/SOUL.git
cd SOUL- MVP

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env and add your Groq API key(s)
```

## Usage

```bash
python main.py
```

Interact through the terminal. Type `exit`, `quit`, or `bye` to end the session.

## Requirements

- Python 3.8 or higher
- Groq API key ([Get one here](https://console.groq.com/))
- Persona definition file (`pacificia.json` in `personas/pacify/`)

## Project Structure

```
soul-pacificia-mvp/
├── main.py                 # Main conversation loop
├── requirements.txt        # Dependencies
├── .env                    # API keys (gitignored)
└── personas/
    └── pacify/
        └── pacificia.json  # Persona configuration
```

## Roadmap

- [x] Phase 1: Text-based conversation engine
- [x] Phase 2: Voice interaction (wake word, STT, TTS)
- [ ] Phase 3: Action execution system
- [ ] Phase 4: System state monitoring
- [ ] Phase 5: Visual desktop overlay

## Contributing

This project is under active development. Issues and suggestions are welcome, but please note that the codebase is evolving rapidly.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Powered by [Groq](https://groq.com/) and Llama 3.3
