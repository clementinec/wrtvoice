# Socratic Method Bot

A web-based application that uses real-time speech transcription (Whisper) and AI dialogue (Ollama + LLaMA 3.1) to help students defend their essays through Socratic questioning.

## 🎯 Features

- **PDF Upload**: Upload essay PDFs and extract the first 500 words for context
- **Real-time Transcription**: Uses OpenAI's Whisper for live speech-to-text
- **Socratic Dialogue**: LLaMA 3.1 acts as a tutor challenging arguments
- **Text-to-Speech**: Bot responses are spoken aloud using pyttsx3
- **Conversation Splitting**: Automatic phrase detection from `transcribe_demo.py`
- **Session Storage**: All dialogues saved as timestamped JSON files
- **Web Interface**: Clean, modern UI for seamless interaction

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Browser   │ ←──→│   FastAPI    │ ←──→│   Ollama    │
│  (WebUI)    │     │   (app.py)   │     │ (llama3.1)  │
└─────────────┘     └──────────────┘     └─────────────┘
                           ↕
                    ┌──────────────┐
                    │   Whisper    │
                    │  (Local STT) │
                    └──────────────┘
```

## 📋 Prerequisites

1. **Python 3.8+**
2. **Ollama** with `llama3.1:latest` model (already installed ✓)
3. **FFmpeg** (for audio processing)
4. **PyAudio** dependencies

### macOS Setup

```bash
# Install FFmpeg
brew install ffmpeg

# Install PyAudio dependencies
brew install portaudio
```

## 🚀 Installation

### 1. Install Existing Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Web Application Dependencies

```bash
pip install -r requirements_web.txt
```

### 3. Verify Ollama is Running

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# If not running, start it
ollama serve
```

## 📖 Usage

### Start the Server

```bash
python app.py
```

The server will start at `http://localhost:8000`

### Workflow

1. **Upload PDF**
   - Navigate to `http://localhost:8000`
   - Upload your essay (PDF format)
   - Wait for processing (extracts first 500 words)

2. **Start Session**
   - Click "Start Session"
   - Whisper model loads (one-time initialization)
   - Bot greets you and asks about your thesis

3. **Engage in Dialogue**
   - Speak naturally into your microphone
   - After 3 seconds of silence, your phrase is complete
   - Bot generates a Socratic response and speaks it aloud
   - Conversation continues iteratively

4. **End Session**
   - Click "End Session" when done
   - Conversation saved to `conversations/<timestamp>.json`
   - Text export also saved as `.txt` file

## 📁 Project Structure

```
whisper_real_time/
├── app.py                      # Main FastAPI application
├── transcribe_demo.py          # Original Whisper demo
├── modules/
│   ├── __init__.py
│   ├── pdf_parser.py           # PDF text extraction
│   ├── ollama_client.py        # Ollama/LLaMA integration
│   ├── whisper_stt.py          # Real-time speech-to-text
│   ├── tts_engine.py           # Text-to-speech
│   └── conversation_manager.py # Session management & storage
├── static/
│   ├── index.html              # Landing page
│   └── conversation.html       # Chat interface
├── conversations/              # Saved dialogues (JSON)
├── uploads/                    # Temporary PDF storage
├── requirements.txt            # Original dependencies
└── requirements_web.txt        # Web app dependencies
```

## 🔧 Configuration

### Whisper Model Selection

Edit in `app.py` or modify the `/start-session` endpoint:

```python
# Options: tiny, base, small, medium, large
whisper_model = "base"  # Default (fast, good quality)
```

### Phrase Timeout (Silence Detection)

In `modules/whisper_stt.py`:

```python
phrase_timeout = 3.0  # Seconds of silence before phrase completes
```

### Socratic Prompt Customization

Edit in `modules/ollama_client.py`:

```python
SOCRATIC_SYSTEM_PROMPT = """
Your custom instructions here...
"""
```

## 📊 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Landing page |
| `/conversation` | GET | Conversation UI |
| `/health` | GET | Check system status |
| `/upload-pdf` | POST | Upload PDF file |
| `/start-session` | POST | Initialize session |
| `/ws/conversation` | WebSocket | Real-time dialogue |
| `/end-session` | POST | Save and close session |
| `/sessions` | GET | List all sessions |
| `/sessions/{id}` | GET | Get session details |
| `/microphones` | GET | List audio devices |

## 🧪 Testing Individual Modules

### Test PDF Parser

```bash
python modules/pdf_parser.py path/to/essay.pdf
```

### Test Ollama Client

```bash
python modules/ollama_client.py
```

### Test Whisper STT

```bash
python modules/whisper_stt.py
```

### Test TTS Engine

```bash
python modules/tts_engine.py
```

### Test Conversation Manager

```bash
python modules/conversation_manager.py
```

## 📝 Conversation JSON Format

```json
{
  "session_id": "2025-11-04_14-30-00",
  "session_start": "2025-11-04T14:30:00",
  "pdf_context": "First 500 words of essay...",
  "pdf_metadata": {
    "title": "Essay Title",
    "author": "Student Name",
    "pages": 5
  },
  "conversation": [
    {
      "timestamp": "2025-11-04T14:30:15",
      "speaker": "bot",
      "text": "What is your main argument?"
    },
    {
      "timestamp": "2025-11-04T14:30:20",
      "speaker": "student",
      "text": "I argue that...",
      "audio_duration": 3.5
    }
  ],
  "message_count": 12,
  "student_messages": 6,
  "bot_messages": 6
}
```

## 🐛 Troubleshooting

### "Ollama not available" Error

```bash
# Start Ollama server
ollama serve

# Verify llama3.1 is installed
ollama list
```

### PyAudio Installation Issues (macOS)

```bash
brew install portaudio
pip install pyaudio
```

### Whisper Model Download Slow

Models are cached after first download:
- `tiny`: ~75 MB
- `base`: ~150 MB (recommended)
- `small`: ~500 MB
- `medium`: ~1.5 GB

### Microphone Not Detected

```bash
# List available microphones
python modules/whisper_stt.py
```

## 🔒 Security Notes

- PDFs are temporarily stored in `uploads/` and deleted after processing
- No API keys required (all local processing)
- Conversations stored locally in `conversations/`

## 🎓 Educational Use

This bot is designed to:
- Challenge students' arguments constructively
- Identify logical gaps and unsupported claims
- Practice verbal defense of written work
- Improve critical thinking skills

## 📄 License

Inherits license from the original Whisper Real-Time repository.

## 🙏 Acknowledgments

- Built on top of the existing `transcribe_demo.py` implementation
- Uses OpenAI's Whisper for speech recognition
- Powered by Ollama and LLaMA 3.1 for dialogue generation
- Text-to-speech via pyttsx3

---

**Happy Socratic Questioning! 🤔**
