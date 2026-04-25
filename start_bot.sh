#!/bin/bash

echo "=========================================="
echo "  Socratic Method Bot - Startup Script"
echo "=========================================="
echo ""

export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4:e4b}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8000}"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "✓ Virtual environment activated"
    echo ""
fi

# Check if Ollama is running
echo "Checking Ollama status..."
if curl -s "${OLLAMA_BASE_URL}/api/tags" > /dev/null 2>&1; then
    echo "✓ Ollama is running"
else
    echo "✗ Ollama is not running!"
    echo "  Checked: ${OLLAMA_BASE_URL}"
    echo ""
    echo "Please start Ollama in another terminal:"
    echo "  ollama serve"
    echo ""
    read -p "Press Enter after starting Ollama, or Ctrl+C to exit..."
fi

# Check if the configured Ollama model is available
echo ""
echo "Checking for ${OLLAMA_MODEL} model..."
model_found=0
while read -r model_name _; do
    if [ "${model_name}" = "${OLLAMA_MODEL}" ]; then
        model_found=1
        break
    fi

    if [[ "${OLLAMA_MODEL}" != *:* && "${model_name}" == "${OLLAMA_MODEL}:"* ]]; then
        model_found=1
        break
    fi
done < <(ollama list | tail -n +2)

if [ "${model_found}" -eq 1 ]; then
    echo "✓ ${OLLAMA_MODEL} model found"
else
    echo "⚠ ${OLLAMA_MODEL} model not found."
    echo ""
    echo "You can still start the app and choose any installed model in the browser."
    echo "To install the preferred default:"
    echo "  ollama pull ${OLLAMA_MODEL}"
    echo ""
    echo "Or start with a different preferred model:"
    echo "  OLLAMA_MODEL=<model-name> ./start_bot.sh"
fi

# Check Python dependencies
echo ""
echo "Checking Python dependencies..."
if python3 -c "import fastapi, uvicorn, aiohttp, requests, PyPDF2; import multipart" 2>/dev/null; then
    echo "✓ Web/text dependencies installed"
else
    echo "✗ Missing dependencies!"
    echo ""
    echo "Please install dependencies:"
    echo "  pip install -r requirements_web.txt"
    exit 1
fi

if python3 -c "import whisper, speech_recognition, pyaudio, torch, numpy" 2>/dev/null; then
    echo "✓ Voice dependencies installed"
else
    echo "Voice dependencies not found; text mode will still work."
    echo "Install requirements.txt or requirements_all.txt to enable voice mode."
fi

# Create necessary directories
mkdir -p conversations uploads static modules

echo ""
echo "=========================================="
echo "  Starting FastAPI Server..."
echo "=========================================="
echo ""
echo "Access the application at:"
echo "  http://${HOST}:${PORT}"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the server
python3 app.py
