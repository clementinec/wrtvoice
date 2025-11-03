#!/bin/bash

echo "=========================================="
echo "  Socratic Method Bot - Startup Script"
echo "=========================================="
echo ""

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "✓ Virtual environment activated"
    echo ""
fi

# Check if Ollama is running
echo "Checking Ollama status..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✓ Ollama is running"
else
    echo "✗ Ollama is not running!"
    echo ""
    echo "Please start Ollama in another terminal:"
    echo "  ollama serve"
    echo ""
    read -p "Press Enter after starting Ollama, or Ctrl+C to exit..."
fi

# Check if llama3.1 is available
echo ""
echo "Checking for llama3.1 model..."
if ollama list | grep -q "llama3.1"; then
    echo "✓ llama3.1 model found"
else
    echo "✗ llama3.1 model not found!"
    echo ""
    echo "Please install it:"
    echo "  ollama pull llama3.1"
    exit 1
fi

# Check Python dependencies
echo ""
echo "Checking Python dependencies..."
if python3 -c "import fastapi, uvicorn, whisper, speech_recognition, PyPDF2, pyttsx3" 2>/dev/null; then
    echo "✓ All Python dependencies installed"
else
    echo "✗ Missing dependencies!"
    echo ""
    echo "Please install dependencies:"
    echo "  pip install -r requirements.txt"
    echo "  pip install -r requirements_web.txt"
    exit 1
fi

# Create necessary directories
mkdir -p conversations uploads static modules

echo ""
echo "=========================================="
echo "  Starting FastAPI Server..."
echo "=========================================="
echo ""
echo "Access the application at:"
echo "  http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Start the server
python3 app.py
