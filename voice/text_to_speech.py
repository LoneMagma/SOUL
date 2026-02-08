"""
Text-to-Speech Engine
Supports both Edge TTS (high quality) and pyttsx3 (fallback)
"""

import sys
import asyncio
import os
from pathlib import Path


# Try to import Edge TTS (preferred)
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

# Fallback to pyttsx3
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


class VoiceEngine:
    """
    Handles text-to-speech conversion.
    Tries Edge TTS first (better quality), falls back to pyttsx3.
    """
    
    def __init__(self, use_edge_tts=True):
        """
        Initialize TTS engine.
        
        Args:
            use_edge_tts (bool): Try to use Edge TTS if available
        """
        self.edge_tts = None
        self.pyttsx3_engine = None
        self.voice_name = None
        
        # Try Edge TTS first
        if use_edge_tts and EDGE_TTS_AVAILABLE:
            self._init_edge_tts()
        
        # Fallback to pyttsx3
        if not self.edge_tts and PYTTSX3_AVAILABLE:
            self._init_pyttsx3()
        
        if not self.edge_tts and not self.pyttsx3_engine:
            print("WARNING: No TTS engine available. Voice output disabled.")
            print("Install edge-tts: pip install edge-tts")
    
    def _init_edge_tts(self):
        """Initialize Edge TTS with a good female voice."""
        # Best female voices for English (US)
        # You can change this to other voices - see list_edge_voices()
        voices = [
            "en-US-AriaNeural",      # Young female, friendly
            "en-US-JennyNeural",     # Professional female
            "en-GB-SoniaNeural",     # British female
            "en-AU-NatashaNeural",   # Australian female
        ]
        
        self.voice_name = voices[0]  # Default to Aria (young, friendly)
        self.edge_tts = True
        print(f"Voice Engine: Edge TTS ({self.voice_name})")
    
    def _init_pyttsx3(self):
        """Initialize pyttsx3 as fallback."""
        try:
            self.pyttsx3_engine = pyttsx3.init()
            
            # Try to set female voice
            voices = self.pyttsx3_engine.getProperty('voices')
            if len(voices) > 1:
                self.pyttsx3_engine.setProperty('voice', voices[1].id)
            
            # Slower and clearer
            self.pyttsx3_engine.setProperty('rate', 150)
            self.pyttsx3_engine.setProperty('volume', 0.9)
            
            print("Voice Engine: pyttsx3 (fallback - lower quality)")
        except Exception as e:
            print(f"pyttsx3 initialization failed: {e}")
            self.pyttsx3_engine = None
    
    def speak(self, text):
        """
        Convert text to speech.
        
        Args:
            text (str): Text to speak
        """
        if self.edge_tts:
            self._speak_edge_tts(text)
        elif self.pyttsx3_engine:
            self._speak_pyttsx3(text)
    
    def _speak_edge_tts(self, text):
        """Speak using Edge TTS (async function wrapped for sync usage)."""
        try:
            # Run async function in sync context
            asyncio.run(self._async_speak_edge_tts(text))
        except Exception as e:
            print(f"Edge TTS failed: {e}")
            print("Falling back to pyttsx3...")
            if PYTTSX3_AVAILABLE and not self.pyttsx3_engine:
                self._init_pyttsx3()
            if self.pyttsx3_engine:
                self._speak_pyttsx3(text)
    
    async def _async_speak_edge_tts(self, text):
        """Async function to generate and play speech with Edge TTS."""
        # Generate speech to temporary file
        temp_file = "temp_speech.mp3"
        
        communicate = edge_tts.Communicate(text, self.voice_name)
        await communicate.save(temp_file)
        
        # Play the audio file
        self._play_audio_file(temp_file)
        
        # Clean up
        try:
            os.remove(temp_file)
        except:
            pass
    
    def _play_audio_file(self, filepath):
        """
        Play an audio file using pygame (fast, no new tabs).
        
        Args:
            filepath (str): Path to audio file
        """
        try:
            import pygame
            
            # Initialize pygame mixer if not already done
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            
            # Load and play
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            
            # Wait for playback to finish
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
                
        except Exception as e:
            print(f"Audio playback failed: {e}")
            # Fallback: print text instead of opening browser
            print("(Voice output unavailable - showing text only)")
    
    def _speak_pyttsx3(self, text):
        """Speak using pyttsx3 (fallback)."""
        if not self.pyttsx3_engine:
            return
        
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
        except Exception as e:
            print(f"pyttsx3 speech failed: {e}")
    
    def set_voice(self, voice_name):
        """
        Change Edge TTS voice.
        
        Args:
            voice_name (str): Voice identifier (e.g., "en-US-AriaNeural")
        """
        if self.edge_tts:
            self.voice_name = voice_name
            print(f"Voice changed to: {voice_name}")
        else:
            print("Edge TTS not available. Cannot change voice.")
    
    def list_edge_voices(self):
        """Print all available Edge TTS voices."""
        if not EDGE_TTS_AVAILABLE:
            print("Edge TTS not installed. Run: pip install edge-tts")
            return
        
        print("\nFetching available Edge TTS voices...\n")
        asyncio.run(self._async_list_voices())
    
    async def _async_list_voices(self):
        """Async function to list Edge TTS voices."""
        voices = await edge_tts.list_voices()
        
        # Filter English voices
        english_voices = [v for v in voices if v['Locale'].startswith('en-')]
        
        print("English Female Voices (Recommended):\n" + "="*60)
        for voice in english_voices:
            if 'Female' in voice['Gender']:
                print(f"{voice['ShortName']}")
                print(f"  Locale: {voice['Locale']}")
                print(f"  Name: {voice['FriendlyName']}")
                print()


# Global voice engine instance
_voice_engine = None


def get_voice_engine():
    """Get or create global voice engine."""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine(use_edge_tts=True)
    return _voice_engine


def speak(text):
    """
    Speak text using best available TTS engine.
    
    Args:
        text (str): Text to speak
    """
    engine = get_voice_engine()
    engine.speak(text)


def set_voice(voice_name):
    """
    Change voice (Edge TTS only).
    
    Args:
        voice_name (str): Voice identifier
    """
    engine = get_voice_engine()
    engine.set_voice(voice_name)


def list_voices():
    """List all available Edge TTS voices."""
    engine = get_voice_engine()
    engine.list_edge_voices()


def test_voice():
    """Test the voice engine."""
    print("Testing voice engine...")
    speak("Hello! I'm Pacificia, the soul of this computer. I sound much better now!")
    print("Voice test complete.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--list":
            list_voices()
        else:
            text = " ".join(sys.argv[1:])
            speak(text)
    else:
        test_voice()
