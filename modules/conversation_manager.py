"""
Conversation Manager Module
Manages conversation flow, storage, and time-stamped JSON persistence.
"""

import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path


class ConversationManager:
    """Manages conversation sessions with JSON storage."""

    def __init__(self, storage_dir: str = "conversations"):
        """
        Initialize conversation manager.

        Args:
            storage_dir: Directory to store conversation JSON files
        """
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

        # Current session data
        self.session_id: Optional[str] = None
        self.pdf_context: str = ""
        self.pdf_metadata: Dict = {}
        self.conversation: List[Dict] = []
        self.session_start: Optional[datetime] = None

    def start_session(self, pdf_context: str, pdf_metadata: Optional[Dict] = None) -> str:
        """
        Start a new conversation session.

        Args:
            pdf_context: First 500 words from the PDF
            pdf_metadata: Metadata about the PDF

        Returns:
            Session ID (timestamp-based)
        """
        # Use timezone-aware UTC to avoid local/UTC mismatches
        self.session_start = datetime.now(timezone.utc)
        self.session_id = self.session_start.strftime("%Y-%m-%d_%H-%M-%S")
        self.pdf_context = pdf_context
        self.pdf_metadata = pdf_metadata or {}
        self.conversation = []

        print(f"Started session: {self.session_id}")
        return self.session_id

    def add_message(
        self,
        speaker: str,
        text: str,
        audio_duration: Optional[float] = None,
        audio_file: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Add a message to the conversation.

        Args:
            speaker: 'student' or 'bot'
            text: Message text
            audio_duration: Duration of audio in seconds
            audio_file: Path to audio file (for bot responses)
            metadata: Additional metadata

        Returns:
            The message dictionary
        """
        message = {
            # Store timezone-aware ISO timestamp (+00:00)
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "speaker": speaker,
            "text": text
        }

        if audio_duration is not None:
            message["audio_duration"] = round(audio_duration, 2)

        if audio_file:
            message["audio_file"] = audio_file

        if metadata:
            message["metadata"] = metadata

        self.conversation.append(message)

        # Auto-save after each message
        self.save_session()

        return message

    def get_conversation_history(self, last_n: Optional[int] = None) -> List[Dict]:
        """
        Get conversation history.

        Args:
            last_n: If specified, return only last N messages

        Returns:
            List of message dictionaries
        """
        if last_n:
            return self.conversation[-last_n:]
        return self.conversation

    def get_formatted_history(self, last_n: Optional[int] = None) -> str:
        """
        Get formatted conversation history for LLM context.

        Args:
            last_n: Number of recent messages to include

        Returns:
            Formatted string
        """
        messages = self.get_conversation_history(last_n)
        formatted = []

        for msg in messages:
            speaker = msg['speaker'].upper()
            text = msg['text']
            formatted.append(f"{speaker}: {text}")

        return "\n".join(formatted)

    def save_session(self, filepath: Optional[str] = None) -> str:
        """
        Save current session to JSON file.

        Args:
            filepath: Optional custom filepath (otherwise auto-generated)

        Returns:
            Path to saved file
        """
        if not self.session_id:
            raise ValueError("No active session to save")

        if not filepath:
            filepath = os.path.join(self.storage_dir, f"{self.session_id}.json")

        session_data = {
            "session_id": self.session_id,
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "session_duration_seconds": (
                (datetime.now(timezone.utc) - self.session_start).total_seconds()
                if self.session_start else None
            ),
            "pdf_context": self.pdf_context,
            "pdf_metadata": self.pdf_metadata,
            "conversation": self.conversation,
            "message_count": len(self.conversation),
            "student_messages": sum(1 for msg in self.conversation if msg['speaker'] == 'student'),
            "bot_messages": sum(1 for msg in self.conversation if msg['speaker'] == 'bot')
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        return filepath

    def load_session(self, session_id: str) -> bool:
        """
        Load an existing session.

        Args:
            session_id: Session ID to load

        Returns:
            True if successful, False otherwise
        """
        filepath = os.path.join(self.storage_dir, f"{session_id}.json")

        if not os.path.exists(filepath):
            print(f"Session file not found: {filepath}")
            return False

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.session_id = data['session_id']
            self.session_start = datetime.fromisoformat(data['session_start']) if data.get('session_start') else None
            self.pdf_context = data['pdf_context']
            self.pdf_metadata = data.get('pdf_metadata', {})
            self.conversation = data['conversation']

            print(f"Loaded session: {self.session_id} ({len(self.conversation)} messages)")
            return True

        except Exception as e:
            print(f"Error loading session: {e}")
            return False

    def list_sessions(self) -> List[Dict]:
        """
        List all saved sessions.

        Returns:
            List of session info dictionaries
        """
        sessions = []

        for filename in sorted(os.listdir(self.storage_dir), reverse=True):
            if filename.endswith('.json'):
                filepath = os.path.join(self.storage_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        sessions.append({
                            'session_id': data['session_id'],
                            'session_start': data.get('session_start'),
                            'message_count': data.get('message_count', 0),
                            'pdf_title': data.get('pdf_metadata', {}).get('title', 'Unknown')
                        })
                except Exception:
                    continue

        return sessions

    def export_as_text(self, output_path: Optional[str] = None) -> str:
        """
        Export conversation as readable text file.

        Args:
            output_path: Optional output path

        Returns:
            Path to exported file
        """
        if not self.session_id:
            raise ValueError("No active session to export")

        if not output_path:
            output_path = os.path.join(self.storage_dir, f"{self.session_id}.txt")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(f"Socratic Dialogue Session: {self.session_id}\n")
            f.write(f"Date: {self.session_start.strftime('%Y-%m-%d %H:%M:%S') if self.session_start else 'Unknown'}\n")
            f.write("=" * 70 + "\n\n")

            f.write("ESSAY CONTEXT (First 500 words):\n")
            f.write("-" * 70 + "\n")
            f.write(self.pdf_context)
            f.write("\n\n" + "=" * 70 + "\n\n")

            f.write("CONVERSATION:\n")
            f.write("-" * 70 + "\n\n")

            for msg in self.conversation:
                timestamp = datetime.fromisoformat(msg['timestamp']).strftime('%H:%M:%S')
                speaker = "STUDENT" if msg['speaker'] == 'student' else "BOT"
                f.write(f"[{timestamp}] {speaker}:\n")
                f.write(f"{msg['text']}\n\n")

            f.write("=" * 70 + "\n")
            f.write(f"Total messages: {len(self.conversation)}\n")

        return output_path


if __name__ == "__main__":
    # Test the conversation manager
    print("Testing Conversation Manager...\n")

    manager = ConversationManager(storage_dir="conversations")

    # Start a test session
    sample_context = """
    The impact of artificial intelligence on employment patterns represents one of the most
    significant economic challenges of the 21st century. This essay argues that while AI
    automation will displace certain job categories, it will simultaneously create new
    opportunities that require human creativity and emotional intelligence.
    """

    session_id = manager.start_session(
        pdf_context=sample_context.strip(),
        pdf_metadata={'title': 'AI and Employment Essay', 'author': 'Test Student'}
    )

    print(f"Session started: {session_id}\n")

    # Add some test messages
    manager.add_message('bot', "I've reviewed your essay. What is your main argument about AI's impact on employment?")
    manager.add_message('student', "I think AI will create more jobs than it destroys because it opens up new fields.", audio_duration=3.5)
    manager.add_message('bot', "What specific evidence supports your claim that new jobs will outnumber lost positions?")
    manager.add_message('student', "Well, historically technology has always created new industries.", audio_duration=2.8)

    print("Added 4 messages to conversation")

    # Get formatted history
    print("\nFormatted history:")
    print(manager.get_formatted_history())

    # Save session
    filepath = manager.save_session()
    print(f"\nSaved session to: {filepath}")

    # List sessions
    print("\nAll sessions:")
    for session in manager.list_sessions():
        print(f"  - {session['session_id']}: {session['message_count']} messages")

    # Export as text
    text_file = manager.export_as_text()
    print(f"\nExported to: {text_file}")

    print("\n✓ Conversation Manager test complete")
