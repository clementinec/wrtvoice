# Socratic Method Bot

A local FastAPI app for practicing essay defense through Socratic questioning.
The default interface is typed chat; voice mode is still available when Whisper
and local audio dependencies are installed.

## Features

- PDF upload with first-500-word context extraction.
- Text chat mode with no microphone or Whisper dependency.
- Optional voice mode using local Whisper speech-to-text.
- Local Ollama/LLaMA response generation.
- Streaming bot responses in voice mode.
- Session persistence to JSON and text exports in `conversations/`.

## Requirements

Text mode:

```bash
pip install -r requirements_web.txt
```

Voice mode also requires the audio/Whisper stack:

```bash
pip install -r requirements.txt
```

For macOS voice mode, install system audio tools first:

```bash
brew install portaudio ffmpeg
```

The app expects Ollama to be running locally with `llama3.1:latest`:

```bash
ollama serve
ollama pull llama3.1
```

## Run

```bash
./start_bot.sh
```

Then open:

```text
http://localhost:8000
```

## Usage

1. Upload a PDF essay.
2. Choose `Text chat` or `Voice`.
3. Start the session.
4. Answer the tutor's questions.
5. End the session to save JSON and text exports.

Voice mode uses the microphone attached to the machine running the FastAPI
server, not the browser client's microphone. For remote/browser-client voice,
the audio capture path would need to move into the browser and stream audio to
the backend.

## API

- `GET /health` - server/Ollama/session status.
- `POST /upload-pdf` - upload the essay PDF.
- `POST /start-session` - start a text or voice session.
- `GET /session-state` - current in-memory session state for the UI.
- `POST /message` - submit a typed student message.
- `WebSocket /ws/conversation` - voice-mode transcription/response stream.
- `POST /end-session` - save and close the current session.
- `GET /sessions` - list saved sessions.
- `GET /sessions/{session_id}` - load one saved session.
- `GET /microphones` - list server-side microphones when voice deps exist.

## Project Structure

```text
app.py                      FastAPI app and session routes
modules/pdf_parser.py       PDF text extraction
modules/ollama_client.py    Ollama prompt and streaming client
modules/whisper_stt.py      Optional local Whisper STT
modules/conversation_manager.py
static/index.html           PDF upload and mode selection
static/conversation.html    Text/voice conversation UI
conversations/              Saved session exports
```

## Maintenance Notes

- `requirements_web.txt` is enough for text mode.
- `requirements_all.txt` installs everything, including optional voice/TTS code.
- The current app keeps one active in-memory session at a time.
- Generated caches and temporary uploads are ignored by `.gitignore`; existing
  checked-in conversation fixtures are left untouched.
