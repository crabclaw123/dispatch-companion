# DISPATCH 📡 — ChatGPT plan + local voice

Windows gaming companion: hold F8, capture a game frame, ask aloud, release,
and hear an OpenAI model reply using your ChatGPT plan allowance.

## Updating from the first build

1. Close Dispatch and run `git pull` in your repo terminal.
2. Double-click **setup.bat** to install the new local-voice dependencies.
3. Double-click **launch.bat**. This now launches the **Plus version**.
4. Sign in through your browser with the ChatGPT account you connected during
   the test. Return to the console and choose a model number.
5. The app opens and prepares local speech recognition. Its first launch
   downloads the `base.en` Whisper model from Hugging Face; allow a few minutes.
6. Wait for **READY**. Choose your headset microphone and headphones output.
7. Start RE2 in borderless/windowed mode. Click **Test capture (no API)**,
   verify the image, then close the preview before asking questions.
8. Review **About Cam** and **Confirmed game notes**. Set your scenario,
   difficulty, objective, and confirmed inventory/location; save.
9. Enable F8, return to the game, hold F8 for your question, and release to send.
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
- **About Cam**: editable profile supplied to the model. Account memory/chats are
  not imported. Seed contains only relevant gaming preferences and preferred tone.
- **Confirmed game notes**: manually verified progress; advice is not completion.
- **Clear radio history**: keeps profile and game notes; removes conversation history.

Local Whisper runs on CPU with four threads. Windows System.Speech synthesizes
replies to a temporary WAV, plays through the selected output, and deletes it.
Mic recordings stay in memory and are transcribed locally. Only the screenshot,
question text, recent conversation and saved context are sent to OpenAI.
Screenshots are not saved by Dispatch. Text notes/history are saved to
`local/state.json`, excluded from Git. OAuth tokens stay in memory and refresh
as needed during a session; each launch signs in again. Only non-secret account
registration and host identifiers are saved under `%LOCALAPPDATA%/DispatchCompanion`.
You can disconnect the app in ChatGPT Settings. The local voice is synthetic.

## Limitations / tonight's QA

This is a first integrated build. The Plus text-only test succeeded on the
user PC; the screenshot + local mic + Windows voice loop still needs Windows
end-to-end testing. The build environment verifies compilation, state handling,
mock audio, streamed completion/failure, cancellation and token refresh.

The prompt asks for brief friendly banter, immediate-objective spoilers only,
and uncertainty when maps are unclear. These are instructions, not guarantees
of accurate navigation/no spoilers. There is no walkthrough retrieval, live
video analysis, automatic inventory updates or automatic progress recognition.

First test: typed **What can you see?** with RE2 visible. Check both text and
voice. Next test: ask it aloud with F8. Verify the transcript, answer, correct
headphones and retained context. F9 should stop playback. Close/reopen to test
saved notes/profile. Local device choices currently reset on relaunch.

| Issue | First check |
| --- | --- |
| First launch sits at preparing | Speech model downloading; check console/internet. If download fails, typed questions still work. |
| Wrong/black image | Correct monitor, borderless mode, game unobstructed and not minimized |
| Game window not found | Change title fragment from RESIDENT EVIL or choose the game monitor |
| F8 fails | Enable checkbox; same Windows permission level as game; try mic button |
| Wrong transcription | Correct headset mic, Windows desktop mic permission, quieter background |
| Text reply but no voice | Correct headphones/volume; Windows speech synthesis available; read radio log error |
| Plan limit reached | ChatGPT Settings → Usage; no automatic paid fallback |
| Session/account error | Restart and sign in again; saved registration is tied to the original account |

## Development / references

`python -m unittest discover -s tests -v`

`core.py`: state/prompt; `devices.py`: capture/audio; `plan_connection.py`: streamed
plan inference/refresh; `local_voice.py`: CPU transcription/Windows speech;
`plus_test.py`: OAuth + standalone connection test; `dispatch.py`: desktop UI.

- https://developers.openai.com/siwc/token-sharing-open-source/sign-in
- https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference
- https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
- https://github.com/SYSTRAN/faster-whisper
