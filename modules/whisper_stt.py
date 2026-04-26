"""
Whisper Speech-to-Text Module
Refactored from transcribe_demo.py for use in web application.
Real-time transcription with phrase detection and splitting.
"""

import numpy as np
import speech_recognition as sr
import whisper
import torch
from datetime import datetime, timezone
from queue import Queue
import threading
from typing import Optional, Callable, Dict


class WhisperSTT:
    """Real-time speech-to-text using Whisper model."""

    def __init__(
        self,
        model: str = "small",
        non_english: bool = False,
        energy_threshold: int = 1000,
        record_timeout: float = 2,
        phrase_timeout: float = 5.0,  # Default 5 seconds
        finalization_grace: float = 0.75,
        final_silence_padding: float = 0.8,
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
            finalization_grace: Extra time to wait for a final callback chunk
            final_silence_padding: Silence appended before final transcription
            device_index: Microphone device index (None for default)
            debug: Enable debug logging
        """
        self.model_name = model
        self.non_english = non_english
        self.energy_threshold = energy_threshold
        self.record_timeout = record_timeout
        self.phrase_timeout = phrase_timeout
        self.finalization_grace = finalization_grace
        self.final_silence_padding = final_silence_padding
        self.device_index = device_index
        self.debug = debug

        # Initialize components
        self.data_queue = Queue()
        self.phrase_bytes = bytes()
        self.phrase_time = None  # Last time we received audio
        self.finalizing_since = None
        self.final_transcription_pending = False
        self.last_partial_text = ""
        self.is_running = False
        self.listener_lock = threading.Lock()
        self.stop_background_listener = None

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
        with self.listener_lock:
            if self.is_running:
                print("Already listening.")
                return

            # Start background listener
            self.stop_background_listener = self.recorder.listen_in_background(
                self.source,
                self._record_callback,
                phrase_time_limit=self.record_timeout
            )

            self.is_running = True
            print("Started listening...")

    def stop_listening(self, clear_audio_queue: bool = False) -> None:
        """
        Stop background listening.

        Args:
            clear_audio_queue: Drop queued raw audio that should not be processed.
        """
        with self.listener_lock:
            if self.stop_background_listener:
                self.stop_background_listener(wait_for_stop=True)
                self.stop_background_listener = None
            self.is_running = False
        if clear_audio_queue:
            self.clear_audio_queue()
        print("Stopped listening.")

    def clear_audio_queue(self) -> None:
        """Drop queued raw audio without clearing the current phrase buffer."""
        while not self.data_queue.empty():
            self.data_queue.get()

    def _drain_audio_queue(self) -> bytes:
        """Collect all queued raw audio chunks into one byte string."""
        audio_chunks = []
        while not self.data_queue.empty():
            audio_chunks.append(self.data_queue.get())
        return b''.join(audio_chunks)

    def _transcribe_phrase(self, audio_bytes: bytes, pad_silence: bool = False) -> str:
        """Transcribe raw int16 phrase audio, optionally padding the final pass."""
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        if pad_silence and self.final_silence_padding > 0:
            silence = np.zeros(int(16000 * self.final_silence_padding), dtype=np.float32)
            audio_np = np.concatenate([audio_np, silence])

        return self.audio_model.transcribe(
            audio_np,
            fp16=torch.cuda.is_available()
        )['text'].strip()

    @staticmethod
    def _choose_final_text(final_text: str, partial_text: str) -> str:
        """
        Avoid replacing a richer live transcript with a shorter final transcript.

        Whisper can occasionally drop the tail on the final pass, especially when
        the audio ends right after speech. If the final text is clearly a prefix
        of the last live partial, keep the partial.
        """
        final_text = (final_text or "").strip()
        partial_text = (partial_text or "").strip()

        if not partial_text:
            return final_text
        if not final_text:
            return partial_text

        normalized_final = " ".join(final_text.lower().split())
        normalized_partial = " ".join(partial_text.lower().split())

        if normalized_partial.startswith(normalized_final) and len(partial_text) > len(final_text):
            return partial_text

        if len(final_text) < len(partial_text) * 0.85 and normalized_final in normalized_partial:
            return partial_text

        return final_text

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
            audio_data = self._drain_audio_queue()
            if not audio_data:
                return None

            # Update timestamp - marks when we LAST received audio
            self.phrase_time = now
            self.finalizing_since = None
            self.final_transcription_pending = False

            # Accumulate audio
            self.phrase_bytes += audio_data

            # Transcribe current accumulated audio
            text = self._transcribe_phrase(self.phrase_bytes)
            self.last_partial_text = text

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
            if self.finalizing_since is None:
                self.finalizing_since = now
                if self.debug:
                    print("[DEBUG] Timeout reached, waiting briefly for final audio callback.")
                return {
                    'text': '',
                    'phrase_complete': False,
                    'pausing': True,
                    'time_remaining': 0,
                    'timestamp': now
                }

            grace_elapsed = (now - self.finalizing_since).total_seconds()
            if grace_elapsed < self.finalization_grace:
                return {
                    'text': '',
                    'phrase_complete': False,
                    'pausing': True,
                    'time_remaining': 0,
                    'timestamp': now
                }

            late_audio = self._drain_audio_queue()
            if late_audio:
                if self.debug:
                    print("[DEBUG] Late audio arrived during finalization grace; continuing phrase.")
                self.phrase_time = now
                self.finalizing_since = None
                self.final_transcription_pending = False
                self.phrase_bytes += late_audio
                text = self._transcribe_phrase(self.phrase_bytes)
                self.last_partial_text = text
                return {
                    'text': text,
                    'phrase_complete': False,
                    'pausing': False,
                    'time_remaining': self.phrase_timeout,
                    'timestamp': now
                }

            if not self.final_transcription_pending:
                self.final_transcription_pending = True
                return {
                    'text': '',
                    'phrase_complete': False,
                    'pausing': True,
                    'finalizing': True,
                    'time_remaining': 0,
                    'timestamp': now
                }

            if self.debug:
                print(f"[DEBUG] ✓ Phrase complete! Timeout reached.")

            # Transcribe final phrase
            final_text = self._transcribe_phrase(self.phrase_bytes, pad_silence=True)
            final_text = self._choose_final_text(final_text, self.last_partial_text)

            # Reset state
            self.phrase_bytes = bytes()
            self.phrase_time = None
            self.finalizing_since = None
            self.final_transcription_pending = False
            self.last_partial_text = ""

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

    print("\nInitializing Whisper STT (small model)...")

    def on_transcription(data):
        if data['pausing']:
            print(f"\r[PAUSING {data['time_remaining']:.1f}s] {data.get('last_text', '')}", end='', flush=True)
        else:
            print(f"\r[LISTENING] {data['text']}", end='', flush=True)

    def on_phrase_complete(data):
        print(f"\n✓ COMPLETE: '{data['text']}'")

    stt = WhisperSTT(
        model="small",
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
