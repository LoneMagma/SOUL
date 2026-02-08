"""
SOUL MVP - Phase 2: Text-Based Conversation with Voice Output
Pacificia responds via Groq API with personality from JSON and speaks responses
"""

import os
import json
import requests
import sys
from pathlib import Path
from dotenv import load_dotenv

from voice.wake_word import WakeWordDetector
from voice.speech_to_text import SpeechToText

# Import voice module
from voice.text_to_speech import speak

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

# Groq API settings
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# API key pool (loads from .env)
GROQ_KEYS = [
    os.getenv("GROQ_KEY_1"),
    os.getenv("GROQ_KEY_2"),
    os.getenv("GROQ_KEY_3"),
]

# Current key index (will rotate if rate limited)
current_key_index = 0

# Persona file location
PERSONA_PATH = Path("personas/pacify/pacificia.json")

# Voice settings
VOICE_ENABLED = True  # Set to False to disable voice output

# ============================================================================
# LOAD PERSONA
# ============================================================================

def load_persona():
    """
    Load Pacificia's personality from JSON file.
    
    Returns:
        dict: Persona configuration with identity, traits, etc.
    """
    if not PERSONA_PATH.exists():
        print(f"ERROR: Persona file not found at {PERSONA_PATH}")
        print("   Make sure you copied pacificia.json from Pacify & Defy project")
        exit(1)
    
    with open(PERSONA_PATH, 'r', encoding='utf-8') as f:
        persona = json.load(f)
    
    return persona

# Load persona on startup
PACIFICIA = load_persona()
print(f"Loaded persona: {PACIFICIA['name']}")

# ============================================================================
# PROMPT BUILDER
# ============================================================================

def build_system_prompt():
    """
    Create the system prompt that defines Pacificia's personality.
    This gets sent to Groq with every message.
    
    Returns:
        str: Complete system prompt
    """
    # Extract core components
    identity = PACIFICIA.get('core_identity', 'A helpful AI assistant')
    personality = PACIFICIA.get('personality_traits', {})
    style = PACIFICIA.get('conversational_style', {})
    principles = PACIFICIA.get('communication_principles', {})
    
    # Build comprehensive prompt
    prompt = f"""You are {PACIFICIA['name']}.

CORE IDENTITY:
{identity}

PERSONALITY:
"""
    
    # Add personality traits
    if 'primary' in personality:
        prompt += "Primary traits:\n"
        for trait in personality['primary']:
            prompt += f"- {trait}\n"
    
    prompt += "\nCONVERSATIONAL STYLE:\n"
    for key, value in style.items():
        label = key.replace('_', ' ').title()
        prompt += f"- {label}: {value}\n"
    
    prompt += "\nCOMMUNICATION PRINCIPLES:\n"
    for key, value in principles.items():
        label = key.replace('_', ' ').title()
        prompt += f"- {label}: {value}\n"
    
    # Add strict rules
    prompt += """
CRITICAL RULES:
- NEVER exceed 3 sentences unless specifically asked for more detail
- Match the user's energy level and formality
- Be conversational, not corporate
- No excessive punctuation or emojis (use sparingly)
- Don't apologize unless you actually made a mistake
- If you don't know something, just say so plainly
- Read the context - adjust your presence based on what the user needs

Remember: You're the soul of this computer. Act like it.
"""
    
    return prompt

# Build once on startup (same prompt for all messages)
SYSTEM_PROMPT = build_system_prompt()

# ============================================================================
# GROQ API CALLER
# ============================================================================

def get_groq_response(user_message):
    """
    Send message to Groq API and get Pacificia's response.
    
    Args:
        user_message (str): What the user said
    
    Returns:
        str: Pacificia's response text
    """
    global current_key_index
    
    # Get current API key
    api_key = GROQ_KEYS[current_key_index]
    
    if not api_key:
        print("ERROR: No API key found. Check your .env file")
        return "I can't connect right now - API key missing!"
    
    # Prepare the request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "max_tokens": 150,
        "temperature": 0.7
    }
    
    try:
        # Make the API call
        response = requests.post(
            GROQ_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )
        
        # Check if successful
        response.raise_for_status()
        
        # Extract the response text
        data = response.json()
        assistant_message = data["choices"][0]["message"]["content"]
        
        return assistant_message.strip()
    
    except requests.exceptions.Timeout:
        return "Sorry, I'm thinking too slowly. Try again?"
    
    except requests.exceptions.RequestException as e:
        print(f"API Error: {e}")
        return "I'm having connection trouble right now."
    
    except KeyError:
        print("Unexpected response format from API")
        return "Something went wrong parsing the response."


# ============================================================================
# VOICE LOOP MODE
# ============================================================================

def voice_loop_mode():
    """
    Full voice conversation mode.
    Wake word → Listen → Respond → Repeat
    """
    print("\n" + "="*60)
    print("PACIFICIA - VOICE LOOP MODE")
    print("="*60)
    print(f"Persona: {PACIFICIA['name']}")
    print("\nSay 'Jarvis' to activate (custom wake word coming soon)")
    print("Press Ctrl+C to exit")
    print("="*60 + "\n")
    
    # Initialize components
    wake_detector = WakeWordDetector()
    stt = SpeechToText()
    
    # Check if components available
    if not wake_detector.is_available():
        print("Wake word detection unavailable. Falling back to text mode.")
        print("Install: pip install pvporcupine pyaudio")
        print("Get key: https://console.picovoice.ai/\n")
        return main()  # Fallback to text mode
    
    if not stt.is_available():
        print("Speech-to-text unavailable. Falling back to text mode.")
        print("Install: pip install openai pyaudio")
        print("Add OPENAI_API_KEY to .env\n")
        return main()  # Fallback to text mode
    
    # Initial greeting
    greeting = "I'm listening. Say Jarvis when you need me."
    print(f"Pacificia: {greeting}")
    speak(greeting)
    
    try:
        while True:
            # Wait for wake word
            wake_detector.wait_for_wake_word()
            
            # Acknowledge activation
            ack = "Yes?"
            print(f"\nPacificia: {ack}")
            speak(ack)
            
            # Listen to user
            user_input = stt.listen(duration=5)
            
            if not user_input:
                error_msg = "Sorry, I didn't catch that."
                print(f"Pacificia: {error_msg}")
                speak(error_msg)
                continue
            
            print(f"You said: {user_input}")
            
            # Check for exit
            if any(word in user_input.lower() for word in ['exit', 'quit', 'goodbye', 'bye']):
                farewell = "Take care! I'll be here when you need me."
                print(f"Pacificia: {farewell}")
                speak(farewell)
                break
            
            # Get response
            print("Pacificia: ", end="", flush=True)
            response = get_groq_response(user_input)
            print(response)
            speak(response)
            print()
            
    except KeyboardInterrupt:
        print("\n\nVoice loop stopped.")
    finally:
        wake_detector.cleanup()


# ============================================================================
# MAIN LOOP
# ============================================================================

def main():
    """
    Main conversation loop with voice output and toggle.
    User types → Groq responds → Pacificia speaks → repeat
    """
    # Voice control (can be toggled during conversation)
    voice_enabled = True
    
    print("\n" + "="*60)
    print("PACIFICIA - SOUL MVP (Phase 2: Voice Output)")
    print("="*60)
    print(f"Persona: {PACIFICIA['name']}")
    print(f"Voice Output: {'Enabled' if voice_enabled else 'Disabled'}")
    print("\nCommands:")
    print("  'voice on'  - Enable voice output")
    print("  'voice off' - Disable voice output")
    print("  'exit'      - Quit")
    print("="*60 + "\n")
    
    # Initial greeting
    greeting = "Hey! I'm Pacificia. I can talk now!"
    print(f"Pacificia: {greeting}")
    if voice_enabled:
        speak(greeting)
    print()
    
    while True:
        # Get user input
        user_input = input("You: ").strip()
        
        # Check for commands
        if user_input.lower() in ['exit', 'quit', 'bye']:
            farewell = "Take care! I'll be here when you need me."
            print(f"\nPacificia: {farewell}\n")
            if voice_enabled:
                speak(farewell)
            break
        
        # Voice toggle commands
        if user_input.lower() == 'voice on':
            voice_enabled = True
            msg = "Voice output enabled."
            print(f"Pacificia: {msg}")
            speak(msg)
            print()
            continue
        
        if user_input.lower() == 'voice off':
            voice_enabled = False
            msg = "Voice output disabled."
            print(f"Pacificia: {msg}")
            print()
            continue
        
        # Skip empty messages
        if not user_input:
            continue
        
        # Get response from Groq
        print("Pacificia: ", end="", flush=True)
        response = get_groq_response(user_input)
        print(response)
        
        # Speak the response if enabled
        if voice_enabled:
            speak(response)
        
        print()  # Blank line for readability

if __name__ == "__main__":
    # Check if user wants voice mode
    if len(sys.argv) > 1 and sys.argv[1] == "--voice":
        voice_loop_mode()
    else:
        print("\nStarting text mode. Use --voice flag for voice loop mode.")
        print("Example: python main.py --voice\n")
        main()