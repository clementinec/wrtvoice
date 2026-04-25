# Quick Start Guide - Socratic Method Bot

## Prerequisites Check

✅ **Ollama installed**: `/usr/local/bin/ollama`
✅ **Ollama model available**: `gemma4:e4b` preferred, `qwen3:14b` recommended for stronger tutoring
✅ **Whisper/PyAudio**: Optional; only needed for voice mode

## Installation (One-time)

```bash
# 1. Install text-mode dependencies
./install_dependencies.sh

# Optional: install voice dependencies later
./install_dependencies.sh --voice

# Optional manual macOS voice-mode system package
env -u HOMEBREW_BOTTLE_DOMAIN -u HOMEBREW_API_DOMAIN HOMEBREW_NO_AUTO_UPDATE=1 brew install portaudio
```

## Running the Application

### Option 1: Use the Start Script (Recommended)

```bash
./start_bot.sh
```

### Option 2: Manual Start

```bash
# Terminal 1: Start Ollama (if not running)
ollama serve

# Terminal 2: Start the web app
python app.py
```

To use a different installed Ollama model:

```bash
OLLAMA_MODEL=<model-name> ./start_bot.sh
```

You can also choose an installed Ollama model from the upload page before
starting a session.

## Usage Flow

1. **Open Browser**: Navigate to `http://localhost:8000`

2. **Upload PDF**:
   - Click the upload area or drag & drop your essay PDF
   - Up to the first 5,000 words are automatically extracted

3. **Start Session**:
   - Choose Text editing for typed revision help, or Voice for microphone practice
   - Click "Start Session" button
   - Text mode starts immediately once Ollama is ready
   - Voice mode loads Whisper first (one-time, ~30 seconds)

4. **Engage in Dialogue**:
   - In text mode, type an editing request or use a prompt button
   - In voice mode, speak into the server machine microphone
   - After the configured pause timeout, the bot responds in the chat

5. **End Session**:
   - Click "End Session" when done
   - Conversation saved to `conversations/<timestamp>.json`
   - Text export created as `.txt` file

## Test the Components

```bash
# Test PDF parser
python modules/pdf_parser.py path/to/essay.pdf

# Test Ollama connection
python modules/ollama_client.py

# Test Whisper STT
python modules/whisper_stt.py

# Test TTS
python modules/tts_engine.py

# Test conversation manager
python modules/conversation_manager.py
```

## Troubleshooting

### Ollama not responding
```bash
ollama serve
```

### Whisper model not found
First run downloads models automatically (base ≈ 150MB)

### Microphone not working
```bash
# List available microphones
python modules/whisper_stt.py
```

### PyAudio errors (macOS)
```bash
brew install portaudio
pip install --upgrade pyaudio
```

## Configuration

### Change Whisper Model (Speed vs Quality)

In `app.py`, modify line 140:
```python
model="tiny"    # Fastest, lower quality
model="base"    # Recommended (default)
model="small"   # Better quality, slower
model="medium"  # High quality, much slower
```

### Adjust Phrase Detection Timeout

**Default: 5.0 seconds**
**Range: 4.0 - 10.0 seconds** (configurable via slider on upload page)

In `app.py`, modify line 27 to change default:
```python
phrase_timeout: float = 5.0  # Default 5 seconds
phrase_timeout: float = 4.0  # Faster responses
phrase_timeout: float = 10.0  # Very patient
```

### Customize Socratic Prompts

Edit `modules/ollama_client.py` line 16-27:
```python
SOCRATIC_SYSTEM_PROMPT = """
Your custom instructions here...
"""
```

## File Locations

- **Conversations**: `conversations/<timestamp>.json`
- **Text Exports**: `conversations/<timestamp>.txt`
- **Temporary PDFs**: `uploads/` (auto-deleted after processing)

## Key Features

✅ **100% Local Processing**
- Whisper runs locally (no OpenAI API)
- Ollama runs locally (no external LLM calls)

✅ **Reuses Existing Code**
- Phrase splitting from `transcribe_demo.py:102-104`
- Audio queue management from `transcribe_demo.py:78-136`
- Whisper integration fully compatible

✅ **Socratic Method**
- LLaMA 3.1 trained to challenge arguments
- Requests evidence for claims
- Highlights logical gaps
- Guides without giving answers

## API Endpoints (For Advanced Use)

- `GET /health` - Check system status
- `POST /upload-pdf` - Upload essay
- `POST /start-session` - Initialize conversation
- `WebSocket /ws/conversation` - Real-time dialogue
- `POST /end-session` - Save and close
- `GET /sessions` - List all sessions
- `GET /sessions/{id}` - Get session details

---

**Ready to start? Run:** `./start_bot.sh`
