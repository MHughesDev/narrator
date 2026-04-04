# Debugging “multiple voices” / echo (stacked TTS)

**Echo or “extra voices” only when you press Ctrl+Alt+Plus/Minus during playback, and fine if you leave speed alone?** That pattern matches **librosa’s phase-vocoder time stretch** on the remainder of the clip (not a second `waveOut` stream). The algorithm often sounds **chorus-like or doubled**. Mitigation: set **`NARRATOR_LIVE_RATE_DEFER=1`** so rate hotkeys only affect the **next** speak (no in-play stretch).

**Sounds like one voice in a room when you are *not* changing rate?** Consider **Windows audio enhancements** / **spatial audio**, or **listening on speakers** (real room acoustics)—see **D** below.

Use **`NARRATOR_DEBUG_AUDIO=1`** when running `python -m narrator` to log process/thread IDs, `playback_gate` acquire/release, `waveOut` open/close/reset/write, and speak-worker boundaries. Combine with **`NARRATOR_DEBUG_LIVE_RATE=1`** for live-rate handoff details.

```powershell
$env:NARRATOR_DEBUG_AUDIO="1"
$env:NARRATOR_DEBUG_LIVE_RATE="1"
python -m narrator
```

---

## Hypothesis list (code → OS → hardware)

### A. Application / process

1. **Two Narrator processes** — A second `python -m narrator` plays on top of the first. Mutex normally blocks this unless `NARRATOR_ALLOW_MULTI=1`. **Check:** Task Manager → multiple `python.exe` narrating; debug logs show **two different PIDs** if both attach to logging (rare) or run two consoles.
2. **Re-entrant or parallel playback** — Bug that starts two `waveOut` streams. **Check:** `playback_gate` should serialize; logs show **nested acquire** or **two acquires without release** if broken.
3. **Duplicate `play_wav_interruptible` calls** — Worker invokes play twice for one utterance. **Check:** logs **“speech.play_wav_interruptible enter”** twice per user speak.
4. **Live-rate path** — Stretch + reopen while old audio still in mixer. **Check:** `NARRATOR_DEBUG_LIVE_RATE` handoff lines, `drain_s`, `reason=`.

### B. Windows audio stack

5. **Default playback device / mixer latency** — Old buffer still audible after `waveOutReset`/`close`. **Check:** increase `NARRATOR_POST_WAVEOUT_CLOSE_DRAIN_S`; compare headphones vs speakers.
6. **Exclusive / shared mode** — Another app or driver duplicates the stream. **Check:** close Discord, OBS, VoiceMeeter, “Enhancements” on the output device.
7. **Windows Sonic / spatial / mono mix** — Can widen or duplicate perception. **Check:** Sound → device → disable spatial audio / enhancements.

### C. TTS / signal processing

8. **Librosa phase-vocoder artifacts** — Can sound “washy” or doubled; not usually true polyphony. **Check:** disable live rate changes; if echo only when nudging rate, points here vs (5).
9. **Stereo / routing** — Wrong downmix or dual routing. **Check:** we downmix to mono before play; debug shows `channels=1` in WAV parse.

### D. User environment

10. **Bluetooth latency / multipoint** — Delayed or duplicated packets. **Check:** wired headset vs BT.
11. **Monitor with speakers + headset** — Audio mirroring to two outputs. **Check:** Sound settings, “test” only one device.
12. **Virtual audio cable** (VB-Audio, etc.) — Splits to multiple sinks. **Check:** default output device list.

### E. Listen + speak

13. **Dictation feedback** — Unlikely to mix with Piper WAV, but **Listen** uses a different path. **Check:** echo with **Listen off** and only Speak.

---

## How to read the new logs

| Log fragment | Meaning |
|--------------|---------|
| `playback_gate acquire` / `release` | Only one playback session should be **inside** the gate at a time. |
| `waveOut open` / `close` / `reset` | Device lifecycle; rapid open/open without close is suspicious. |
| `waveOutWrite` | Each submitted buffer; should be one in flight at a time in the inner loop. |
| `speech.play_wav_interruptible enter` | Once per worker play start. |
| `worker play_wav_interruptible returned` | End of playback for that WAV. |

If you see **two interleaved `play_wav_interruptible enter`** from the same PID without a **return** between them, the worker logic is wrong. If **two PIDs**, two processes.
