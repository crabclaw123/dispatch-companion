"""CPU Whisper transcription and Windows speech: no remote voice API."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile

from devices import play_wav


class LocalVoice:
    def __init__(self):
        self.model = None

    def prepare(self):
        from faster_whisper import WhisperModel
        if self.model is None:
            self.model = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=4)

    def transcribe(self, audio):
        self.prepare()
        audio.seek(0)
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                            vad_filter=True, condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments).strip()


def speak(text, device, cancel):
    # Text comes through stdin, file path through environment; no model-written
    # text is interpreted as PowerShell code. The transient WAV is deleted.
    script = """$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$text = [Console]::In.ReadToEnd()
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo -ArgumentList 24000, ([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono)
  $voice.SetOutputToWaveFile($env:DISPATCH_WAVE_PATH, $format)
  $voice.Speak($text)
} finally { $voice.Dispose() }
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    with tempfile.TemporaryDirectory(prefix="dispatch-voice-") as directory:
        path = Path(directory) / "reply.wav"
        env = dict(os.environ, DISPATCH_WAVE_PATH=str(path))
        process = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive",
                                    "-EncodedCommand", encoded], stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            process.stdin.write(text.encode("utf-8"))
            process.stdin.close()
            while process.poll() is None:
                if cancel.wait(0.05):
                    process.terminate()
                    process.wait(timeout=5)
                    return
            if process.returncode != 0 or not path.exists():
                raise RuntimeError("Windows speech failed. Your text reply is still in the radio log.")
            if not cancel.is_set():
                play_wav(path.read_bytes(), device, cancel)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
