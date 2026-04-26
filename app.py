"""
Socratic Method Bot - Main Application
FastAPI server for real-time transcription and Socratic dialogue.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
import asyncio
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from typing import Optional

from modules.pdf_parser import PDFParser
from modules.ollama_client import OllamaClient
from modules.conversation_manager import ConversationManager


PDF_CONTEXT_WORD_LIMIT = 5000
PAPER_ANCHOR_WORD_LIMIT = 320
MIN_ABSTRACT_WORDS = 20
SOCRATIC_MEMORY_WORD_LIMIT = 160
DEFAULT_WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
SUPPORTED_WHISPER_MODELS = {"tiny", "base", "small", "medium", "large"}


# Request models
class SessionStartRequest(BaseModel):
    mode: str = "voice"
    ollama_model: Optional[str] = None
    whisper_model: str = DEFAULT_WHISPER_MODEL
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
    "paper_anchor": "",
    "paper_anchor_source": "",
    "socratic_memory": "",
    "pdf_metadata": {},
    "pdf_context_stats": {},
    "session_active": False,
    "mode": "voice",
    "ollama_model": ollama_client.model,
    "whisper_stt": None
}

SESSION_MODES = {"voice", "text"}
RECOMMENDED_OLLAMA_MODELS = [
    "qwen3:14b",
    "llama3.1:latest",
    "gemma4:e4b",
    "gemma3:12b",
]
FILLER_WORDS = {"um", "umm", "uh", "uhh", "er", "erm", "em", "emm", "hm", "hmm", "mm", "mmm", "mhm"}


def normalize_session_mode(mode: str) -> str:
    """Normalize and validate the requested interaction mode."""
    normalized = (mode or "voice").strip().lower()
    if normalized not in SESSION_MODES:
        raise HTTPException(status_code=400, detail="Session mode must be 'voice' or 'text'")
    return normalized


def normalize_ollama_model(model: Optional[str]) -> str:
    """Normalize the requested Ollama model name."""
    normalized = (model or ollama_client.model or OllamaClient.DEFAULT_MODEL).strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Ollama model is required")
    return normalized


def normalize_whisper_model(model: Optional[str]) -> str:
    """Normalize and validate the requested local Whisper model size."""
    normalized = (model or DEFAULT_WHISPER_MODEL).strip().lower()
    if normalized not in SUPPORTED_WHISPER_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Whisper model must be one of: {', '.join(sorted(SUPPORTED_WHISPER_MODELS))}"
        )
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


def reset_runtime_session() -> None:
    """Clear active runtime state so one session cannot leak into the next."""
    stop_active_voice_session()
    current_session.update({
        "pdf_uploaded": False,
        "pdf_context": "",
        "paper_anchor": "",
        "paper_anchor_source": "",
        "socratic_memory": "",
        "pdf_metadata": {},
        "pdf_context_stats": {},
        "session_active": False,
        "mode": "voice",
        "ollama_model": ollama_client.model,
        "whisper_stt": None
    })
    conversation_manager.reset()


def public_context_stats(context_stats: dict) -> dict:
    """Return context metadata without echoing essay text to the browser."""
    return {key: value for key, value in context_stats.items() if key != "text"}


def trim_words(text: str, max_words: int) -> str:
    """Trim text to a word budget without splitting on punctuation."""
    words = (text or "").split()
    return " ".join(words[:max_words])


def extract_paper_anchor(pdf_context: str) -> dict:
    """
    Extract a stable short paper anchor for voice mode.

    Prefer an Abstract section when it is detectable; otherwise use the opening
    words. This keeps every Socratic turn grounded without resending the whole
    essay excerpt.
    """
    normalized = re.sub(r"\s+", " ", pdf_context or "").strip()
    if not normalized:
        return {"text": "", "source": "none", "words": 0}

    abstract_match = re.search(
        r"\babstract\b\s*[:.\-]?\s*(?P<body>.*?)(?=\b(?:keywords?|key words|introduction|1\.?\s+introduction|i\.?\s+introduction|background)\b)",
        normalized,
        flags=re.IGNORECASE,
    )
    if abstract_match:
        abstract_text = trim_words(abstract_match.group("body").strip(), PAPER_ANCHOR_WORD_LIMIT)
        if len(abstract_text.split()) >= MIN_ABSTRACT_WORDS:
            return {
                "text": abstract_text,
                "source": "abstract",
                "words": len(abstract_text.split())
            }

    abstract_start = re.search(r"\babstract\b\s*[:.\-]?\s*(?P<body>.*)", normalized, flags=re.IGNORECASE)
    if abstract_start:
        abstract_text = trim_words(abstract_start.group("body").strip(), PAPER_ANCHOR_WORD_LIMIT)
        if len(abstract_text.split()) >= MIN_ABSTRACT_WORDS:
            return {
                "text": abstract_text,
                "source": "abstract",
                "words": len(abstract_text.split())
            }

    opening_text = trim_words(normalized, PAPER_ANCHOR_WORD_LIMIT)
    return {
        "text": opening_text,
        "source": "opening",
        "words": len(opening_text.split())
    }


def synthesize_paper_anchor(pdf_context: str, model: Optional[str] = None) -> dict:
    """
    Generate a compact abstract-like anchor when the PDF has no detected Abstract.

    This is best-effort. If Ollama is unavailable or generation fails, callers
    should fall back to the opening words rather than fail the upload.
    """
    model_name = normalize_ollama_model(model)
    if not ollama_client.check_connection():
        return {
            "text": "",
            "source": "synthesis_failed",
            "words": 0,
            "error": f"Ollama is not available at {ollama_client.base_url}"
        }

    if not ollama_client.model_available(model=model_name):
        return {
            "text": "",
            "source": "synthesis_failed",
            "words": 0,
            "error": f"Ollama model '{model_name}' is not installed"
        }

    previous_model = ollama_client.model
    excerpt = trim_words(pdf_context, PDF_CONTEXT_WORD_LIMIT)
    messages = [
        {
            "role": "system",
            "content": (
                "Create a compact paper anchor for a Socratic tutor. "
                "Use only the provided paper text. Do not invent sources, claims, authors, data, or conclusions. "
                "Write 120-220 words in plain prose, no heading, no bullets, no markdown. "
                "Capture the central claim, scope, evidence base, and stakes if present."
            )
        },
        {
            "role": "user",
            "content": f"Paper text excerpt:\n\n{excerpt}"
        }
    ]

    try:
        ollama_client.set_model(model_name)
        result = ollama_client.chat(
            messages,
            options={
                "temperature": 0.2,
                "top_p": 0.85,
                "num_predict": 280,
                "repeat_penalty": 1.08,
            }
        )
    finally:
        ollama_client.set_model(previous_model)

    if result.get("error"):
        return {
            "text": "",
            "source": "synthesis_failed",
            "words": 0,
            "error": result.get("response", "Ollama synthesis failed")
        }

    synthesized = re.sub(
        r"^\s*(?:abstract|summary|paper anchor)\s*[:.\-]\s*",
        "",
        result.get("response", "").strip(),
        flags=re.IGNORECASE,
    )
    synthesized = trim_words(synthesized, PAPER_ANCHOR_WORD_LIMIT)
    if len(synthesized.split()) < MIN_ABSTRACT_WORDS:
        return {
            "text": "",
            "source": "synthesis_failed",
            "words": len(synthesized.split()),
            "error": "Synthesized anchor was too short"
        }

    return {
        "text": synthesized,
        "source": "synthetic_abstract",
        "words": len(synthesized.split())
    }


def choose_paper_anchor(pdf_context: str, model: Optional[str] = None) -> dict:
    """Detect an abstract, synthesize one if needed, then fall back to opening words."""
    detected_anchor = extract_paper_anchor(pdf_context)
    if detected_anchor["source"] == "abstract":
        detected_anchor["synthesis_attempted"] = False
        return detected_anchor

    synthesized_anchor = synthesize_paper_anchor(pdf_context, model=model)
    if synthesized_anchor.get("text"):
        synthesized_anchor["synthesis_attempted"] = True
        synthesized_anchor["fallback_anchor_source"] = detected_anchor["source"]
        return synthesized_anchor

    detected_anchor["synthesis_attempted"] = True
    detected_anchor["synthesis_error"] = synthesized_anchor.get("error", "Synthesis unavailable")
    return detected_anchor


def store_processed_pdf(
    filename: str,
    temp_path: str,
    context_stats: dict,
    context_summary: dict,
    paper_anchor: dict
) -> dict:
    """Persist processed PDF state and build the upload response."""
    pdf_metadata = PDFParser().get_metadata(temp_path)

    context_summary["paper_anchor_source"] = paper_anchor["source"]
    context_summary["paper_anchor_words"] = paper_anchor["words"]
    context_summary["paper_anchor_synthesis_attempted"] = paper_anchor.get("synthesis_attempted", False)
    if paper_anchor.get("synthesis_error"):
        context_summary["paper_anchor_synthesis_error"] = paper_anchor["synthesis_error"]

    current_session["pdf_uploaded"] = True
    current_session["pdf_context"] = context_stats["text"]
    current_session["paper_anchor"] = paper_anchor["text"]
    current_session["paper_anchor_source"] = paper_anchor["source"]
    current_session["socratic_memory"] = ""
    current_session["pdf_metadata"] = pdf_metadata
    current_session["session_active"] = False
    current_session["pdf_metadata"]["filename"] = filename
    current_session["pdf_metadata"]["words_extracted"] = context_summary["words_extracted"]
    current_session["pdf_metadata"]["total_words"] = context_summary["total_words"]
    current_session["pdf_metadata"]["word_limit"] = context_summary["word_limit"]
    current_session["pdf_metadata"]["truncated"] = context_summary["truncated"]
    current_session["pdf_metadata"]["paper_anchor_source"] = paper_anchor["source"]
    current_session["pdf_metadata"]["paper_anchor_words"] = paper_anchor["words"]
    current_session["pdf_metadata"]["paper_anchor_synthesis_attempted"] = paper_anchor.get("synthesis_attempted", False)
    current_session["pdf_context_stats"] = context_summary

    return {
        "success": True,
        "message": f"PDF processed: {context_summary['words_extracted']} words imported",
        "metadata": pdf_metadata,
        "context": context_summary
    }


def pdf_extraction_error(context_summary: dict) -> str:
    """Build a specific upload error for PDFs without usable essay text."""
    if context_summary.get("boilerplate_detected"):
        if context_summary.get("ocr_available"):
            return (
                "The PDF appears to contain viewer headers or scanned pages, "
                "but OCR did not find usable essay text. Please upload the original "
                "searchable PDF or export it with OCR."
            )
        return (
            "The PDF appears to contain viewer headers or scanned pages, not searchable essay text. "
            "Please upload the original searchable PDF, or install OCR support with "
            "`brew install tesseract` and `pip install PyMuPDF`."
        )

    return "No readable text found in PDF"


def ollama_model_hint(model: Optional[str] = None) -> str:
    """Return a command hint for installing the configured Ollama model."""
    model_name = model or ollama_client.model
    return f"Run `ollama pull {model_name}` or choose an installed model."


def ensure_ollama_ready(model: Optional[str] = None) -> None:
    """Raise a user-actionable error when Ollama cannot serve this app."""
    model_name = normalize_ollama_model(model)
    if not ollama_client.check_connection():
        raise HTTPException(
            status_code=503,
            detail=f"Ollama server not available at {ollama_client.base_url}. Start it with `ollama serve`."
        )

    if not ollama_client.model_available(model=model_name):
        raise HTTPException(
            status_code=503,
            detail=f"Ollama model '{model_name}' is not installed. {ollama_model_hint(model_name)}"
        )


def prompt_history_without_latest_student(student_text: str) -> list:
    """Return recent history without duplicating the latest student turn."""
    history = conversation_manager.get_conversation_history(last_n=10)
    if not history:
        return []

    latest = history[-1]
    if (
        latest.get("speaker") == "student"
        and latest.get("text", "").strip() == student_text.strip()
    ):
        return history[:-1]

    return history


def is_filler_utterance(text: str) -> bool:
    """Return true for speech fragments that should not trigger the model."""
    words = re.sub(r"[^a-zA-Z]+", " ", text or "").lower().split()
    return bool(words) and len(words) <= 4 and all(word in FILLER_WORDS for word in words)


def ensure_socratic_question(response_text: str) -> str:
    """Make voice/Socratic responses recover if a model stops without asking."""
    text = (response_text or "").strip()
    if not text or text.startswith("[Error communicating with Ollama"):
        return text

    if text.rstrip(' "\'').endswith(("?", "？")):
        return text

    return (
        f"{text} "
        "What evidence from your paper would you use to defend that point?"
    )


def extract_questions(text: str) -> list:
    """Extract questions from a bot response for repetition avoidance."""
    return [question.strip() for question in re.findall(r"[^?？]*[?？]", text or "") if question.strip()]


def compact_message(text: str, max_words: int = 45) -> str:
    """Normalize and trim one transcript message for the Socratic memory block."""
    return trim_words(re.sub(r"\s+", " ", text or "").strip(), max_words)


def build_socratic_memory() -> str:
    """
    Build a compact current-thread note from recent transcript turns.

    This is deliberately rule-based rather than an extra LLM call, so it keeps
    voice latency predictable while still anchoring follow-up questions.
    """
    history = conversation_manager.get_conversation_history(last_n=12)
    recent_student_points = []
    recent_tutor_questions = []

    for message in reversed(history):
        text = (message.get("text") or "").strip()
        if not text:
            continue

        if message.get("speaker") == "student":
            if is_filler_utterance(text):
                continue
            recent_student_points.append(compact_message(text, max_words=38))
        elif message.get("speaker") == "bot":
            questions = extract_questions(text)
            for question in reversed(questions):
                recent_tutor_questions.append(compact_message(question, max_words=32))

        if len(recent_student_points) >= 3 and len(recent_tutor_questions) >= 3:
            break

    parts = []
    if recent_student_points:
        points = list(reversed(recent_student_points[:3]))
        parts.append("Student's recent defended points: " + " / ".join(points))

    if recent_tutor_questions:
        questions = list(reversed(recent_tutor_questions[:3]))
        parts.append("Recent tutor questions already asked: " + " / ".join(questions))

    if not parts:
        return "No defended student point yet. Start by identifying the central claim the student wants to defend."

    return trim_words(" ".join(parts), SOCRATIC_MEMORY_WORD_LIMIT)


def refresh_socratic_memory() -> str:
    """Refresh in-memory and saved-session Socratic state."""
    memory = build_socratic_memory()
    current_session["socratic_memory"] = memory
    if conversation_manager.pdf_metadata is not None:
        conversation_manager.pdf_metadata["socratic_memory"] = memory
    return memory


def voice_context() -> str:
    """Build the compact context sent to Socratic voice models."""
    paper_anchor = current_session.get("paper_anchor") or trim_words(
        current_session["pdf_context"],
        PAPER_ANCHOR_WORD_LIMIT
    )
    anchor_source = current_session.get("paper_anchor_source") or "opening"
    socratic_memory = build_socratic_memory()
    current_session["socratic_memory"] = socratic_memory

    return (
        f"Paper anchor ({anchor_source}; stable short context, not the full essay):\n"
        f"{paper_anchor}\n\n"
        "Current Socratic thread (use this to continue the same line of inquiry and avoid repeated questions):\n"
        f"{socratic_memory}"
    )


def session_context_for_mode(mode: str) -> str:
    """Return a mode-appropriate essay context slice for model calls."""
    if mode == "voice":
        return voice_context()
    return current_session["pdf_context"]


def active_model_context_word_count() -> int:
    """Return the number of essay-context words sent for the active mode."""
    return len(session_context_for_mode(current_session["mode"]).split())


def stream_bot_response(student_text: str):
    """Return the mode-appropriate Ollama async stream for a student turn."""
    conversation_history = prompt_history_without_latest_student(student_text)
    mode = current_session["mode"]
    pdf_context = session_context_for_mode(mode)

    if mode == "text":
        return ollama_client.generate_editor_response_stream(
            student_input=student_text,
            pdf_context=pdf_context,
            conversation_history=conversation_history
        )

    return ollama_client.generate_socratic_response_stream(
        student_input=student_text,
        pdf_context=pdf_context,
        conversation_history=conversation_history
    )


async def generate_bot_response(student_text: str, on_chunk=None) -> str:
    """Generate a mode-appropriate bot response, streaming chunks as they arrive."""
    full_response = ""

    async for chunk in stream_bot_response(student_text):
        if chunk:
            full_response += chunk
            if on_chunk:
                await on_chunk(chunk)

    full_response = full_response.strip()
    if current_session["mode"] == "voice":
        return ensure_socratic_question(full_response)
    return full_response


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
    available_models = ollama_client.available_models() if ollama_status else []
    model_available = ollama_client.model_available(available_models) if ollama_status else False

    return {
        "status": "healthy",
        "ollama_connected": ollama_status,
        "ollama_base_url": ollama_client.base_url,
        "ollama_model": ollama_client.model,
        "ollama_model_available": model_available,
        "available_models": available_models,
        "recommended_models": RECOMMENDED_OLLAMA_MODELS,
        "default_model": OllamaClient.DEFAULT_MODEL,
        "default_whisper_model": DEFAULT_WHISPER_MODEL,
        "supported_whisper_models": sorted(SUPPORTED_WHISPER_MODELS),
        "model_hint": ollama_model_hint(),
        "pdf_uploaded": current_session["pdf_uploaded"],
        "session_active": current_session["session_active"],
        "mode": current_session["mode"]
    }


@app.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    ollama_model: Optional[str] = Form(None)
):
    """
    Handle PDF upload and extract essay context for the pilot.
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
        context_stats = parser.extract_words_with_stats(
            temp_path,
            max_words=PDF_CONTEXT_WORD_LIMIT
        )
        pdf_context = context_stats["text"]
        context_summary = public_context_stats(context_stats)
        if not pdf_context.strip() or context_summary.get("low_confidence_extraction"):
            raise HTTPException(status_code=400, detail=pdf_extraction_error(context_summary))

        paper_anchor = choose_paper_anchor(pdf_context, model=ollama_model)
        return store_processed_pdf(file.filename, temp_path, context_stats, context_summary, paper_anchor)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/upload-pdf/stream")
async def upload_pdf_stream(
    file: UploadFile = File(...),
    ollama_model: Optional[str] = Form(None)
):
    """
    Stream upload processing progress as NDJSON for the browser checklist.
    """
    async def events():
        temp_path = None

        def event(payload: dict) -> str:
            return json.dumps(payload) + "\n"

        try:
            if not file.filename.endswith('.pdf'):
                yield event({"type": "error", "message": "Only PDF files are allowed"})
                return

            upload_dir = "uploads"
            os.makedirs(upload_dir, exist_ok=True)
            temp_path = os.path.join(
                upload_dir,
                f"temp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf"
            )

            yield event({"type": "status", "step": "save", "status": "active", "message": "Saving PDF"})
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            yield event({"type": "status", "step": "save", "status": "done", "message": "PDF saved"})

            yield event({"type": "status", "step": "extract", "status": "active", "message": "Extracting readable text"})
            parser = PDFParser()
            context_stats = parser.extract_words_with_stats(
                temp_path,
                max_words=PDF_CONTEXT_WORD_LIMIT
            )
            pdf_context = context_stats["text"]
            context_summary = public_context_stats(context_stats)
            if not pdf_context.strip() or context_summary.get("low_confidence_extraction"):
                yield event({
                    "type": "error",
                    "step": "extract",
                    "message": pdf_extraction_error(context_summary)
                })
                return
            yield event({
                "type": "status",
                "step": "extract",
                "status": "done",
                "message": f"Extracted {context_summary['words_extracted']} words"
            })

            yield event({"type": "status", "step": "anchor", "status": "active", "message": "Looking for paper abstract"})
            detected_anchor = extract_paper_anchor(pdf_context)

            if detected_anchor["source"] == "abstract":
                paper_anchor = detected_anchor
                paper_anchor["synthesis_attempted"] = False
                yield event({
                    "type": "status",
                    "step": "anchor",
                    "status": "done",
                    "message": f"Detected abstract anchor ({paper_anchor['words']} words)"
                })
                yield event({
                    "type": "status",
                    "step": "synthesize",
                    "status": "done",
                    "message": "Synthesis skipped; abstract found"
                })
            else:
                yield event({
                    "type": "status",
                    "step": "anchor",
                    "status": "done",
                    "message": "No abstract detected"
                })
                yield event({
                    "type": "status",
                    "step": "synthesize",
                    "status": "active",
                    "message": "Synthesizing short paper anchor"
                })
                synthesized_anchor = synthesize_paper_anchor(pdf_context, model=ollama_model)
                if synthesized_anchor.get("text"):
                    paper_anchor = synthesized_anchor
                    paper_anchor["synthesis_attempted"] = True
                    paper_anchor["fallback_anchor_source"] = detected_anchor["source"]
                    yield event({
                        "type": "status",
                        "step": "synthesize",
                        "status": "done",
                        "message": f"Synthesized paper anchor ({paper_anchor['words']} words)"
                    })
                else:
                    paper_anchor = detected_anchor
                    paper_anchor["synthesis_attempted"] = True
                    paper_anchor["synthesis_error"] = synthesized_anchor.get("error", "Synthesis unavailable")
                    yield event({
                        "type": "status",
                        "step": "synthesize",
                        "status": "warn",
                        "message": "Synthesis unavailable; using opening words"
                    })

            yield event({"type": "status", "step": "ready", "status": "active", "message": "Preparing session state"})
            response_payload = store_processed_pdf(
                file.filename,
                temp_path,
                context_stats,
                context_summary,
                paper_anchor
            )
            yield event({"type": "status", "step": "ready", "status": "done", "message": "PDF ready"})
            yield event({"type": "success", **response_payload})

        except Exception as exc:
            yield event({"type": "error", "message": f"Error processing PDF: {str(exc)}"})

        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/start-session")
async def start_session(request: SessionStartRequest):
    """
    Initialize conversation session with Ollama and optional Whisper voice input.
    """
    mode = normalize_session_mode(request.mode)
    requested_model = normalize_ollama_model(request.ollama_model)
    whisper_model = normalize_whisper_model(request.whisper_model)
    phrase_timeout = request.phrase_timeout

    print(
        f"[SESSION] Starting {mode} session "
        f"(ollama_model={requested_model}, whisper_model={whisper_model}, "
        f"phrase_timeout={phrase_timeout}s)"
    )

    if not current_session["pdf_uploaded"]:
        raise HTTPException(status_code=400, detail="No PDF uploaded")

    try:
        ensure_ollama_ready(requested_model)
        ollama_client.set_model(requested_model)

        WhisperSTT = get_whisper_stt_class() if mode == "voice" else None
        if mode == "voice" and not WhisperSTT.list_microphones():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Voice mode is unavailable because no server-side microphones were found. "
                    "Connect a microphone and grant microphone access to the terminal or Python app "
                    "that runs this server, then restart wrtvoice."
                )
            )
        stop_active_voice_session()

        # Start conversation session
        session_metadata = dict(current_session["pdf_metadata"])
        session_metadata["mode"] = mode
        session_metadata["ollama_model"] = requested_model
        session_metadata["paper_anchor_source"] = current_session["paper_anchor_source"]
        session_metadata["paper_anchor_words"] = len(current_session["paper_anchor"].split())
        session_metadata["paper_anchor"] = current_session["paper_anchor"]
        session_id = conversation_manager.start_session(
            pdf_context=current_session["pdf_context"],
            pdf_metadata=session_metadata
        )

        # Get initial bot greeting from Ollama
        initial_response = ollama_client.initialize_context(
            current_session["pdf_context"],
            mode=mode
        )
        if initial_response.get("error"):
            raise HTTPException(status_code=502, detail=initial_response.get("response", "Ollama generation failed"))
        bot_message = initial_response.get("response", "Hello! Let's discuss your essay.")

        # Add to conversation
        conversation_manager.add_message('bot', bot_message)
        if mode == "voice":
            refresh_socratic_memory()

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
        current_session["ollama_model"] = requested_model

        return {
            "success": True,
            "session_id": session_id,
            "mode": mode,
            "ollama_model": requested_model,
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
        "ollama_model": current_session["ollama_model"],
        "metadata": current_session["pdf_metadata"],
        "context": current_session["pdf_context_stats"],
        "active_context_words": active_model_context_word_count()
        if current_session["session_active"]
        else 0,
        "conversation": conversation_manager.get_conversation_history()
        if current_session["session_active"]
        else []
    }


@app.post("/message")
async def send_text_message(request: MessageRequest):
    """
    Submit a typed student message and return the editor response.
    """
    if not current_session["session_active"]:
        raise HTTPException(status_code=400, detail="No active session")

    if current_session["mode"] != "text":
        raise HTTPException(status_code=400, detail="Typed messages are available in text mode only")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")

    ensure_ollama_ready()

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


@app.post("/message/stream")
async def stream_text_message(request: MessageRequest):
    """
    Submit a typed student message and stream the editor response as NDJSON.
    """
    if not current_session["session_active"]:
        raise HTTPException(status_code=400, detail="No active session")

    if current_session["mode"] != "text":
        raise HTTPException(status_code=400, detail="Typed messages are available in text mode only")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message text is required")

    ensure_ollama_ready()

    async def response_events():
        try:
            student_message = conversation_manager.add_message('student', text)
            yield json.dumps({
                "type": "student_message",
                "student_message": student_message
            }) + "\n"

            full_response = ""
            started_at = time.monotonic()
            first_chunk_at = None
            yield json.dumps({
                "type": "status",
                "status": "waiting_for_model",
                "model": current_session["ollama_model"],
                "context_words": active_model_context_word_count()
            }) + "\n"

            async for chunk in stream_bot_response(text):
                if not chunk:
                    continue
                if first_chunk_at is None:
                    first_chunk_at = time.monotonic()
                    yield json.dumps({
                        "type": "status",
                        "status": "first_token",
                        "elapsed_s": round(first_chunk_at - started_at, 2)
                    }) + "\n"
                full_response += chunk
                yield json.dumps({
                    "type": "bot_response_chunk",
                    "chunk": chunk,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }) + "\n"

            bot_message = conversation_manager.add_message('bot', full_response.strip())
            yield json.dumps({
                "type": "bot_response_complete",
                "bot_message": bot_message,
                "timing": {
                    "first_token_s": round(first_chunk_at - started_at, 2)
                    if first_chunk_at else None,
                    "total_s": round(time.monotonic() - started_at, 2),
                    "context_words": active_model_context_word_count(),
                    "model": current_session["ollama_model"]
                }
            }) + "\n"

        except Exception as e:
            yield json.dumps({
                "type": "error",
                "message": f"Error generating response: {str(e)}"
            }) + "\n"

    return StreamingResponse(response_events(), media_type="application/x-ndjson")


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

    def pause_voice_recording():
        # Stop recording before LLM work so responding/analyzing audio cannot enter the next turn.
        whisper_stt.stop_listening(clear_audio_queue=True)

    def resume_voice_recording():
        if current_session["session_active"] and current_session["mode"] == "voice":
            whisper_stt.clear_audio_queue()
            whisper_stt.start_listening()

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
                    if result.get('finalizing'):
                        await websocket.send_json({
                            "type": "status",
                            "status": "transcribing"
                        })
                        last_pausing_time = datetime.now(timezone.utc)
                        await asyncio.sleep(0.25)
                        continue

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
                    pause_voice_recording()
                    text = result['text']

                    # Skip empty or filler-only phrases so "um/emm" does not trigger a model turn.
                    if not text.strip() or is_filler_utterance(text):
                        if is_filler_utterance(text):
                            await websocket.send_json({"type": "discard_transcription"})
                        await websocket.send_json({"type": "status", "status": "listening"})
                        current_student_text = ""
                        last_pausing_time = None
                        resume_voice_recording()
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
                    await websocket.send_json({
                        "type": "status",
                        "status": "waiting_for_model",
                        "model": current_session["ollama_model"],
                        "context_words": active_model_context_word_count()
                    })

                    full_response = ""
                    started_at = time.monotonic()
                    first_chunk_at = None

                    async for chunk in stream_bot_response(text):
                        if not chunk:
                            continue
                        if first_chunk_at is None:
                            first_chunk_at = time.monotonic()
                            await websocket.send_json({
                                "type": "status",
                                "status": "first_token",
                                "elapsed_s": round(first_chunk_at - started_at, 2)
                            })
                        full_response += chunk
                        await websocket.send_json({
                            "type": "bot_response_chunk",
                            "chunk": chunk,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })

                    clean_response = full_response.strip()
                    final_response = ensure_socratic_question(clean_response)
                    if final_response != clean_response:
                        extra_chunk = final_response[len(clean_response):] if final_response.startswith(clean_response) else final_response
                        if extra_chunk:
                            await websocket.send_json({
                                "type": "bot_response_chunk",
                                "chunk": extra_chunk,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                    full_response = final_response

                    # Send completion signal
                    await websocket.send_json({
                        "type": "bot_response_complete",
                        "text": full_response,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "timing": {
                            "first_token_s": round(first_chunk_at - started_at, 2)
                            if first_chunk_at else None,
                            "total_s": round(time.monotonic() - started_at, 2),
                            "context_words": active_model_context_word_count(),
                            "model": current_session["ollama_model"]
                        }
                    })

                    # Add bot response to conversation
                    conversation_manager.add_message('bot', full_response)
                    refresh_socratic_memory()

                    # Return to listening status
                    await websocket.send_json({"type": "status", "status": "listening"})
                    current_student_text = ""
                    last_pausing_time = None
                    resume_voice_recording()

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
        message_count = len(conversation_manager.conversation)

        # Clean up
        reset_runtime_session()

        return {
            "success": True,
            "message": "Session ended",
            "json_file": filepath,
            "text_file": text_filepath,
            "message_count": message_count
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
    session = conversation_manager.read_session(session_id)
    if session:
        return {
            "session_id": session.get("session_id"),
            "pdf_context": session.get("pdf_context", ""),
            "conversation": session.get("conversation", []),
            "metadata": session.get("pdf_metadata", {})
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
        print(f"✓ Ollama is running ({ollama_client.model})")
    else:
        print("✗ WARNING: Ollama is not running!")
        print("  Start it with: ollama serve")

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print(f"\nServer will start at: http://{host}:{port}")
    print("Press Ctrl+C to stop\n")

    uvicorn.run(app, host=host, port=port, log_level="info")
