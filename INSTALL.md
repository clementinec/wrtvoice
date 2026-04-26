# Installation Guide

## Quick Install (Automated)

Text mode only, recommended for first testing:

```bash
./install_dependencies.sh
```

Socratic Oracle voice mode, including Whisper and PyAudio:

```bash
./install_dependencies.sh --voice
```

If PyAudio fails, text mode can still run. Use `pip install -r requirements_web.txt`
or rerun `./install_dependencies.sh` without `--voice`.

## Manual Install (Step-by-Step)

If the automated script fails, follow these steps:

### 1. Install System Dependencies (macOS)

```bash
# Install Homebrew if not already installed
# /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install portaudio (required for PyAudio)
env -u HOMEBREW_BOTTLE_DOMAIN -u HOMEBREW_API_DOMAIN HOMEBREW_NO_AUTO_UPDATE=1 brew install portaudio
```

### 2. Upgrade pip

```bash
pip3 install --upgrade pip setuptools wheel
```

### 3. Install Core Dependencies

```bash
# Install in this order to avoid conflicts
pip3 install numpy
pip3 install torch torchvision torchaudio
pip3 install requests
```

### 4. Install Audio Dependencies

```bash
# PyAudio (may require special flags on macOS)
pip3 install pyaudio

# If PyAudio fails, try:
ARCHFLAGS="-arch arm64" CFLAGS="-I/opt/homebrew/opt/portaudio/include" LDFLAGS="-L/opt/homebrew/opt/portaudio/lib" pip3 install pyaudio

# Or for Intel Macs:
CFLAGS="-I/usr/local/include" LDFLAGS="-L/usr/local/lib" pip3 install pyaudio

# Other audio libraries
pip3 install SpeechRecognition
```

### 5. Install Whisper

```bash
pip3 install openai-whisper
```

### 6. Install Web Framework

```bash
pip3 install fastapi
pip3 install "uvicorn[standard]"
pip3 install websockets
pip3 install python-multipart
pip3 install PyPDF2
pip3 install python-dotenv
```

### 7. Verify Installation

```bash
python3 << 'EOF'
packages = ['fastapi', 'uvicorn', 'websockets', 'PyPDF2',
            'requests', 'torch', 'numpy', 'whisper', 'speech_recognition', 'pyaudio']
for pkg in packages:
    try:
        __import__(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        print(f'✗ {pkg} - MISSING')
EOF
```

## Alternative: Use Virtual Environment

**Recommended to avoid conflicts:**

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install all dependencies
pip install -r requirements_web.txt
pip install -r requirements.txt

# When done, deactivate with:
deactivate
```

## Troubleshooting

### PyAudio won't install on macOS

**Issue**: `fatal error: 'portaudio.h' file not found`

**Solution**:
```bash
brew install portaudio
export ARCHFLAGS="-arch arm64"
export CFLAGS="-I/opt/homebrew/opt/portaudio/include"
export LDFLAGS="-L/opt/homebrew/opt/portaudio/lib"
pip3 install pyaudio
```

### PyTorch CUDA error on macOS

**Issue**: CUDA not available on macOS

**Solution**: This is normal! The app detects this automatically and uses CPU.
No action needed.

### "command not found: ollama"

**Solution**: Install Ollama first:
```bash
# Download from: https://ollama.com
# Or via Homebrew:
brew install ollama
```

### Whisper model download is slow

**First run**: Whisper downloads models (`small.en` is the voice default; `base.en` is faster and smaller)
- Models are cached in `~/.cache/whisper/`
- Subsequent runs are instant
- Use `WHISPER_MODEL=base ./start_bot.sh` to trade some accuracy for speed
- Use `PRELOAD_WHISPER_MODEL=0 ./start_bot.sh` to skip startup preload

## Verify Everything Works

```bash
# Test Ollama
ollama list

# Test Whisper
python3 -c "import whisper; print('Whisper OK')"

# Test FastAPI
python3 -c "import fastapi; print('FastAPI OK')"

# Test PyAudio
python3 -c "import pyaudio; print('PyAudio OK')"

# Test all modules
python3 modules/ollama_client.py
```

## Start the Application

```bash
./start_bot.sh
```

Or manually:
```bash
python3 app.py
```

Then open: **http://localhost:8000**
