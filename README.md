# DISPATCH 📡

A Windows, capture-on-demand gaming radio companion. Hold **F8**, ask a
question, release the key, and hear a short answer based on one screenshot and
your saved game context. First profile: **Resident Evil 2 Remake**.

## First launch

1. Install **Python 3.11 or 3.12 for Windows** from https://www.python.org/downloads/windows/.
   Include the Python launcher. No administrator launch is needed.
2. Clone this repo (or download and extract its ZIP):
   ```powershell
   git clone https://github.com/crabclaw123/dispatch-companion.git
   cd dispatch-companion
   ```
3. Double-click **setup.bat**. It creates a virtual environment and installs dependencies.
4. Open the newly created **.env** in Notepad. Put your own OpenAI API key after
   `OPENAI_API_KEY=` and save. Create/manage keys at https://platform.openai.com/api-keys.
   Keep the key on your own PC; do not send it in chat or put it in GitHub.
   API use requires separate API billing; a ChatGPT subscription does not cover it.
5. Double-click **launch.bat**.
6. Start RE2 in **borderless/windowed mode**. Keep the game visible and unobstructed.
7. Select the microphone and headphones you use for gaming. Start with System default.
8. Click **Test capture (no API)**. If it cannot find the game, change the window-title
   fragment or select the specific monitor with the game on it. This is a visible-screen
   capture, not an injected game hook. A minimized or obscured window will not work.
9. Close the preview. In **Confirmed game notes**, set your scenario, difficulty,
   current objective, and any facts you actually know. Click **Save confirmed notes**.
   No old ChatGPT conversation has been imported automatically.
10. Enable the F8 checkbox. Return to RE2. Hold **F8**, wait until Dispatch shows
    **LISTENING**, speak, and release. The screenshot is taken when F8 begins,
    not when you release it. Open your map *before* F8 when asking for a route.

There is also a **Start mic / Stop mic** button and a typed **Ask + capture**
fallback. Typed questions still use the screenshot, model, and spoken reply.
**F9** stops voice/cancels a turn. An already-submitted API request can still
finish and incur charges; the app waits for it before accepting another turn.
Mic recordings stop at 30 seconds. F8 is not suppressed and may also reach the
game; unbind F8 in your game if necessary.

## Tonight's QA checklist

- Capture test shows RE2, not Dispatch/another window, and map text is readable.
- Ask “What can you see?” with a simple game frame. Compare its reply to the frame.
- Open the map, then ask “Where am I?” It should admit uncertainty if labels are unreadable.
- Ask a route question with your objective and scenario filled in.
- Verify a second question retains the conversation.
- Press F9 during playback; speech should stop. During an API call cancellation
  waits for that call to return and discards its result when possible.
- Close/reopen; confirmed notes and the last six exchanges should remain.
- Confirm no .env, screenshots, recordings, or local/state.json appear in `git status`.

## What v0.1 does and does not establish

The chain is recorded speech → transcription → image + question through the
Responses API → text-to-speech → headphones. Defaults are `gpt-4.1`,
`gpt-4o-mini-transcribe`, and `gpt-4o-mini-tts`. Model names and voice are editable
in .env. Availability depends on your API account. No continuous video analysis,
automatic inventory detection, or verified walkthrough retrieval is included.

The prompt asks for immediate-objective spoilers only, explicit uncertainty,
and a distinction between observed, confirmed, and recalled information. Those
are model instructions, **not a guarantee** of accurate navigation or no spoilers.
When unsure, Dispatch should ask you to open your map/inventory rather than
inventing a route. Future work: grounded game knowledge and structured state updates.

Screenshots and mic audio live in memory and are sent to OpenAI for each question.
They are not saved by the app. API service data handling still applies. Response
requests use `store=False`. The text radio history and confirmed notes are saved
locally in **local/state.json**, excluded from Git. Clearing radio history keeps
your confirmed notes. Microphone and capture choices currently reset on relaunch.
The spoken voice is AI-generated.

## Troubleshooting

| Problem | First check |
| --- | --- |
| Black or wrong screenshot | Borderless mode; correct monitor; game unobstructed; close preview |
| No matching window | Game running, not minimized; try title fragment `RESIDENT EVIL` or your game monitor |
| F8 does nothing | Enable checkbox; hold until LISTENING; try mic button; keep game and app at the same permission level |
| Silence / wrong mic | Windows microphone permissions for desktop apps; choose headset input; mute switch |
| Reply appears but no audio | Select headphones output; Windows volume mixer; text reply remains available |
| API key rejected | Correct .env key, save, restart; avoid whitespace or placeholder text |
| Quota / rate limit | API billing, project budget/limits, account model access |
| Slow reply | This first version has three sequential API calls and buffers generated speech before playback |
| Damaged state | Rename local/state.json as a backup; relaunch to create fresh state |

## Development

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q core.py devices.py dispatch.py
```

`core.py` contains state/request logic, `devices.py` owns capture/audio, and
`dispatch.py` owns UI/worker orchestration. UI work stays on the Tk main thread;
network/audio work runs on one background worker. No API key is needed for tests.

Reference implementations follow the official API guides:
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/speech-to-text
- https://developers.openai.com/api/docs/guides/text-to-speech

Validation in the build environment covers state, payloads, audio encoding,
cancelled playback, and Python compilation with device mocks.
Actual RE2 capture, global Windows hotkey, physical microphone/headset, and live
API end-to-end behavior require testing on the gaming PC.
