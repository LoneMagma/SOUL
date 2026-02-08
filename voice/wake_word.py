"""
Wake Word Detection - "Hey Pacificia"
Uses Picovoice Porcupine for always-listening activation trigger
"""

import os
import struct
import sys

try:
    import pvporcupine
    import pyaudio
    WAKE_WORD_AVAILABLE = True
except ImportError:
    WAKE_WORD_AVAILABLE = False
    print("Wake word detection unavailable. Install: pip install pvporcupine pyaudio")


class WakeWordDetector:
    """
    Listens for "Hey Pacificia" wake word in background.
    Uses Picovoice Porcupine (free tier: 3 wake words).
    """
    
    def __init__(self, access_key=None, sensitivity=0.5):
        """
        Initialize wake word detector.
        
        Args:
            access_key (str): Picovoice API key (get from console.picovoice.ai)
            sensitivity (float): Detection sensitivity (0.0 to 1.0)
                                0.5 = balanced, higher = more sensitive
        """
        if not WAKE_WORD_AVAILABLE:
            self.porcupine = None
            self.audio_stream = None
            return
        
        # Get API key from env or parameter
        self.access_key = access_key or os.getenv("PICOVOICE_KEY")
        
        if not self.access_key:
            print("ERROR: PICOVOICE_KEY not found in .env file")
            print("Get free key at: https://console.picovoice.ai/")
            self.porcupine = None
            self.audio_stream = None
            return
        
        try:
            # Initialize Porcupine with built-in "jarvis" keyword
            # (sounds similar to "Hey Pacificia")
            # For custom wake word, you'd train at picovoice.ai
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=["jarvis"],  # Built-in keyword (free)
                sensitivities=[sensitivity]
            )
            
            # Initialize audio stream
            self.pa = pyaudio.PyAudio()
            self.audio_stream = self.pa.open(
                rate=self.porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.porcupine.frame_length
            )
            
            print("Wake word detector initialized (say 'Jarvis' to activate)")
            print("Note: Custom 'Hey Pacificia' requires Picovoice account upgrade")
            
        except Exception as e:
            print(f"Wake word initialization failed: {e}")
            self.porcupine = None
            self.audio_stream = None
    
    def is_available(self):
        """Check if wake word detection is available."""
        return self.porcupine is not None
    
    def wait_for_wake_word(self):
        """
        Block until wake word is detected.
        Returns immediately if wake word detection unavailable.
        """
        if not self.is_available():
            print("\nWake word detection unavailable. Press Enter to continue.")
            input()
            return
        
        print("\nListening for wake word...")
        
        try:
            while True:
                # Read audio frame
                pcm = self.audio_stream.read(
                    self.porcupine.frame_length,
                    exception_on_overflow=False
                )
                pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm)
                
                # Process frame
                keyword_index = self.porcupine.process(pcm)
                
                if keyword_index >= 0:
                    print("Wake word detected!")
                    return
                    
        except KeyboardInterrupt:
            print("\nWake word detection stopped.")
            return
    
    def cleanup(self):
        """Clean up resources."""
        if self.audio_stream:
            self.audio_stream.close()
        if hasattr(self, 'pa') and self.pa:
            self.pa.terminate()
        if self.porcupine:
            self.porcupine.delete()


def test_wake_word():
    """Test wake word detection."""
    print("Wake Word Detection Test")
    print("="*60)
    
    detector = WakeWordDetector()
    
    if not detector.is_available():
        print("Cannot test - wake word detection unavailable")
        return
    
    print("Say 'Jarvis' to test detection")
    print("Press Ctrl+C to stop")
    print("="*60)
    
    try:
        while True:
            detector.wait_for_wake_word()
            print("Detection successful! Listening again...")
    except KeyboardInterrupt:
        print("\nTest stopped.")
    finally:
        detector.cleanup()


if __name__ == "__main__":
    test_wake_word()