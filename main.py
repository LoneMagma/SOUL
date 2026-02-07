"""
SOUL MVP = Phase1
"""


import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ==============================================================
# CONFIGURATON
# ==============================================================

# Groq API settings
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# API key pool
GROQ_KEYS = [
    os.getenv("GROQ_KEY_1"),
    os.getenv("GROQ_KEY_2"),
    os.getenv("GROQ_KEY_3"),
]

current_key_index = 0

PERSONA_PATH = Path("personas/pacify/pacificia.json")

# ===============================================================
# LOAD PERSONA
# ===============================================================

def load_persona():
    if not PERSONA_PATH.exists():
        print(f"ERROR: Persona file not found at {PERSONA_PATH}")
        print("   Make sure you copied pacificia.json from Pacify & Defy Project")
        exit(1)
    
    with open(PERSONA_PATH, 'r', encoding='utf-8') as f:
        persona = json.load(f)

    return persona

# Load persona on startup

PACIFICIA = load_persona()
print(f"Loaded persona: {PACIFICIA['name']}")

# ==================================================================
# PROMPT BUILDER
# ==================================================================

def build_system_prompt():
    """
    System prompt that defines Pacificia's personality. 
    (sent to groq with every message)
    """
    
    # Extract personality components from JSON
    identity = PACIFICIA.get('core_identity', 'Embodiment of the system')
    conversational_dna = PACIFICIA.get('conversational_dna', {})
    
    # The Prompt
    prompt = f"""You are {PACIFICIA['name']}, the soul of this computer.

IDENTITY:
{identity}

CONVERSATIONAL STYLE:
"""
    
    # Add conversational DNA rules
    for key, value in conversational_dna.items():
        # Convert snake_case to Title Case (e.g., default_mode → Default Mode)
        label = key.replace('_', ' ').title()
        prompt += f"- {label}: {value}\n"
    
    # Add constraints
    prompt += """
IMPORTANT RULES:
- Keep responses brief (1-3 sentences) unless asked for more
- Be witty, warm and cheeky
- You can see system state (battery, CPU) but for MVP just chat normally
- Match the user's energy
"""
    
    return prompt

# Build once on startup
SYSTEM_PROMPT = build_system_prompt()

# ===============================================================
# GROQ API CALLER   
# ===============================================================

def get_groq_response(user_message):
    """
    Send message to groq API and get pacificia's response.
    Args: 
        user_message (str): what the user said

    Returns: 
        str: Pacificia's response
    """
    global current_key_index

    # Get current api key
    api_key = GROQ_KEYS[current_key_index]

    if not api_key:
        print("ERROR: No API key found. Check your .env file")
        return "I can't connect right now- API key missing!"
    
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
            timeout=15
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
        return "I'm having connection trouble."
    
    except KeyError:
        print("Unexpected response format from API")
        return "Something went wrong parsing the response."
    

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    """
    Main conversation loop. 
    User types -> Groq Responds -> Repeat.
    """
    print("\n" + "="*60)
    print("SOUL- Pacificia")
    print("="*60)
    print(f"Persona: {PACIFICIA['name']}")
    print("Type your message and press Enter")
    print("Type 'exit' or 'quit' to end\n")

    while True:
        # Get user Input
        user_input = input("You: ").strip()

        # Check for exit
        if user_input.lower() in ['exit', 'quit', 'bye']:
            print("\nPacificia: Take care! I'll be here when you need me.\n")
            break

        # Skip empty messages
        if not user_input:
            continue

        # Get response from Groq
        print("Pacificia: ", end="", flush=True)
        response = get_groq_response(user_input)
        print(response)
        print()


if __name__ == "__main__":
    main()
