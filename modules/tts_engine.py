"""
Text-to-Speech Engine Module
Handles converting bot responses to speech audio.
"""

import pyttsx3
import os
from typing import Optional
import threading


class TTSEngine:
    """Text-to-speech engine using pyttsx3 (offline)."""

    def __init__(self, rate: int = 150, volume: float = 0.9, voice_index: int = 0):
        """
        Initialize TTS engine.

        Args:
            rate: Speech rate (words per minute)
            volume: Volume level (0.0 to 1.0)
            voice_index: Voice index to use (0 for default)
        """
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', rate)
        self.engine.setProperty('volume', volume)

        # Set voice
        voices = self.engine.getProperty('voices')
        if voice_index < len(voices):
            self.engine.setProperty('voice', voices[voice_index].id)

        self.is_speaking = False
        self._lock = threading.Lock()

    def speak(self, text: str, blocking: bool = True) -> None:
        """
        Speak text aloud.

        Args:
            text: Text to speak
            blocking: Whether to block until speech completes
        """
        with self._lock:
            if self.is_speaking:
                self.engine.stop()

            self.is_speaking = True

        try:
            self.engine.say(text)
            if blocking:
                self.engine.runAndWait()
            else:
                # Run in separate thread
                threading.Thread(target=self.engine.runAndWait, daemon=True).start()
        finally:
            with self._lock:
                self.is_speaking = False

    def speak_async(self, text: str) -> None:
        """
        Speak text asynchronously (non-blocking).

        Args:
            text: Text to speak
        """
        self.speak(text, blocking=False)

    def save_to_file(self, text: str, output_path: str) -> bool:
        """
        Save speech to audio file.

        Args:
            text: Text to convert
            output_path: Path to save audio file

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            self.engine.save_to_file(text, output_path)
            self.engine.runAndWait()
            return True
        except Exception as e:
            print(f"Error saving TTS to file: {e}")
            return False

    def stop(self) -> None:
        """Stop current speech."""
        self.engine.stop()

    def list_voices(self) -> list:
        """
        List available voices.

        Returns:
            List of tuples (index, name, languages)
        """
        voices = self.engine.getProperty('voices')
        voice_list = []
        for idx, voice in enumerate(voices):
            voice_list.append((idx, voice.name, voice.languages))
        return voice_list

    def set_voice(self, voice_index: int) -> bool:
        """
        Set voice by index.

        Args:
            voice_index: Index of voice to use

        Returns:
            True if successful, False otherwise
        """
        try:
            voices = self.engine.getProperty('voices')
            if 0 <= voice_index < len(voices):
                self.engine.setProperty('voice', voices[voice_index].id)
                return True
            return False
        except Exception:
            return False

    def set_rate(self, rate: int) -> None:
        """
        Set speech rate.

        Args:
            rate: Words per minute (typical range: 100-250)
        """
        self.engine.setProperty('rate', rate)

    def set_volume(self, volume: float) -> None:
        """
        Set volume level.

        Args:
            volume: Volume (0.0 to 1.0)
        """
        self.engine.setProperty('volume', max(0.0, min(1.0, volume)))


if __name__ == "__main__":
    # Test the TTS engine
    print("Initializing TTS engine...")
    tts = TTSEngine()

    print("\nAvailable voices:")
    for idx, name, langs in tts.list_voices():
        print(f"  [{idx}] {name} - {langs}")

    print("\nTesting TTS...")
    test_text = "Hello! I am your Socratic tutor. Let's discuss your essay and strengthen your arguments through critical questioning."

    print(f"Speaking: '{test_text}'")
    tts.speak(test_text)

    print("\nTesting file save...")
    output_file = "/tmp/test_tts.aiff"
    if tts.save_to_file("This is a test of file saving.", output_file):
        print(f"✓ Saved to {output_file}")
    else:
        print("✗ Failed to save file")

    print("\nTTS test complete.")
