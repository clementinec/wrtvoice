"""
Socratic Method Bot - Main Application
FastAPI server for real-time transcription and Socratic dialogue.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import uvicorn
import asyncio
import os
import shutil
from datetime import datetime, timezone

from modules.pdf_parser import PDFParser
from modules.ollama_client import OllamaClient
from modules.conversation_manager import ConversationManager


# Request models
class SessionStartRequest(BaseModel):
    mode: str = "voice"
    whisper_model: str = "base"
    phrase_timeout: float = 5.0  # Default 5 seconds


class MessageRequest(BaseModel):
    text: str


app = FastAPI(title="Socratic Method Bot")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global instances
conversation_manager = ConversationManager(storage_dir="conversations")
ollama_client = OllamaClient()

# Session state
current_session = {
    "pdf_uploaded": False,
    "pdf_context": "",
    "pdf_metadata": {},
    "session_active": False,
    "mode": "voice",
    "whisper_stt": None
}

SESSION_MODES = {"voice", "text"}


def normalize_session_mode(mode: str) -> str:
    """Normalize and validate the requested interaction mode."""
    normalized = (mode or "voice").strip().lower()
    if normalized not in SESSION_MODES:
        raise HTTPException(status_code=400, detail="Session mode must be 'voice' or 'text'")
    return normalized


def get_whisper_stt_class():
    """Import Whisper lazily so text-only sessions do not require audio dependencies."""
    try:
        from modules.whisper_stt import WhisperSTT
        return WhisperSTT
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice mode is unavailable because Whisper/audio dependencies are not installed. "
                "Install requirements.txt or requirements_all.txt to enable voice sessions."
            )
        ) from exc


def stop_active_voice_session() -> None:
    """Stop any active Whisper listener before replacing or ending a session."""
    whisper_stt = current_session.get("whisper_stt")
    if whisper_stt:
        whisper_stt.stop_listening()
        current_session["whisper_stt"] = None


async def generate_bot_response(student_text: str, on_chunk=None) -> str:
    """Generate the bot response with the shared Socratic prompt path."""
    conversation_history = conversation_manager.get_conversation_history(last_n=10)
    full_response = ""

    async for chunk in ollama_client.generate_socratic_response_stream(
        student_input=student_text,
        pdf_context=current_session["pdf_context"],
        conversation_history=conversation_history
    ):
        if chunk:
            full_response += chunk
            if on_chunk:
                await on_chunk(chunk)

    return full_response.strip()


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the landing page."""
    return FileResponse("static/index.html")


@app.get("/conversation", response_class=HTMLResponse)
async def conversation_page():
    """Serve the conversation page."""
    return FileResponse("static/conversation.html")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    ollama_status = ollama_client.check_connection()

    return {
        "status": "healthy",
        "ollama_connected": ollama_status,
        "pdf_uploaded": current_session["pdf_uploaded"],
        "session_active": current_session["session_active"],
        "mode": current_session["mode"]
    }


@app.post("/upload-pdf")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Handle PDF upload and extract first 500 words.
    """
    # Validate file type
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Save uploaded file temporarily
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)

    # Use UTC for filenames to keep ordering consistent across timezones
    temp_path = os.path.join(upload_dir, f"temp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf")

    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Extract text from PDF
        parser = PDFParser()
        pdf_context = parser.extract_first_n_words(temp_path, n_words=500)
        pdf_metadata = parser.get_metadata(temp_path)

        # Store in session
        current_session["pdf_uploaded"] = True
        current_session["pdf_context"] = pdf_context
        current_session["pdf_metadata"] = pdf_metadata
        current_session["pdf_metadata"]["filename"] = file.filename

        return {
            "success": True,
            "message": f"PDF processed: {len(pdf_context.split())} words extracted",
            "metadata": pdf_metadata
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/start-session")
async def start_session(request: SessionStartRequest):
    """
    Initialize conversation session with Ollama and optional Whisper voice input.
    """
    mode = normalize_session_mode(request.mode)
    whisper_model = request.whisper_model
    phrase_timeout = request.phrase_timeout

    print(f"[SESSION] Starting {mode} session (model={whisper_model}, phrase_timeout={phrase_timeout}s)")

    if not current_session["pdf_uploaded"]:
        raise HTTPException(status_code=400, detail="No PDF uploaded")

    try:
        # Check Ollama connection
        if not ollama_client.check_connection():
            raise HTTPException(status_code=503, detail="Ollama server not available")

        WhisperSTT = get_whisper_stt_class() if mode == "voice" else None
        stop_active_voice_session()

        # Start conversation session
        session_id = conversation_manager.start_session(
            pdf_context=current_session["pdf_context"],
            pdf_metadata=current_session["pdf_metadata"]
        )

        # Get initial bot greeting from Ollama
        initial_response = ollama_client.initialize_context(current_session["pdf_context"])
        bot_message = initial_response.get("response", "Hello! Let's discuss your essay.")

        # Add to conversation
        conversation_manager.add_message('bot', bot_message)

        if mode == "voice":
            # Initialize Whisper STT with user-specified timeout from slider
            print(f"[WHISPER] Initializing with phrase_timeout={phrase_timeout}s")
            current_session["whisper_stt"] = WhisperSTT(
                model=whisper_model,
                phrase_timeout=phrase_timeout,  # From slider on upload page
                record_timeout=2.0,
                debug=False
            )
            print(f"[WHISPER] Initialized. Timeout value in STT: {current_session['whisper_stt'].phrase_timeout}s")
        else:
            current_session["whisper_stt"] = None

        current_session["session_active"] = True
        current_session["mode"] = mode

        return {
            "success": True,
            "session_id": session_id,
            "mode": mode,
            "initial_message": bot_message
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting session: {str(e)}")


@app.get("/session-state")
async def session_state():
    """Return the current in-memory session state for the browser UI."""
    return {
        "pdf_uploaded": current_session["pdf_uploaded"],
        "session_active": current_session["session_active"],
        "mode": current_session["mode"],
        "metadata": current_session["pdf_metadata"],
        "conversation": conversation_manager.get_conversation_history()
        if current_session["session_active"]
        else []
    }


@app.post("/message")
async def send_text_message(request: MessageRequest):
    """
    Submit a typed student message and return the Socratic response.
    """
    if not current_session["session_active"]:
        raise HTTPException(status_code=400, detail="No active session")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")

    if not ollama_client.check_connection():
        raise HTTPException(status_code=503, detail="Ollama server not available")

    try:
        student_message = conversation_manager.add_message('student', text)
        bot_text = await generate_bot_response(text)
        bot_message = conversation_manager.add_message('bot', bot_text)

        return {
            "success": True,
            "student_message": student_message,
            "bot_message": bot_message
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating response: {str(e)}")


@app.websocket("/ws/conversation")
async def websocket_conversation(websocket: WebSocket):
    """
    WebSocket endpoint for real-time conversation.
    Handles bidirectional communication: transcription → bot response.
    """
    await websocket.accept()

    if not current_session["session_active"]:
        await websocket.send_json({"type": "error", "message": "No active session"})
        await websocket.close()
        return

    if current_session["mode"] != "voice":
        await websocket.send_json({"type": "error", "message": "Current session is not in voice mode"})
        await websocket.close()
        return

    whisper_stt = current_session["whisper_stt"]

    if not whisper_stt:
        await websocket.send_json({"type": "error", "message": "Whisper not initialized"})
        await websocket.close()
        return

    # Start listening
    whisper_stt.start_listening()

    try:
        # Send ready signal
        await websocket.send_json({"type": "ready", "message": "Listening started"})

        # Send conversation history (including initial bot greeting)
        for msg in conversation_manager.get_conversation_history():
            await websocket.send_json({
                "type": "bot_response" if msg['speaker'] == 'bot' else "transcription",
                "text": msg['text'],
                "timestamp": msg['timestamp'],
                "phrase_complete": True
            })

        # Track current transcription state to avoid duplicates
        current_student_text = ""
        last_pausing_time = None

        # Main loop: process audio and handle transcription
        while True:
            # Process audio queue - returns single dict or None
            result = whisper_stt.process_audio_queue()

            if result:
                # Handle pausing state (countdown)
                if result.get('pausing'):
                    time_remaining = result.get('time_remaining', 0)

                    # Only send pausing updates every 0.5s to reduce spam
                    if last_pausing_time is None or (datetime.now(timezone.utc) - last_pausing_time).total_seconds() >= 0.5:
                        await websocket.send_json({
                            "type": "status",
                            "status": "pausing",
                            "time_remaining": time_remaining
                        })
                        last_pausing_time = datetime.now(timezone.utc)

                # Handle phrase complete
                elif result.get('phrase_complete'):
                    text = result['text']

                    # Skip empty phrases
                    if not text.strip():
                        await websocket.send_json({"type": "status", "status": "listening"})
                        current_student_text = ""
                        last_pausing_time = None
                        continue

                    # Send final transcription ONLY (no duplicate live transcription)
                    await websocket.send_json({
                        "type": "transcription",
                        "text": text,
                        "phrase_complete": True,
                        "timestamp": result['timestamp'].isoformat()
                    })

                    # Add student message to conversation
                    conversation_manager.add_message('student', text)

                    # Send "analyzing" status
                    await websocket.send_json({"type": "status", "status": "analyzing"})

                    # Send "responding" status before streaming
                    await websocket.send_json({"type": "status", "status": "responding"})

                    async def send_chunk(chunk):
                        await websocket.send_json({
                            "type": "bot_response_chunk",
                            "chunk": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })

                    full_response = await generate_bot_response(text, on_chunk=send_chunk)

                    # Send completion signal
                    await websocket.send_json({
                        "type": "bot_response_complete",
                        "text": full_response,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })

                    # Add bot response to conversation
                    conversation_manager.add_message('bot', full_response)

                    # Return to listening status
                    await websocket.send_json({"type": "status", "status": "listening"})
                    current_student_text = ""
                    last_pausing_time = None

                # Handle live transcription update (user is speaking)
                else:
                    text = result['text']

                    # Only send if text actually changed (avoid duplicates)
                    if text and text != current_student_text:
                        current_student_text = text
                        last_pausing_time = None  # Reset pausing timer
                        await websocket.send_json({
                            "type": "transcription",
                            "text": text,
                            "phrase_complete": False,
                            "timestamp": result['timestamp'].isoformat()
                        })
                        # Also update status to listening when user resumes speaking
                        await websocket.send_json({"type": "status", "status": "listening"})

            # Small delay to prevent busy-waiting
            await asyncio.sleep(0.25)

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")
        await websocket.send_json({"type": "error", "message": str(e)})
    finally:
        # Clean up
        if whisper_stt:
            whisper_stt.stop_listening()


@app.post("/end-session")
async def end_session():
    """
    End the current session and save conversation.
    """
    if not current_session["session_active"]:
        raise HTTPException(status_code=400, detail="No active session")

    try:
        # Save final conversation
        filepath = conversation_manager.save_session()

        # Export as text
        text_filepath = conversation_manager.export_as_text()

        # Clean up
        stop_active_voice_session()

        current_session["session_active"] = False

        return {
            "success": True,
            "message": "Session ended",
            "json_file": filepath,
            "text_file": text_filepath,
            "message_count": len(conversation_manager.conversation)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error ending session: {str(e)}")


@app.get("/sessions")
async def list_sessions():
    """List all saved conversation sessions."""
    sessions = conversation_manager.list_sessions()
    return {"sessions": sessions}


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get details of a specific session."""
    if conversation_manager.load_session(session_id):
        return {
            "session_id": conversation_manager.session_id,
            "pdf_context": conversation_manager.pdf_context,
            "conversation": conversation_manager.conversation,
            "metadata": conversation_manager.pdf_metadata
        }
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/microphones")
async def list_microphones():
    """List available microphone devices."""
    try:
        WhisperSTT = get_whisper_stt_class()
        mics = WhisperSTT.list_microphones()
        return {"microphones": [{"index": idx, "name": name} for idx, name in mics]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    print("=" * 70)
    print("Socratic Method Bot - Starting Server")
    print("=" * 70)

    # Check Ollama connection
    print("\nChecking Ollama connection...")
    if ollama_client.check_connection():
        print("✓ Ollama is running (llama3.1:latest)")
    else:
        print("✗ WARNING: Ollama is not running!")
        print("  Start it with: ollama serve")

    print("\nServer will start at: http://localhost:8000")
    print("Press Ctrl+C to stop\n")

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
