"""
Socratic Method Bot - Core Modules
"""

from .pdf_parser import PDFParser
from .ollama_client import OllamaClient
from .conversation_manager import ConversationManager

__all__ = [
    'PDFParser',
    'OllamaClient',
    'ConversationManager'
]


def __getattr__(name):
    """Lazy-load optional voice modules so text-only installs can import the package."""
    if name == 'WhisperSTT':
        from .whisper_stt import WhisperSTT
        return WhisperSTT
    if name == 'TTSEngine':
        from .tts_engine import TTSEngine
        return TTSEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
