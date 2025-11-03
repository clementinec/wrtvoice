#!/bin/bash

echo "=========================================="
echo "  Installing Socratic Bot Dependencies"
echo "=========================================="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
echo "Python version: $PYTHON_VERSION"

# Step 1: System dependencies (macOS)
echo ""
echo "Step 1: Installing system dependencies..."
echo "----------------------------------------"

if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Detected macOS"

    # Check for Homebrew
    if ! command -v brew &> /dev/null; then
        echo "⚠️  Homebrew not found. Please install from: https://brew.sh"
        exit 1
    fi

    echo "Installing portaudio (for PyAudio)..."
    brew install portaudio || echo "portaudio may already be installed"

    echo "Installing ffmpeg (for audio processing)..."
    brew install ffmpeg || echo "ffmpeg may already be installed"
else
    echo "Not macOS - please install portaudio and ffmpeg manually"
fi

# Step 2: Create/activate virtual environment (optional but recommended)
echo ""
echo "Step 2: Python environment setup"
echo "----------------------------------------"
read -p "Do you want to create a virtual environment? (recommended) [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ ! -d "venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv venv
    fi
    echo "Activating virtual environment..."
    source venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "Skipping virtual environment (using system Python)"
fi

# Step 3: Upgrade pip
echo ""
echo "Step 3: Upgrading pip..."
echo "----------------------------------------"
pip install --upgrade pip setuptools wheel

# Step 4: Install core dependencies first
echo ""
echo "Step 4: Installing core dependencies..."
echo "----------------------------------------"

echo "Installing numpy..."
pip install numpy

echo "Installing PyTorch (CPU version for macOS)..."
pip install torch torchvision torchaudio

echo "Installing requests..."
pip install requests

# Step 5: Install audio dependencies
echo ""
echo "Step 5: Installing audio dependencies..."
echo "----------------------------------------"

echo "Installing PyAudio..."
pip install pyaudio || {
    echo "⚠️  PyAudio installation failed. Trying alternative method..."
    pip install --global-option='build_ext' --global-option='-I/opt/homebrew/include' --global-option='-L/opt/homebrew/lib' pyaudio
}

echo "Installing SpeechRecognition..."
pip install SpeechRecognition

echo "Installing pyttsx3 (text-to-speech)..."
pip install pyttsx3

# Step 6: Install Whisper
echo ""
echo "Step 6: Installing OpenAI Whisper..."
echo "----------------------------------------"
pip install git+https://github.com/openai/whisper.git

# Step 7: Install web framework dependencies
echo ""
echo "Step 7: Installing web framework..."
echo "----------------------------------------"

echo "Installing FastAPI..."
pip install fastapi

echo "Installing Uvicorn..."
pip install "uvicorn[standard]"

echo "Installing WebSockets..."
pip install websockets

echo "Installing python-multipart..."
pip install python-multipart

echo "Installing PyPDF2..."
pip install PyPDF2

echo "Installing python-dotenv..."
pip install python-dotenv

echo "Installing aiohttp (for async streaming)..."
pip install aiohttp

# Step 8: Verify installation
echo ""
echo "Step 8: Verifying installation..."
echo "----------------------------------------"

python3 << 'EOF'
import sys
packages = {
    'fastapi': 'FastAPI',
    'uvicorn': 'Uvicorn',
    'websockets': 'WebSockets',
    'multipart': 'python-multipart',
    'PyPDF2': 'PyPDF2',
    'pyttsx3': 'pyttsx3',
    'requests': 'requests',
    'aiohttp': 'aiohttp',
    'torch': 'PyTorch',
    'numpy': 'NumPy',
    'whisper': 'Whisper',
    'speech_recognition': 'SpeechRecognition',
    'pyaudio': 'PyAudio'
}

missing = []
for module, name in packages.items():
    try:
        __import__(module)
        print(f'✓ {name}')
    except ImportError:
        print(f'✗ {name} - MISSING')
        missing.append(name)

if missing:
    print(f'\n⚠️  Missing packages: {", ".join(missing)}')
    print('You may need to install these manually.')
    sys.exit(1)
else:
    print('\n✅ All dependencies installed successfully!')
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo "  Installation Complete!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Make sure Ollama is running: ollama serve"
    echo "2. Start the bot: ./start_bot.sh"
    echo ""
else
    echo ""
    echo "⚠️  Some packages failed to install."
    echo "Please check the errors above and install manually."
fi
