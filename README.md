# DISPATCH 📡 — ChatGPT plan + local voice

Windows gaming companion: hold F8, capture a game frame, ask aloud, release,
and hear an OpenAI model reply using your ChatGPT plan allowance.

## Updating

1. Close Dispatch and run `git pull` in your repo terminal.
2. Double-click **setup.bat** to install/update local dependencies.
3. Double-click **launch.bat** and sign in with ChatGPT.
4. Wait for **READY**, then choose microphone, headphones, voice, speed, and Whisper model.
5. Use **Test voice (no ChatGPT)** to audition speech without using ChatGPT allowance.
6. Start RE2 in borderless/windowed mode and verify **Test capture (no API)**.
7. Enable F8, hold it to ask, and release to send. Open the map before F8 when you want routing help.

**No API key is needed. `.env` is no longer loaded. No paid API fallback exists.**
The app uses your shared ChatGPT allowance, subject to account/model access and app limits.

## Phase 2 speed controls

Dispatch now supports three local Whisper models:

- **Tiny — fastest**: lowest transcription latency; best first choice when speed matters.
- **Base — balanced**: default balance of speed and recognition quality.
- **Small — more accurate**: slower and larger, but useful if Tiny/Base mishear you.

The first time you select a Whisper model, faster-whisper may need to download it. After that,
the selected model is remembered in `local/state.json`. Switching models replaces the loaded
model rather than keeping multiple models in memory.

### Streaming speech

ChatGPT responses are already streamed by the plan connection. Dispatch now consumes those
text deltas as they arrive, detects completed sentences, and feeds them to a separate speech
worker. That means ChatGPT can continue generating sentence 2 while sentence 1 is already
being synthesized/spoken. F9 still cancels both the request/playback path and queued speech.

This is intentionally sentence-by-sentence rather than word-by-word so the voice remains
natural and does not constantly restart synthesis on tiny fragments.

### Latency telemetry

After each completed question, the Radio log prints a `LATENCY` line such as:

`LATENCY · capture 0.08s · transcribe 0.61s · first token 0.92s · first sentence 1.31s · speech start 1.31s · model total 2.44s · speech playback 5.87s`

Those measurements are also appended to `local/performance.log` so multiple runs can be
compared. The useful fields are:

- **capture** — screenshot preparation time.
- **transcribe** — local Whisper transcription time.
- **first token** — time from starting the ChatGPT request until the first text arrives.
- **first sentence** — time until enough text exists to begin sentence speech.
- **speech start** — time from model-request start until the speech worker begins sentence 1.
- **model total** — time until ChatGPT finishes the full response.
- **speech playback** — total time spent processing/playing queued speech after sentence 1 begins.

For an apples-to-apples speed comparison, ask the same short question several times with
**Tiny** and **Base** and compare `transcribe`, `first sentence`, and `speech start` rather than
judging only by feel.

## Controls and data

- **F8**: hold to capture/record, release to send (maximum 30 seconds).
- **F9**: cancel or stop voice; a sent request can still consume allowance.
- **Start mic / Stop mic**: button fallback.
- **Ask + capture**: typed question fallback, still with image and spoken answer.
- **Test capture**: local preview only, consumes no model allowance.
- **Test voice**: auditions selected voice/speed without ChatGPT.
- **Dispatch voice**: curated Microsoft Edge neural voices plus Windows offline fallback.
- **Speech speed**: selectable from 0.85× through 1.30×.
- **Whisper model**: Tiny, Base, or Small local speech recognition.
- **About Cam**: editable profile supplied to the model.
- **Confirmed game notes**: manually verified progress; advice is not completion.
- **Clear radio history**: keeps profile/game/settings; removes conversation history.

Local Whisper runs on CPU with four threads. Replies normally use Microsoft Edge neural TTS
over the internet, decoded locally and played through the selected sounddevice output. If Edge
TTS is unavailable, Dispatch falls back to Windows System.Speech. Choosing **Windows Default —
offline fallback** skips Edge entirely.

Mic recordings stay in memory and are transcribed locally. Only the screenshot, question text,
recent conversation and saved context are sent to OpenAI. Screenshots are not saved. Text
notes/history and voice/Whisper preferences are saved to `local/state.json`, excluded from Git.
OAuth tokens stay in memory and refresh as needed during a session.

## Troubleshooting

| Issue | First check |
| --- | --- |
| First use of a Whisper model sits at preparing/transcribing | Model may be downloading; check console/internet |
| Tiny mishears words | Switch back to Base; use Small only if accuracy still needs help |
| Neural voice falls back to Windows | Run setup.bat; check `local/voice-error.log` and internet |
| Wrong/black image | Correct monitor, borderless mode, game unobstructed and not minimized |
| Game window not found | Change title fragment from RESIDENT EVIL or choose the game monitor |
| F8 fails | Enable checkbox; same Windows permission level as game; try mic button |
| Text reply but no voice | Correct headphones/volume; try Windows Default |
| Plan limit reached | ChatGPT Settings → Usage; no automatic paid fallback |

## Development / references

Run tests with:

`python -m unittest discover -s tests -v`

`core.py`: state/prompt; `devices.py`: capture/audio; `plan_connection.py`: streamed
plan inference/refresh + delta callback; `local_voice.py`: selectable Whisper + Edge/Windows
speech; `plus_test.py`: OAuth + standalone connection test; `dispatch.py`: desktop UI,
streaming speech queue, and latency telemetry.

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/rany2/edge-tts
