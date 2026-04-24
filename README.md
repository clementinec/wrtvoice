# Socratic Method Bot

A local FastAPI app for working on essays with an LLM. The default interface is
typed essay editing; voice mode is still available for Socratic defense practice
when Whisper and local audio dependencies are installed.

## Features

- PDF upload with up to 5,000 words imported for the current pilot.
- Text editing mode with no microphone or Whisper dependency.
- Optional voice mode using local Whisper speech-to-text.
- Local Ollama/LLaMA response generation.
- Streaming bot responses in voice mode.
- Session persistence to JSON and text exports in `conversations/`.

## Requirements

Text mode:

```bash
pip install -r requirements_web.txt
```

For scanned PDFs or PDFs printed from a browser viewer, install OCR support:

```bash
brew install tesseract
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
2. Choose `Text editing` or `Voice`.
3. Start the session.
4. In text mode, ask for routine essay help such as thesis revision, structure,
   clarity edits, paragraph rewrites, or feedback.
5. In voice mode, answer the tutor's Socratic questions.
6. End the session to save JSON and text exports.

For the current pilot, essays under 5,000 words are imported directly. Longer
essays are accepted, but only the first 5,000 words are used as model context
and the upload page shows a truncation notice.

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
- OCR fallback requires `tesseract` on the system path.
- `requirements_all.txt` installs everything, including optional voice/TTS code.
- The current app keeps one active in-memory session at a time.
- Generated caches and temporary uploads are ignored by `.gitignore`; existing
  checked-in conversation fixtures are left untouched.
