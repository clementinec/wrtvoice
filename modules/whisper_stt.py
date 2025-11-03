"""
Whisper Speech-to-Text Module
Refactored from transcribe_demo.py for use in web application.
Real-time transcription with phrase detection and splitting.
"""

import numpy as np
import speech_recognition as sr
import whisper
import torch
from datetime import datetime, timedelta, timezone
from queue import Queue
from typing import Optional, Callable, Dict
from sys import platform
import threading


class WhisperSTT:
    """Real-time speech-to-text using Whisper model."""

    def __init__(
        self,
        model: str = "base",
        non_english: bool = False,
        energy_threshold: int = 1000,
        record_timeout: float = 2,
        phrase_timeout: float = 5.0,  # Default 5 seconds
        device_index: Optional[int] = None,
        debug: bool = False
    ):
        """
        Initialize Whisper STT engine.

        Args:
            model: Whisper model size (tiny, base, small, medium, large)
            non_english: Use non-English model variant
            energy_threshold: Mic energy level for detection
            record_timeout: How real-time the recording is (seconds)
            phrase_timeout: Silence duration before new phrase (seconds)
            device_index: Microphone device index (None for default)
            debug: Enable debug logging
        """
        self.model_name = model
        self.non_english = non_english
        self.energy_threshold = energy_threshold
        self.record_timeout = record_timeout
        self.phrase_timeout = phrase_timeout
        self.device_index = device_index
        self.debug = debug

        # Initialize components
        self.data_queue = Queue()
        self.phrase_bytes = bytes()
        self.phrase_time = None  # Last time we received audio
        self.is_running = False
        self.listener_thread = None

        # Callbacks
        self.on_transcription: Optional[Callable] = None
        self.on_phrase_complete: Optional[Callable] = None

        # Load Whisper model
        print(f"Loading Whisper model '{model}'...")
        model_name = model
        if model != "large" and not non_english:
            model_name = model + ".en"
        self.audio_model = whisper.load_model(model_name)
        print("Model loaded successfully.")

        # Initialize speech recognizer
        self.recorder = sr.Recognizer()
        self.recorder.energy_threshold = energy_threshold
        self.recorder.dynamic_energy_threshold = False

        # Initialize microphone
        self.source = self._initialize_microphone()

    def _initialize_microphone(self) -> sr.Microphone:
        """Initialize microphone source."""
        if self.device_index is not None:
            source = sr.Microphone(sample_rate=16000, device_index=self.device_index)
        else:
            source = sr.Microphone(sample_rate=16000)

        # Adjust for ambient noise
        with source:
            self.recorder.adjust_for_ambient_noise(source)

        return source

    def _record_callback(self, _, audio: sr.AudioData) -> None:
        """
        Threaded callback to receive audio data.

        Args:
            audio: AudioData from the microphone
        """
        data = audio.get_raw_data()
        self.data_queue.put(data)

    def start_listening(self) -> None:
        """Start background listening thread."""
        if self.is_running:
            print("Already listening.")
            return

        # Start background listener
        self.recorder.listen_in_background(
            self.source,
            self._record_callback,
            phrase_time_limit=self.record_timeout
        )

        self.is_running = True
        print("Started listening...")

    def stop_listening(self) -> None:
        """Stop background listening."""
        self.is_running = False
        print("Stopped listening.")

    def process_audio_queue(self) -> Optional[Dict]:
        """
        Process audio from queue and return transcription.

        Logic:
        1. Process any new audio first
        2. If we have accumulated audio and user stopped (no new audio), start countdown
        3. Countdown starts from FULL timeout value when user stops
        4. If countdown reaches 0, finalize phrase

        Returns:
            Dictionary with transcription info or None if no activity
        """
        now = datetime.now(timezone.utc)

        # FIRST: Check if new audio is available
        has_new_audio = not self.data_queue.empty()

        if has_new_audio:
            # Get new audio from queue
            audio_data = b''.join(self.data_queue.queue)
            self.data_queue.queue.clear()

            # Update timestamp - marks when we LAST received audio
            self.phrase_time = now

            # Accumulate audio
            self.phrase_bytes += audio_data

            # Transcribe current accumulated audio
            audio_np = np.frombuffer(self.phrase_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            text = self.audio_model.transcribe(audio_np, fp16=torch.cuda.is_available())['text'].strip()

            if self.debug:
                print(f"[DEBUG] New audio received, transcribed: '{text[:50]}...'")

            result = {
                'text': text,
                'phrase_complete': False,
                'pausing': False,
                'time_remaining': self.phrase_timeout,  # Full timeout available
                'timestamp': now
            }

            if self.on_transcription:
                self.on_transcription(result)

            return result

        # SECOND: No new audio - check if we have accumulated audio (user stopped talking)
        if not self.phrase_time or not self.phrase_bytes:
            # No accumulated audio yet, nothing to do
            return None

        # Calculate how long since user stopped talking
        time_since_stopped = (now - self.phrase_time).total_seconds()
        time_remaining = self.phrase_timeout - time_since_stopped

        if self.debug:
            print(f"[DEBUG] Silence: {time_since_stopped:.2f}s / {self.phrase_timeout}s, remaining: {time_remaining:.2f}s")

        # THIRD: Check if countdown finished (timeout reached)
        if time_since_stopped >= self.phrase_timeout:
            if self.debug:
                print(f"[DEBUG] ✓ Phrase complete! Timeout reached.")

            # Transcribe final phrase
            audio_np = np.frombuffer(self.phrase_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            final_text = self.audio_model.transcribe(audio_np, fp16=torch.cuda.is_available())['text'].strip()

            # Reset state
            self.phrase_bytes = bytes()
            self.phrase_time = None

            result = {
                'text': final_text,
                'phrase_complete': True,
                'pausing': False,
                'time_remaining': 0,
                'timestamp': now
            }

            if self.on_phrase_complete and final_text:
                self.on_phrase_complete(result)

            return result

        # FOURTH: Still counting down (pausing state)
        # Return pausing status with time remaining
        return {
            'text': '',  # No new text, just status update
            'phrase_complete': False,
            'pausing': True,
            'time_remaining': max(0, time_remaining),
            'timestamp': now
        }

    @staticmethod
    def list_microphones() -> list:
        """
        List available microphone devices.

        Returns:
            List of tuples (index, name)
        """
        microphones = []
        for index, name in enumerate(sr.Microphone.list_microphone_names()):
            microphones.append((index, name))
        return microphones


if __name__ == "__main__":
    # Test the Whisper STT
    import time

    print("Available microphones:")
    for idx, name in WhisperSTT.list_microphones():
        print(f"  [{idx}] {name}")

    print("\nInitializing Whisper STT (base model)...")

    def on_transcription(data):
        if data['pausing']:
            print(f"\r[PAUSING {data['time_remaining']:.1f}s] {data.get('last_text', '')}", end='', flush=True)
        else:
            print(f"\r[LISTENING] {data['text']}", end='', flush=True)

    def on_phrase_complete(data):
        print(f"\n✓ COMPLETE: '{data['text']}'")

    stt = WhisperSTT(
        model="base",
        phrase_timeout=3.0,
        record_timeout=2.0,
        debug=True
    )

    stt.on_transcription = on_transcription
    stt.on_phrase_complete = on_phrase_complete

    stt.start_listening()

    print("\n🎤 Listening... (Ctrl+C to stop)\n")

    last_text = ""
    try:
        while True:
            result = stt.process_audio_queue()
            if result:
                if result['pausing']:
                    # Store last text for display during pause
                    result['last_text'] = last_text
                    on_transcription(result)
                elif not result['phrase_complete']:
                    last_text = result['text']
                    on_transcription(result)
                elif result['phrase_complete']:
                    on_phrase_complete(result)
                    last_text = ""
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\n\nStopping...")
        stt.stop_listening()
