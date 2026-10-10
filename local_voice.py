"""Local Whisper transcription plus neural/Windows speech playback."""
import asyncio
import base64
import io
import os
from pathlib import Path
import subprocess
import tempfile
import wave

from devices import play_wav


EDGE_VOICES = {
    "Guy — natural male": "en-US-GuyNeural",
    "Christopher — warm male": "en-US-ChristopherNeural",
    "Eric — clear male": "en-US-EricNeural",
    "Andrew — conversational male": "en-US-AndrewNeural",
    "Jenny — natural female": "en-US-JennyNeural",
    "Aria — conversational female": "en-US-AriaNeural",
}
WINDOWS_VOICE = "Windows Default — offline fallback"
VOICE_CHOICES = list(EDGE_VOICES) + [WINDOWS_VOICE]
DEFAULT_VOICE = "Guy — natural male"

SPEED_CHOICES = {
    "0.85×": "-15%",
    "0.95×": "-5%",
    "1.00×": "+0%",
    "1.10×": "+10%",
    "1.20×": "+20%",
    "1.30×": "+30%",
}
WINDOWS_SPEEDS = {
    "0.85×": -2,
    "0.95×": -1,
    "1.00×": 0,
    "1.10×": 1,
    "1.20×": 2,
    "1.30×": 3,
}
DEFAULT_SPEED = "1.00×"
ROOT = Path(__file__).resolve().parent
VOICE_ERROR_LOG = ROOT / "local" / "voice-error.log"


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


async def _edge_mp3_once(text: str, voice: str, rate: str, cancel) -> bytes:
    import edge_tts

    chunks = []
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    async for chunk in communicate.stream():
        if cancel.is_set():
            return b""
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


async def _edge_mp3(text: str, voice: str, rate: str, cancel) -> bytes:
    """Retry brief/transient Edge failures before giving up to Windows speech."""
    last_error = None
    for attempt in range(3):
        if cancel.is_set():
            return b""
        try:
            content = await _edge_mp3_once(text, voice, rate, cancel)
            if content:
                return content
            if not cancel.is_set():
                last_error = RuntimeError("Edge TTS returned no audio")
        except Exception as error:
            last_error = error
        if attempt < 2 and not cancel.is_set():
            await asyncio.sleep(0.4 * (attempt + 1))
    if last_error:
        raise last_error
    return b""


def _mp3_to_wav(content: bytes) -> bytes:
    """Decode Edge's MP3 to mono 24 kHz PCM WAV for our existing player."""
    import miniaudio

    decoded = miniaudio.decode(content, output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=24000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(decoded.samples.tobytes())
    return buffer.getvalue()


def _speak_edge(text, device, cancel, voice_name, speed_name):
    voice = EDGE_VOICES.get(voice_name, EDGE_VOICES[DEFAULT_VOICE])
    rate = SPEED_CHOICES.get(speed_name, SPEED_CHOICES[DEFAULT_SPEED])
    mp3 = asyncio.run(_edge_mp3(text, voice, rate, cancel))
    if cancel.is_set():
        return
    if not mp3:
        raise RuntimeError("Edge TTS returned no audio")
    play_wav(_mp3_to_wav(mp3), device, cancel)


def _speak_windows(text, device, cancel, speed_name=DEFAULT_SPEED):
    # Text comes through stdin, file path/rate through environment; no model-written
    # text is interpreted as PowerShell code. The transient WAV is deleted.
    script = """$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$text = [Console]::In.ReadToEnd()
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice.Rate = [int]$env:DISPATCH_SPEECH_RATE
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo -ArgumentList 24000, ([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen), ([System.Speech.AudioFormat.AudioChannel]::Mono)
  $voice.SetOutputToWaveFile($env:DISPATCH_WAVE_PATH, $format)
  $voice.Speak($text)
} finally { $voice.Dispose() }
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    with tempfile.TemporaryDirectory(prefix="dispatch-voice-") as directory:
        path = Path(directory) / "reply.wav"
        env = dict(os.environ, DISPATCH_WAVE_PATH=str(path),
                   DISPATCH_SPEECH_RATE=str(WINDOWS_SPEEDS.get(speed_name, 0)))
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


def _record_fallback_reason(voice_name, error):
    """Keep the real Edge error available instead of silently hiding it."""
    try:
        VOICE_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        message = f"{voice_name}: {type(error).__name__}: {error}"
        VOICE_ERROR_LOG.write_text(message + "\n", encoding="utf-8")
        print("DISPATCH Edge voice fallback:", message)
    except OSError:
        pass


def speak(text, device, cancel, voice_name=DEFAULT_VOICE, speed_name=DEFAULT_SPEED):
    """Speak through the selected output. Edge voices automatically fall back to Windows."""
    if voice_name == WINDOWS_VOICE:
        _speak_windows(text, device, cancel, speed_name)
        return "Windows"
    try:
        _speak_edge(text, device, cancel, voice_name, speed_name)
        return "Edge"
    except Exception as error:
        if cancel.is_set():
            return "cancelled"
        _record_fallback_reason(voice_name, error)
        _speak_windows(text, device, cancel, speed_name)
        return "Windows fallback"
