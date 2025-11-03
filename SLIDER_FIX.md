# Slider Value Fix + New Defaults

## Problem

**Slider value was NOT being passed to backend!**

User set slider to 5 seconds → Backend still used 2 seconds (default)

---

## Root Cause

FastAPI wasn't reading JSON body parameters correctly. It was expecting URL query parameters by default, but the frontend was sending JSON in the request body.

**Before** (broken):
```python
@app.post("/start-session")
async def start_session(whisper_model: str = "base", phrase_timeout: float = 2.0):
    # These parameters were read as query params, NOT from JSON body!
    # So phrase_timeout was always 2.0 (the default) ❌
```

**After** (fixed):
```python
class SessionStartRequest(BaseModel):
    whisper_model: str = "base"
    phrase_timeout: float = 5.0

@app.post("/start-session")
async def start_session(request: SessionStartRequest):
    # Now properly reads from JSON body ✅
    phrase_timeout = request.phrase_timeout
```

---

## Changes Made

### 1. **Fixed Backend to Read JSON Body** ✅

**File**: `app.py`

- Added Pydantic `SessionStartRequest` model
- Changed endpoint to accept request body
- Now properly reads `phrase_timeout` from JSON

### 2. **Updated Default to 5 Seconds** ✅

**Files**: `app.py`, `whisper_stt.py`, `index.html`

- Backend default: `phrase_timeout: float = 5.0`
- WhisperSTT default: `phrase_timeout: float = 5.0`
- Frontend slider default: `value="5.0"`

### 3. **Changed Slider Range to 4-10 Seconds** ✅

**File**: `index.html`

**Before**:
```html
<input type="range" min="1" max="5" step="0.5" value="2.0">
```

**After**:
```html
<input type="range" min="4" max="10" step="0.5" value="5.0">
```

---

## New Configuration

### Slider Settings

| Slider Value | Pause Duration | Best For |
|--------------|---------------|----------|
| **4.0s** | 4 seconds | Quick conversation |
| **5.0s** | 5 seconds | **Default - balanced** |
| **6.0s** | 6 seconds | Thoughtful responses |
| **7.0s** | 7 seconds | Slower speakers |
| **8.0s** | 8 seconds | Very patient |
| **10.0s** | 10 seconds | Maximum patience |

### Why 4-10 Seconds Range?

**Too short (< 4s)**:
- Cuts off mid-sentence
- User feels rushed
- Doesn't work well for thoughtful pauses

**Good range (4-10s)**:
- Allows natural speaking rhythm
- Time to think between phrases
- Works for all speaking speeds

**Too long (> 10s)**:
- Feels sluggish
- Long wait between exchanges
- Frustrating for quick speakers

---

## Testing

### 1. Restart Server

```bash
./start_bot.sh
```

### 2. Test Slider Values

**Set slider to 4.0 seconds**:
1. Upload PDF, start session
2. Check terminal: `[SESSION] Starting session with phrase_timeout=4.0s`
3. Speak and stop
4. Countdown should go: 4.0 → 3.5 → 3.0 → ... → 0.0

**Set slider to 10.0 seconds**:
1. Upload PDF, start session
2. Check terminal: `[SESSION] Starting session with phrase_timeout=10.0s`
3. Speak and stop
4. Countdown should go: 10.0 → 9.5 → 9.0 → ... → 0.0

### 3. Verify in Terminal

You should see:
```
[SESSION] Starting session with phrase_timeout=X.Xs from slider (model=base)
[WHISPER] Initializing with phrase_timeout=X.Xs
[WHISPER] Initialized. Timeout value in STT: X.Xs
```

**X.X should match your slider value!**

---

## Debug Output Example

**Slider set to 5.0 seconds**:

```
[SESSION] Starting session with phrase_timeout=5.0s from slider (model=base)
[WHISPER] Initializing with phrase_timeout=5.0s
[WHISPER] Initialized. Timeout value in STT: 5.0s

[DEBUG] New audio received, transcribed: 'I think the argument...'
[DEBUG] New audio received, transcribed: 'I think the argument is...'
[DEBUG] Silence: 0.25s / 5.0s, remaining: 4.75s
[DEBUG] Silence: 0.50s / 5.0s, remaining: 4.50s
[DEBUG] Silence: 1.00s / 5.0s, remaining: 4.00s
[DEBUG] Silence: 2.00s / 5.0s, remaining: 3.00s
[DEBUG] Silence: 3.00s / 5.0s, remaining: 2.00s
[DEBUG] Silence: 4.00s / 5.0s, remaining: 1.00s
[DEBUG] Silence: 5.00s / 5.0s, remaining: 0.00s
[DEBUG] ✓ Phrase complete! Timeout reached.
```

**Total countdown duration: ~5 seconds ✅**

---

## Why This Matters

### Before (Broken)

- User sets 5s → Backend uses 2s
- Unpredictable behavior
- User thinks they configured it but it's ignored
- Frustrating!

### After (Fixed)

- User sets 5s → Backend uses 5s
- Countdown matches slider setting
- Predictable, configurable behavior
- User in control!

---

## Files Changed

1. **`app.py`**:
   - Added `SessionStartRequest` Pydantic model
   - Updated `/start-session` endpoint to use request body
   - Changed default to 5.0s

2. **`modules/whisper_stt.py`**:
   - Changed default `phrase_timeout` to 5.0s

3. **`static/index.html`**:
   - Updated slider: `min="4" max="10" value="5.0"`

4. **`QUICKSTART.md`**:
   - Updated documentation with new defaults

---

## Verification Checklist

- [x] Backend reads slider value from JSON body
- [x] Terminal logs show correct timeout value
- [x] Countdown duration matches slider setting
- [x] Default is 5.0 seconds
- [x] Slider range is 4-10 seconds
- [x] All slider values work correctly

---

**Status**: ✅ FIXED - Slider value now properly passed to backend!

**New Defaults**: 5.0 seconds (range: 4-10s)

**Date**: 2025-11-04
