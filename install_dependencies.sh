#!/bin/bash

set -u

INSTALL_VOICE=0
if [[ "${1:-}" == "--voice" || "${1:-}" == "--all" ]]; then
    INSTALL_VOICE=1
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: ./install_dependencies.sh [--voice]"
    echo ""
    echo "Default installs only web/text-mode dependencies."
    echo "--voice also installs Whisper, PyAudio, and microphone dependencies."
    exit 0
fi

echo "=========================================="
echo "  Installing Socratic Bot Dependencies"
echo "=========================================="
echo ""

PYTHON_CMD=python3

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
echo "Python version: $PYTHON_VERSION"

if [[ "$INSTALL_VOICE" -eq 1 ]]; then
    echo "Install mode: web/text + voice"
else
    echo "Install mode: web/text only"
fi

# Step 1: System dependencies for optional voice mode
echo ""
echo "Step 1: System dependencies"
echo "----------------------------------------"

if [[ "$INSTALL_VOICE" -eq 1 && "$OSTYPE" == "darwin"* ]]; then
    echo "Detected macOS voice install"

    if ! command -v brew &> /dev/null; then
        echo "Homebrew not found. Install it from https://brew.sh, then rerun with --voice."
        exit 1
    fi

    echo "Installing portaudio (for PyAudio)..."
    env -u HOMEBREW_BOTTLE_DOMAIN -u HOMEBREW_API_DOMAIN \
        HOMEBREW_NO_AUTO_UPDATE=1 brew install portaudio \
        || echo "portaudio may already be installed"
elif [[ "$INSTALL_VOICE" -eq 1 ]]; then
    echo "Voice mode requested. Install portaudio with your system package manager."
else
    echo "Skipping audio system packages. Text mode does not need PyAudio or portaudio."
fi

# Step 2: Create/activate virtual environment
echo ""
echo "Step 2: Python environment setup"
echo "----------------------------------------"
read -p "Create a virtual environment? (recommended) [y/N]: " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ ! -d "venv" ]; then
        echo "Creating virtual environment..."
        $PYTHON_CMD -m venv venv
    fi
    echo "Activating virtual environment..."
    source venv/bin/activate
    PYTHON_CMD=python
    echo "Virtual environment activated"
else
    echo "Skipping virtual environment (using system Python)"
fi

# Step 3: Install web/text dependencies
echo ""
echo "Step 3: Installing web/text dependencies"
echo "----------------------------------------"
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel
$PYTHON_CMD -m pip install -r requirements_web.txt

# Step 4: Optional voice dependencies
VOICE_INSTALL_FAILED=0
if [[ "$INSTALL_VOICE" -eq 1 ]]; then
    echo ""
    echo "Step 4: Installing optional voice dependencies"
    echo "----------------------------------------"

    $PYTHON_CMD -m pip install numpy torch SpeechRecognition openai-whisper || VOICE_INSTALL_FAILED=1

    echo "Installing PyAudio..."
    if ! $PYTHON_CMD -m pip install pyaudio; then
        echo "PyAudio failed with the default build path."
        if [[ "$OSTYPE" == "darwin"* ]]; then
            echo "Retrying with Homebrew portaudio include/library paths..."
            PORTAUDIO_PREFIX="$(brew --prefix portaudio 2>/dev/null || true)"
            if [ -z "$PORTAUDIO_PREFIX" ]; then
                PORTAUDIO_PREFIX="/opt/homebrew/opt/portaudio"
            fi
            ARCHFLAGS="-arch arm64" \
            CFLAGS="-I${PORTAUDIO_PREFIX}/include" \
            LDFLAGS="-L${PORTAUDIO_PREFIX}/lib" \
            $PYTHON_CMD -m pip install --no-cache-dir pyaudio || VOICE_INSTALL_FAILED=1
        else
            VOICE_INSTALL_FAILED=1
        fi
    fi
else
    echo ""
    echo "Step 4: Skipping voice dependencies"
    echo "----------------------------------------"
    echo "Run ./install_dependencies.sh --voice later if you need microphone mode."
fi

# Step 5: Verify installation
echo ""
echo "Step 5: Verifying installation"
echo "----------------------------------------"

$PYTHON_CMD << EOF
import sys

web_packages = {
    'fastapi': 'FastAPI',
    'uvicorn': 'Uvicorn',
    'websockets': 'WebSockets',
    'multipart': 'python-multipart',
    'PyPDF2': 'PyPDF2',
    'requests': 'requests',
    'aiohttp': 'aiohttp',
}

voice_packages = {
    'numpy': 'NumPy',
    'torch': 'PyTorch',
    'whisper': 'Whisper',
    'speech_recognition': 'SpeechRecognition',
    'pyaudio': 'PyAudio',
}

def check(packages):
    missing = []
    for module, name in packages.items():
        try:
            __import__(module)
            print(f'OK {name}')
        except ImportError:
            print(f'MISSING {name}')
            missing.append(name)
    return missing

missing_web = check(web_packages)
missing_voice = check(voice_packages) if $INSTALL_VOICE else []

if missing_web:
    print(f'\nMissing required web/text packages: {", ".join(missing_web)}')
    sys.exit(1)

if missing_voice:
    print(f'\nVoice packages still missing: {", ".join(missing_voice)}')
    print('Text mode is still usable. Fix PyAudio only if you need voice mode.')
    sys.exit(2)

print('\nDependency check complete.')
EOF

VERIFY_STATUS=$?

echo ""
if [ "$VERIFY_STATUS" -eq 0 ]; then
    echo "=========================================="
    echo "  Installation Complete"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Make sure Ollama is running: ollama serve"
    echo "2. Start the bot: ./start_bot.sh"
elif [ "$VERIFY_STATUS" -eq 2 ] || [ "$VOICE_INSTALL_FAILED" -eq 1 ]; then
    echo "=========================================="
    echo "  Text Mode Installed; Voice Incomplete"
    echo "=========================================="
    echo ""
    echo "You can still run text mode with ./start_bot.sh."
    echo "For voice mode on macOS, make sure portaudio is installed:"
    echo "  env -u HOMEBREW_BOTTLE_DOMAIN -u HOMEBREW_API_DOMAIN HOMEBREW_NO_AUTO_UPDATE=1 brew install portaudio"
else
    echo "Required web/text dependencies failed to install. Check the pip errors above."
fi
