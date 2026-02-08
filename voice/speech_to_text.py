"""
Speech-to-Text - FREE VERSION
Uses Google's free speech recognition (no API key needed)
Alternative: Vosk for offline use
"""

import os
import wave
import sys

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("PyAudio unavailable. Install: pip install pyaudio")

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    SR_AVAILABLE = False
    print("SpeechRecognition unavailable. Install: pip install SpeechRecognition")


class SpeechToText:
    """
    Records audio and converts to text using FREE speech recognition.
    No API keys required!
    """
    
    def __init__(self):
        """Initialize speech-to-text engine."""
        if SR_AVAILABLE:
            self.recognizer = sr.Recognizer()
            self.microphone = sr.Microphone() if PYAUDIO_AVAILABLE else None
            
            # Adjust for ambient noise on first run
            if self.microphone:
                print("Calibrating microphone for ambient noise... (one-time)")
                with self.microphone as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=1)
                print("Calibration complete.")
        else:
            self.recognizer = None
            self.microphone = None
    
    def is_available(self):
        """Check if speech-to-text is available."""
        return SR_AVAILABLE and PYAUDIO_AVAILABLE
    
    def listen(self, timeout=5, phrase_time_limit=10):
        """
        Listen to microphone and transcribe to text.
        
        Args:
            timeout (int): Seconds to wait for speech to start
            phrase_time_limit (int): Max seconds for phrase
        
        Returns:
            str: Transcribed text or None if failed
        """
        if not self.is_available():
            print("Speech recognition unavailable")
            return None
        
        try:
            print("Listening...")
            
            with self.microphone as source:
                # Listen for audio
                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_time_limit
                )
            
            print("Processing speech...")
            
            # Transcribe using Google (free, no API key)
            text = self.recognizer.recognize_google(audio)
            
            return text.strip()
            
        except sr.WaitTimeoutError:
            print("No speech detected (timeout)")
            return None
        except sr.UnknownValueError:
            print("Could not understand audio")
            return None
        except sr.RequestError as e:
            print(f"Google Speech Recognition error: {e}")
            print("Check your internet connection")
            return None
        except Exception as e:
            print(f"Unexpected error: {e}")
            return None
    
    def listen_with_voice_feedback(self):
        """
        Listen with better user feedback.
        Returns transcribed text or None.
        """
        if not self.is_available():
            return None
        
        try:
            with self.microphone as source:
                print("Speak now...")
                
                # Adjust for ambient noise briefly
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                
                # Listen
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
            
            print("Got it! Processing...")
            
            # Transcribe
            text = self.recognizer.recognize_google(audio)
            return text.strip()
            
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            print("Network error - check internet connection")
            return None
        except Exception as e:
            print(f"Error: {e}")
            return None


def test_speech_to_text():
    """Test speech-to-text functionality."""
    print("Speech-to-Text Test (FREE VERSION)")
    print("="*60)
    print("Uses Google Speech Recognition (no API key needed)")
    print("="*60)
    
    stt = SpeechToText()
    
    if not stt.is_available():
        print("\nSpeech recognition unavailable.")
        print("Install: pip install SpeechRecognition pyaudio")
        return
    
    print("\nSpeak after the prompt...")
    text = stt.listen_with_voice_feedback()
    
    if text:
        print(f"\nYou said: '{text}'")
    else:
        print("\nFailed to transcribe")


if __name__ == "__main__":
    test_speech_to_text()