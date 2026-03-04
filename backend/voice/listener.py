"""
SOUL — Voice Pipeline
=======================
Two-stage voice input:
  Stage 1: Porcupine wake-word detection (tiny, always-on, CPU-light)
  Stage 2: Whisper transcription (fires only after wake word)

Also handles TTS output via pyttsx3 (local, no API cost) with
ElevenLabs as optional upgrade path.
"""

import asyncio
import io
import os
import queue
import threading
import time
import wave
from typing import Callable, Optional

# Audio capture
import pyaudio

# Speech-to-text (local Whisper)
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    print("[Voice] Whisper not installed. STT unavailable.")

# Wake word (Porcupine)
try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False
    print("[Voice] Porcupine not installed. Using keyword fallback.")

# TTS
try:
    import pyttsx3
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False
    print("[Voice] pyttsx3 not installed. TTS unavailable.")


SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 512
RECORD_SECONDS_MAX = 10     # max command length
SILENCE_THRESHOLD = 500     # amplitude below this = silence
SILENCE_TIMEOUT = 1.5       # seconds of silence before ending recording


class VoiceListener:
    """
    Listens for wake word, then records user command,
    then fires transcription callback.
    """

    def __init__(
        self,
        wake_word: str = "hey pacify",
        on_command: Callable[[str], None] = None,
        porcupine_access_key: str = ""
    ):
        self.wake_word = wake_word.lower()
        self.on_command = on_command
        self.porcupine_key = porcupine_access_key or os.environ.get("PORCUPINE_KEY", "")
        self._running = False
        self._audio = None
        self._whisper_model = None
        self._tts_engine = None

        # Load whisper model (base = fast, good enough for commands)
        if WHISPER_AVAILABLE:
            print("[Voice] Loading Whisper base model...")
            self._whisper_model = whisper.load_model("base")
            print("[Voice] Whisper ready.")

        if TTS_AVAILABLE:
            self._tts_engine = pyttsx3.init()
            self._configure_tts()

    def _configure_tts(self):
        """Set TTS rate and voice to match entity personality."""
        if not self._tts_engine:
            return
        self._tts_engine.setProperty("rate", 165)   # slightly slower = more natural
        self._tts_engine.setProperty("volume", 0.9)

        # Try to find a feminine voice
        voices = self._tts_engine.getProperty("voices")
        for voice in voices:
            if "female" in voice.name.lower() or "zira" in voice.name.lower():
                self._tts_engine.setProperty("voice", voice.id)
                break

    def speak(self, text: str):
        """Speak text aloud (blocking). Run in thread to avoid blocking event loop."""
        if not TTS_AVAILABLE or not self._tts_engine:
            print(f"[TTS] {text}")
            return

        def _speak():
            self._tts_engine.say(text)
            self._tts_engine.runAndWait()

        threading.Thread(target=_speak, daemon=True).start()

    def start_listening(self):
        """Start the wake-word detection loop in a background thread."""
        self._running = True
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()
        return thread

    def stop(self):
        self._running = False

    def _listen_loop(self):
        """
        Main loop:
        1. Open audio stream
        2. Feed to Porcupine for wake word detection
        3. On wake word → record command → transcribe → callback
        """
        self._audio = pyaudio.PyAudio()

        if PORCUPINE_AVAILABLE and self.porcupine_key:
            self._porcupine_loop()
        else:
            print("[Voice] Running in DEMO mode — type commands in console.")
            self._console_fallback_loop()

    def _porcupine_loop(self):
        porcupine = pvporcupine.create(
            access_key=self.porcupine_key,
            keywords=["hey siri"]  # closest built-in; replace with custom model for production
        )

        stream = self._audio.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length
        )

        print(f"[Voice] Listening for wake word: '{self.wake_word}'")

        try:
            while self._running:
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                import struct
                pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)
                result = porcupine.process(pcm_unpacked)

                if result >= 0:
                    print("[Voice] Wake word detected!")
                    command = self._record_command()
                    if command and self.on_command:
                        self.on_command(command)
        finally:
            stream.stop_stream()
            stream.close()
            porcupine.delete()

    def _record_command(self) -> Optional[str]:
        """Record audio until silence, then transcribe with Whisper."""
        print("[Voice] Recording command...")

        stream = self._audio.open(
            rate=SAMPLE_RATE,
            channels=CHANNELS,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=CHUNK
        )

        frames = []
        silent_chunks = 0
        max_silent = int(SILENCE_TIMEOUT * SAMPLE_RATE / CHUNK)

        for _ in range(int(SAMPLE_RATE / CHUNK * RECORD_SECONDS_MAX)):
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)

            # Simple silence detection
            import struct
            amplitude = max(abs(x) for x in struct.unpack(f"{CHUNK}h", data))
            if amplitude < SILENCE_THRESHOLD:
                silent_chunks += 1
                if silent_chunks > max_silent:
                    break
            else:
                silent_chunks = 0

        stream.stop_stream()
        stream.close()

        if not frames or not WHISPER_AVAILABLE:
            return None

        # Write to WAV buffer and transcribe
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(self._audio.get_sample_size(pyaudio.paInt16))
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(b"".join(frames))

        buf.seek(0)
        import numpy as np
        import soundfile as sf
        audio_data, _ = sf.read(buf)

        result = self._whisper_model.transcribe(audio_data, language="en")
        text = result["text"].strip()
        print(f"[Voice] Heard: '{text}'")
        return text if text else None

    def _console_fallback_loop(self):
        """Fallback for dev mode — type commands."""
        while self._running:
            try:
                text = input(f"\n[DEMO] Type command (or 'quit'): ").strip()
                if text.lower() == "quit":
                    self._running = False
                    break
                if text and self.on_command:
                    self.on_command(text)
            except (EOFError, KeyboardInterrupt):
                break
