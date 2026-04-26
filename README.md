# Socratic Oracle

A local FastAPI app for developing verbal understanding of a writeup through
guided Socratic questions. A typed text workspace is also available for routine
revision tasks.

## Features

- PDF upload with up to 5,000 words imported for the current pilot.
- Text editing mode with no microphone or Whisper dependency.
- Optional Socratic Oracle voice mode using local Whisper speech-to-text.
- Local Ollama/LLaMA response generation.
- Streaming bot responses in voice mode.
- Session persistence to JSON and text exports in `conversations/`.

## Requirements

Text mode:

```bash
pip install -r requirements_web.txt
```

Or use the installer, which now defaults to text mode and skips PyAudio:

```bash
./install_dependencies.sh
```

For scanned PDFs or PDFs printed from a browser viewer, install OCR support:

```bash
brew install tesseract
```

Socratic Oracle voice mode also requires the audio/Whisper stack:

```bash
./install_dependencies.sh --voice
```

For macOS voice mode, PyAudio needs the Homebrew PortAudio headers:

```bash
env -u HOMEBREW_BOTTLE_DOMAIN -u HOMEBREW_API_DOMAIN HOMEBREW_NO_AUTO_UPDATE=1 brew install portaudio
```

The app expects Ollama to be running locally. The preferred default model is
`qwen3:14b`, and you can switch to any installed model on the upload page:

```bash
ollama serve
ollama pull qwen3:14b
ollama pull llama3.1
ollama pull gemma4:e4b
```

To use a different installed model or Ollama host, set:

```bash
export OLLAMA_MODEL=qwen3:14b
export OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Socratic Oracle voice mode defaults to Whisper `small.en` for better transcription. The first
startup preloads it and may download the model once. To choose a faster model or
skip preload:

```bash
export WHISPER_MODEL=base
export PRELOAD_WHISPER_MODEL=0
```

For Socratic Oracle sessions, the model prompt uses a compact paper anchor
(detected Abstract when available, otherwise a synthesized abstract-like anchor
when Ollama is available, otherwise the opening words) plus recent conversation
memory. Text editing mode still uses the fuller imported essay excerpt for
revision tasks.

## Run

```bash
./start_bot.sh
```

Then open:

```text
http://localhost:8000
```

## Usage

1. Upload a PDF writeup.
2. Choose `Text workspace` or `Socratic Oracle`.
3. Start the session.
4. In text mode, ask for routine essay help such as thesis revision, structure,
   clarity edits, paragraph rewrites, or feedback.
5. In Socratic Oracle mode, answer question-led prompts to develop verbal understanding of your writeup.
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
- `POST /message/stream` - submit a typed message and stream NDJSON response chunks.
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
- `requirements_all.txt` installs everything, including optional voice code.
- The current app keeps one active in-memory session at a time.
- Generated caches and temporary uploads are ignored by `.gitignore`; existing
  checked-in conversation fixtures are left untouched.
