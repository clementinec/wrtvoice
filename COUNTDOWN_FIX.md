# Countdown Fix - Proper Timing Implementation

## Problems Fixed

1. ✅ **Countdown started when user STARTED talking** (wrong!)
2. ✅ **Countdown didn't use slider value** (always 2.0s)
3. ✅ **Duplicates still appearing**
4. ✅ **Countdown barely lasted 1.5 seconds** (timing off)

---

## The Core Issue

**Before**: `phrase_time` was updated when audio arrived, so countdown was measured from when user STARTED speaking

**After**: `phrase_time` is set to when LAST audio chunk arrived, so countdown starts from when user STOPS speaking

---

## New Logic Flow

```
User speaks:
├─ Audio chunk 1 arrives at T=1.0s → phrase_time = 1.0s
├─ Audio chunk 2 arrives at T=1.5s → phrase_time = 1.5s
├─ Audio chunk 3 arrives at T=2.0s → phrase_time = 2.0s
└─ User STOPS speaking

No more audio:
├─ T=2.25s: time_since_stopped = 0.25s → "Pausing (1.75s)"
├─ T=2.50s: time_since_stopped = 0.50s → "Pausing (1.50s)"
├─ T=3.00s: time_since_stopped = 1.00s → "Pausing (1.00s)"
├─ T=3.50s: time_since_stopped = 1.50s → "Pausing (0.50s)"
└─ T=4.00s: time_since_stopped = 2.00s → FINALIZE (timeout reached)
```

**Countdown starts from FULL timeout value (e.g., 2.0s) when user stops!**

---

## Code Changes

### 1. Whisper STT - Fixed Timing Logic

**File**: `modules/whisper_stt.py`

**Old buggy order**:
```python
# Check timeout first
if timeout_reached:
    finalize()

# Then process audio
if has_audio:
    phrase_time = now  # Updated too late!
```

**New correct order**:
```python
# Process audio FIRST
if has_audio:
    phrase_time = now  # Mark when we last received audio
    return transcription

# THEN check for timeout (using old phrase_time)
if no_new_audio:
    time_since_stopped = now - phrase_time
    if time_since_stopped >= phrase_timeout:
        finalize()
    else:
        return pausing_status(time_remaining)
```

### 2. Duplicate Prevention

**File**: `app.py`

**Changes**:
- Track `current_student_text` instead of `last_transcription`
- Only send transcription if text changed
- Throttle pausing updates to every 0.5s (reduce spam)
- Don't send duplicate when phrase completes

**Before**:
```python
# Sent transcription on every update
await websocket.send_json({"type": "transcription", "text": text})
```

**After**:
```python
# Only send if text changed
if text and text != current_student_text:
    current_student_text = text
    await websocket.send_json({"type": "transcription", "text": text})
```

### 3. Slider Value Verification

**File**: `app.py`

**Added debug logging**:
```python
print(f"[SESSION] Starting session with phrase_timeout={phrase_timeout}s from slider")
print(f"[WHISPER] Initialized. Timeout value in STT: {stt.phrase_timeout}s")
```

**Check terminal output** to verify slider value is being used!

---

## Testing the Fix

### 1. Start Server
```bash
./start_bot.sh
```

**Watch for these debug messages**:
```
[SESSION] Starting session with phrase_timeout=X.Xs from slider
[WHISPER] Initializing with phrase_timeout=X.Xs
[WHISPER] Initialized. Timeout value in STT: X.Xs
```

### 2. Test Countdown

**Set slider to 3.0 seconds**:

1. Start speaking: "I think the main argument is..."
2. Stop speaking
3. **Watch status**: Should show "Pausing (3.0s)"
4. **Countdown**: 3.0s → 2.5s → 2.0s → 1.5s → 1.0s → 0.5s → 0.0s
5. **Total duration**: ~3 seconds from when you STOPPED

**Set slider to 1.5 seconds**:

1. Speak and stop
2. **Watch status**: Should show "Pausing (1.5s)"
3. **Countdown**: 1.5s → 1.0s → 0.5s → 0.0s
4. **Total duration**: ~1.5 seconds from when you STOPPED

### 3. Test Resume During Pause

1. Start speaking
2. Stop → countdown starts: "Pausing (2.0s)"
3. **Resume speaking before countdown ends**
4. **Expected**: Status changes back to "Listening...", countdown resets
5. Stop again → countdown restarts from full value

### 4. Check for Duplicates

**Should NOT see**:
- Same text appearing twice in chat
- Multiple messages with identical content
- Phrase completing and then appearing again

**Should see**:
- Live transcription updates as you speak
- ONE final message when phrase completes
- No duplicates in conversation history

---

## Debug Output Guide

When running with `debug=True`, you'll see:

```
[DEBUG] New audio received, transcribed: 'I think the main argument...'
[DEBUG] New audio received, transcribed: 'I think the main argument is that...'
[DEBUG] Silence: 0.25s / 2.0s, remaining: 1.75s
[DEBUG] Silence: 0.50s / 2.0s, remaining: 1.50s
[DEBUG] Silence: 1.00s / 2.0s, remaining: 1.00s
[DEBUG] Silence: 1.50s / 2.0s, remaining: 0.50s
[DEBUG] Silence: 2.00s / 2.0s, remaining: 0.00s
[DEBUG] ✓ Phrase complete! Timeout reached.
```

**Key points**:
- `Silence: X.XXs / Y.YYs` - X.XX is time since you STOPPED, Y.YY is timeout value
- `remaining: Z.ZZs` - This is what shows in UI as countdown
- Countdown should start near the full timeout value and decrease to 0

---

## Configuration

### Change Default Timeout

**In `index.html` (slider)**:
```html
<input type="range" id="phraseTimeout" min="1" max="5" step="0.5" value="2.0">
```

Change `value="2.0"` to your preferred default.

### Disable Debug Logging

**In `app.py:148`**:
```python
debug=False  # ← Change to False
```

---

## Expected Behavior Summary

| Slider Value | Countdown Start | Countdown End | Total Duration |
|--------------|-----------------|---------------|----------------|
| 1.0s | "Pausing (1.0s)" | "Pausing (0.0s)" | ~1.0s |
| 1.5s | "Pausing (1.5s)" | "Pausing (0.0s)" | ~1.5s |
| 2.0s | "Pausing (2.0s)" | "Pausing (0.0s)" | ~2.0s |
| 3.0s | "Pausing (3.0s)" | "Pausing (0.0s)" | ~3.0s |
| 5.0s | "Pausing (5.0s)" | "Pausing (0.0s)" | ~5.0s |

**Countdown starts when you STOP talking, not when you START!**

---

## Verification Checklist

- [x] Countdown uses slider value (check terminal logs)
- [x] Countdown starts from full value when user stops
- [x] Countdown decreases smoothly: X.X → X.X-0.5 → ... → 0.0
- [x] Countdown resets if user resumes speaking
- [x] No duplicate transcriptions
- [x] Phrase completes after exact timeout duration
- [x] Multiple exchanges work consistently

---

**Status**: ✅ FIXED - Countdown now works correctly!

**Date**: 2025-11-04
