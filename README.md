# DISPATCH 📡 — ChatGPT plan + local voice

Windows gaming companion: hold F8, capture a game frame, ask aloud, release,
and hear an OpenAI model reply using your ChatGPT plan allowance.

## Updating

1. Close Dispatch and run `git pull` in your repo terminal.
2. Double-click **setup.bat** to install/update local dependencies.
3. Double-click **launch.bat** and sign in with ChatGPT.
4. Wait for **READY**, then choose microphone, headphones, voice, speed, Whisper model, and web mode.
5. Use **Test voice (no ChatGPT)** to audition speech without using ChatGPT allowance.
6. Start RE2 in borderless/windowed mode and verify **Test capture (no API)**.
7. Enable F8, hold it to ask, and release to send. Open the map before F8 when you want routing help.

**No API key is needed. `.env` is no longer loaded. No paid API fallback exists.**
The app uses your shared ChatGPT allowance, subject to account/model access and app limits.

## Live web lookup

Dispatch can expose OpenAI's built-in Responses API `web_search` tool to the selected ChatGPT-plan model.
The **Web lookup** selector has three modes:

- **Auto** (default): routine questions stay on the same no-tool fast path as before web support. A small local relevance check enables web access only for questions that look freshness- or verification-dependent, such as “latest,” “right now,” “on sale,” or “are you sure?” If Cam explicitly asks to “look that up,” “check online,” “search the web,” etc., Dispatch forces a lookup.
- **Asked only**: the web tool stays off for normal questions and is enabled only when the question explicitly requests an online lookup.
- **Off**: Dispatch never enables web search. If a lookup is explicitly requested, the Radio Log notes that web lookup is disabled.

When search actually runs, Dispatch changes status to **SEARCHING WEB · live lookup** and logs a `WEB` system message.
Search is never claimed unless the Responses stream reports a real `web_search_call`.

Web answers keep the same spoiler-conscious GPS rules: search only for the immediate question, do not turn a specific puzzle/route lookup into a future walkthrough, and do not treat advice as confirmed progress.

Web citations returned by OpenAI are rendered as numbered clickable links in the Radio Log, with a clickable Sources line underneath the response. Before each sentence reaches TTS, Dispatch strips Markdown citation links and raw URLs so source links remain visible but are not read aloud.

Web search remains subject to the selected model and the user's ChatGPT account/workspace policy. If OpenAI does not allow web search for that model/session, Dispatch surfaces the request error rather than switching to a paid API key or another search service.

## Phase 2 speed controls

Dispatch supports three local Whisper models:

- **Tiny — fastest**: lowest transcription latency; best first choice when speed matters.
- **Base — balanced**: default balance of speed and recognition quality.
- **Small — more accurate**: slower and larger, but useful if Tiny/Base mishear you.

The first time you select a Whisper model, faster-whisper may need to download it. After that,
the selected model is remembered in `local/state.json`. Switching models replaces the loaded
model rather than keeping multiple models in memory.

### Streaming speech

ChatGPT responses are streamed by the plan connection. Dispatch consumes those text deltas as
they arrive, detects completed sentences, and feeds them to a separate speech worker. That means
ChatGPT can continue generating sentence 2 while sentence 1 is already being synthesized/spoken.
F9 still cancels both the request/playback path and queued speech.

This is intentionally sentence-by-sentence rather than word-by-word so the voice remains
natural and does not constantly restart synthesis on tiny fragments.

### Neural voice note — October 2026

Microsoft changed the Edge Read Aloud handshake in October 2026, which caused `edge-tts 7.2.8`
and earlier to fall back to Windows speech. Upstream fixed the handshake in `edge-tts 7.3.0`.
Dispatch now requires `edge-tts>=7.3.0`; run **setup.bat** after pulling this update so the neural
voice choices work again.

### Latency telemetry

After each completed question, the Radio log prints a `LATENCY` line such as:

`LATENCY · capture 0.08s · transcribe 0.61s · web search 1.20s · first token 2.10s · first sentence 2.42s · speech start 2.42s · model total 3.05s · speech playback 5.87s`

The `web search` field appears only when a live search actually ran. Measurements are also appended
to `local/performance.log` so multiple runs can be compared. The useful fields are:

- **capture** — screenshot preparation time.
- **transcribe** — local Whisper transcription time.
- **web search** — elapsed span from the first reported web-search event through the final reported search completion.
- **first token** — time from starting the ChatGPT request until the first text arrives.
- **first sentence** — time until enough text exists to begin sentence speech.
- **speech start** — time from model-request start until the speech worker begins sentence 1.
- **model total** — time until ChatGPT finishes the full response.
- **speech playback** — total time spent processing/playing queued speech after sentence 1 begins.

For an apples-to-apples speed comparison, ask the same short question several times with
**Tiny** and **Base** and compare `transcribe`, `first sentence`, and `speech start` rather than
judging only by feel. Web searches will naturally add latency, but Auto no longer advertises the
web tool on ordinary game questions.

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
- **Web lookup**: Auto, Asked only, or Off.
- **About Cam**: editable profile supplied to the model.
- **Confirmed game notes**: manually verified progress; advice is not completion.
- **Clear radio history**: keeps profile/game/settings; removes conversation history.

Local Whisper runs on CPU with four threads. Replies normally use Microsoft Edge neural TTS
over the internet, decoded locally and played through the selected sounddevice output. If Edge
TTS is unavailable, Dispatch falls back to Windows System.Speech. Choosing **Windows Default —
offline fallback** skips Edge entirely.

Mic recordings stay in memory and are transcribed locally. Only the screenshot, question text,
recent conversation and saved context are sent to OpenAI. If web lookup is enabled for a request,
OpenAI may also search the web to answer it. Screenshots are not saved. Text notes/history and
voice/Whisper/web preferences are saved to `local/state.json`, excluded from Git. OAuth tokens
stay in memory and refresh as needed during a session.

## Troubleshooting

| Issue | First check |
| --- | --- |
| Web lookup request fails | Try another eligible model/session; web search is subject to model/account/workspace policy |
| Dispatch searched when you wanted maximum speed | Change **Web lookup** to **Asked only** |
| Explicit “look it up” does not search | Confirm **Web lookup** is Auto or Asked only and check the Radio Log for a web/tool error |
| First use of a Whisper model sits at preparing/transcribing | Model may be downloading; check console/internet |
| Tiny mishears words | Switch back to Base; use Small only if accuracy still needs help |
| Neural voice falls back to Windows | Pull latest, run setup.bat so edge-tts is at least 7.3.0, then check `local/voice-error.log` if it still fails |
| Wrong/black image | Correct monitor, borderless mode, game unobstructed and not minimized |
| Game window not found | Change title fragment from RESIDENT EVIL or choose the game monitor |
| F8 fails | Enable checkbox; same Windows permission level as game; try mic button |
| Text reply but no voice | Correct headphones/volume; try Windows Default |
| Plan limit reached | ChatGPT Settings → Usage; no automatic paid fallback |

## Development / references

Run tests with:

`python -m unittest discover -s tests -v`

`core.py`: state/prompt + web relevance gate + TTS-safe citation cleanup; `devices.py`: capture/audio;
`plan_connection.py`: streamed plan inference/refresh + optional Responses web search + citation extraction;
`local_voice.py`: selectable Whisper + Edge/Windows speech; `plus_test.py`: OAuth + standalone connection test;
`dispatch.py`: desktop UI, web mode/clickable citations, streaming speech queue, and latency telemetry.

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/rany2/edge-tts
