# DISPATCH 📡 — ChatGPT plan + local voice

Windows gaming companion: hold F8, capture a game frame, ask aloud, release,
and hear an OpenAI model reply using your ChatGPT plan allowance.

## Updating from the first build

1. Close Dispatch and run `git pull` in your repo terminal.
2. Double-click **setup.bat** to install/update the local voice dependencies, including Edge TTS.
3. Double-click **launch.bat**. This launches the ChatGPT-plan version.
4. Sign in through your browser with the ChatGPT account you connected during
   the test. Return to the console and choose a model number.
5. The app opens and prepares local speech recognition. Its first launch
   downloads the `base.en` Whisper model from Hugging Face; allow a few minutes.
6. Wait for **READY**. Choose your headset microphone and headphones output.
7. Choose a **Dispatch voice** and **Speech speed**, then click **Test voice (no ChatGPT)**
   to audition it without using ChatGPT allowance.
8. Start RE2 in borderless/windowed mode. Click **Test capture (no API)**,
   verify the image, then close the preview before asking questions.
9. Review **About Cam** and **Confirmed game notes**. Set your scenario,
   difficulty, objective, and confirmed inventory/location; save.
10. Enable F8, return to the game, hold F8 for your question, and release to send.
    Wait briefly for the microphone to open before speaking. Screenshot capture
    happens at the beginning of the question. Open the map *before* F8 for routing.

**No API key is needed. `.env` is no longer loaded. No paid API fallback exists.**
The app uses your shared ChatGPT allowance, subject to account/model access,
app limits, and any credits settings you authorize in ChatGPT. Review these
in ChatGPT Settings → Usage. This is not unlimited usage.

For a fresh installation, install Python 3.11/3.12 for Windows including its
launcher, clone this repo, run setup.bat, then launch.bat. In Git Bash use File
Explorer to double-click the batch files rather than PowerShell syntax.

## Controls and data

- **F8**: hold to capture/record, release to send (maximum 30 seconds).
- **F9**: cancel or stop voice; a sent request can still consume allowance.
- **Start mic / Stop mic**: button fallback.
- **Ask + capture**: typed question fallback, still with image and spoken answer.
- **Test capture**: local preview only, consumes no model allowance.
- **Test voice**: auditions the selected voice/speed without sending anything to ChatGPT.
- **Dispatch voice**: curated Microsoft Edge neural voices plus the original Windows offline voice.
- **Speech speed**: selectable from 0.85× through 1.30× and applies to neural or Windows speech.
- **About Cam**: editable profile supplied to the model. Account memory/chats are
  not imported. Seed contains only relevant gaming preferences and preferred tone.
- **Confirmed game notes**: manually verified progress; advice is not completion.
- **Clear radio history**: keeps profile and game notes; removes conversation history.

Local Whisper runs on CPU with four threads. By default, replies use Microsoft
Edge neural TTS over the internet. The returned MP3 is decoded locally and then
played through the same selected sounddevice output used by the existing app, so
F9 cancellation and headphone routing are preserved. If Edge TTS is unavailable,
Dispatch automatically falls back to Windows System.Speech. Choosing **Windows
Default — offline fallback** skips Edge entirely.

Mic recordings stay in memory and are transcribed locally. Only the screenshot,
question text, recent conversation and saved context are sent to OpenAI.
Screenshots are not saved by Dispatch. Text notes/history and voice preferences
are saved to `local/state.json`, excluded from Git. OAuth tokens stay in memory
and refresh as needed during a session; each launch signs in again. Only non-secret
account registration and host identifiers are saved under `%LOCALAPPDATA%/DispatchCompanion`.
You can disconnect the app in ChatGPT Settings. All voice output is synthetic.

## Limitations / QA

The neural voice path needs a live internet connection to Microsoft's Edge speech
service. If that service is unreachable or synthesis/decoding fails, Dispatch uses
Windows speech instead and notes the fallback in the radio log. The Windows voice
remains available as a direct offline selection.

The prompt asks for brief friendly banter, immediate-objective spoilers only,
and uncertainty when maps are unclear. These are instructions, not guarantees
of accurate navigation/no spoilers. There is no walkthrough retrieval, live
video analysis, automatic inventory updates or automatic progress recognition.

Recommended voice QA: run **setup.bat**, launch Dispatch, choose each voice and use
**Test voice (no ChatGPT)**. Verify the selected headphones, speed control, and F9
cancellation. Then ask one typed question and one F8 question to confirm the full
capture → ChatGPT → speech loop. Close/reopen to confirm the voice/speed preference
persists. Local microphone/output device choices still reset on relaunch.

| Issue | First check |
| --- | --- |
| First launch sits at preparing | Speech model downloading; check console/internet. If download fails, typed questions still work. |
| Neural voice falls back to Windows | Internet connection or Edge speech service availability; try Test voice again |
| Wrong/black image | Correct monitor, borderless mode, game unobstructed and not minimized |
| Game window not found | Change title fragment from RESIDENT EVIL or choose the game monitor |
| F8 fails | Enable checkbox; same Windows permission level as game; try mic button |
| Wrong transcription | Correct headset mic, Windows desktop mic permission, quieter background |
| Text reply but no voice | Correct headphones/volume; try Windows Default; read radio log error |
| Plan limit reached | ChatGPT Settings → Usage; no automatic paid fallback |
| Session/account error | Restart and sign in again; saved registration is tied to the original account |

## Development / references

`python -m unittest discover -s tests -v`

`core.py`: state/prompt; `devices.py`: capture/audio; `plan_connection.py`: streamed
plan inference/refresh; `local_voice.py`: CPU transcription + Edge/Windows speech;
`plus_test.py`: OAuth + standalone connection test; `dispatch.py`: desktop UI.

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://github.com/SYSTRAN/faster-whisper
- https://github.com/rany2/edge-tts
