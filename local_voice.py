"""Local Whisper transcription plus pipelined neural/Windows speech playback."""
import asyncio
import base64
from collections import deque
import io
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import wave

from core import speech_text
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

WHISPER_MODELS = {
    "Tiny — fastest": "tiny.en",
    "Base — balanced": "base.en",
    "Small — more accurate": "small.en",
}
DEFAULT_WHISPER = "Base — balanced"

ROOT = Path(__file__).resolve().parent
VOICE_ERROR_LOG = ROOT / "local" / "voice-error.log"
PERF_LOG_PATH = ROOT / "local" / "performance.log"


class LocalVoice:
    def __init__(self):
        self.model = None
        self.model_id = None

    def prepare(self, model_name=DEFAULT_WHISPER):
        from faster_whisper import WhisperModel
        model_id = WHISPER_MODELS.get(model_name, WHISPER_MODELS[DEFAULT_WHISPER])
        if self.model is None or self.model_id != model_id:
            self.model = WhisperModel(model_id, device="cpu", compute_type="int8", cpu_threads=4)
            self.model_id = model_id

    def transcribe(self, audio, model_name=DEFAULT_WHISPER):
        self.prepare(model_name)
        audio.seek(0)
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1,
                                            vad_filter=True, condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments).strip()


class _SpeechEntry:
    def __init__(self, text, stream_id=None):
        self.text = text
        self.stream_id = stream_id
        self.claimed = False
        self.ready = threading.Event()
        self.audio = b""
        self.engine = None
        self.error = None
        self.synth_seconds = 0.0
        self.ready_at = None


class _SpeechPipeline:
    """Pre-synthesize later sentences while the current sentence is playing."""

    def __init__(self):
        self.condition = threading.Condition()
        self.entries = deque()
        # voice, speed, cancel event, model-stream id, playback-thread id
        self.context = None
        self.sequence = 0
        self.last_playback_end = None
        self.worker = threading.Thread(target=self._run, daemon=True, name="dispatch-tts-prefetch")
        self.worker.start()

    def register(self, text, stream_id):
        text = speech_text(text)
        if not text:
            return
        with self.condition:
            self.entries.append(_SpeechEntry(text, stream_id))
            self.condition.notify_all()

    def claim(self, text, voice_name, speed_name, cancel):
        text = speech_text(text)
        if not text:
            return None, 0, None

        caller_id = id(threading.current_thread())
        with self.condition:
            entry = next((item for item in self.entries
                          if not item.claimed and item.text == text), None)

            if entry is not None:
                target_stream = entry.stream_id
            elif self.context is not None and self.context[4] == caller_id:
                # The unfinished final tail is queued directly by Dispatch rather than
                # passing through ready_sentences; keep it in the same response stream.
                target_stream = self.context[3]
            else:
                target_stream = ("direct", time.monotonic_ns())
                entry = _SpeechEntry(text, target_stream)
                self.entries.append(entry)

            if entry is None:
                entry = _SpeechEntry(text, target_stream)
                self.entries.append(entry)

            same_context = (
                self.context is not None
                and self.context[0] == voice_name
                and self.context[1] == speed_name
                and self.context[3] == target_stream
                and self.context[4] == caller_id
            )
            if not same_context:
                self._switch_context_locked(
                    voice_name, speed_name, cancel, target_stream, caller_id
                )

            entry.claimed = True
            self.sequence += 1
            sequence = self.sequence
            previous_end = self.last_playback_end
            self.condition.notify_all()
            return entry, sequence, previous_end

    def _switch_context_locked(self, voice_name, speed_name, cancel,
                               target_stream, caller_id):
        kept = deque()
        for item in self.entries:
            if item.stream_id == target_stream:
                kept.append(item)
            elif not item.ready.is_set():
                item.engine = "cancelled"
                item.ready_at = time.perf_counter()
                item.ready.set()
        self.entries = kept
        self.context = (voice_name, speed_name, cancel, target_stream, caller_id)
        self.sequence = 0
        self.last_playback_end = None

    def finish(self, entry, playback_end):
        with self.condition:
            try:
                self.entries.remove(entry)
            except ValueError:
                pass
            self.last_playback_end = playback_end
            self.condition.notify_all()

    def cancel_all(self):
        with self.condition:
            self._clear_locked()
            self.condition.notify_all()

    def _clear_locked(self):
        for entry in self.entries:
            if not entry.ready.is_set():
                entry.engine = "cancelled"
                entry.ready_at = time.perf_counter()
                entry.ready.set()
        self.entries.clear()
        self.context = None
        self.sequence = 0
        self.last_playback_end = None

    def _next_unsynthesized_locked(self):
        if self.context is None:
            return None
        active_stream = self.context[3]
        for entry in self.entries:
            if entry.stream_id == active_stream and not entry.ready.is_set():
                return entry
        return None

    def _run(self):
        while True:
            with self.condition:
                self.condition.wait_for(
                    lambda: self.context is not None
                    and self._next_unsynthesized_locked() is not None
                )
                entry = self._next_unsynthesized_locked()
                voice_name, speed_name, cancel, _, _ = self.context

            if cancel.is_set():
                with self.condition:
                    if not entry.ready.is_set():
                        entry.engine = "cancelled"
                        entry.ready_at = time.perf_counter()
                        entry.ready.set()
                continue

            started = time.perf_counter()
            try:
                audio, engine = _synthesize_speech(
                    entry.text, cancel, voice_name, speed_name
                )
                entry.audio = audio
                entry.engine = engine
            except Exception as error:
                entry.error = error
            finally:
                entry.synth_seconds = time.perf_counter() - started
                entry.ready_at = time.perf_counter()
                entry.ready.set()


_SPEECH_PIPELINE = _SpeechPipeline()


_ABBREVIATION_END = re.compile(
    r"(?:\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc)|(?:\b[a-z]\.){1,4})\.$",
    re.IGNORECASE,
)


def _terminal_sentence(text):
    """Treat a streamed terminal punctuation mark as complete without waiting for whitespace."""
    stripped = text.strip()
    if len(stripped) < 8 or not stripped.endswith((".", "!", "?")):
        return False
    if stripped.endswith("...") or _ABBREVIATION_END.search(stripped):
        return False
    return True


def ready_sentences(buffer):
    """Return completed sentences and pre-register them for background TTS synthesis."""
    parts = re.split(r"(?<=[.!?])\s+", buffer)
    complete = [part.strip() for part in parts[:-1] if part.strip()]
    tail = parts[-1] if parts else buffer

    # Streaming APIs often finish the last sentence with punctuation but no trailing
    # whitespace. Recognize that immediately so the final sentence can synthesize while
    # the previous one is still playing instead of waiting for response.completed.
    if _terminal_sentence(tail):
        complete.append(tail.strip())
        tail = ""

    if not complete:
        return [], buffer

    stream_id = id(threading.current_thread())
    for sentence in complete:
        _SPEECH_PIPELINE.register(sentence, stream_id)
    return complete, tail


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


def _edge_wav(text, cancel, voice_name, speed_name):
    voice = EDGE_VOICES.get(voice_name, EDGE_VOICES[DEFAULT_VOICE])
    rate = SPEED_CHOICES.get(speed_name, SPEED_CHOICES[DEFAULT_SPEED])
    mp3 = asyncio.run(_edge_mp3(text, voice, rate, cancel))
    if cancel.is_set():
        return b""
    if not mp3:
        raise RuntimeError("Edge TTS returned no audio")
    return _mp3_to_wav(mp3)


def _windows_wav(text, cancel, speed_name=DEFAULT_SPEED):
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
                    return b""
            if process.returncode != 0 or not path.exists():
                raise RuntimeError("Windows speech failed. Your text reply is still in the radio log.")
            return path.read_bytes()
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


def _synthesize_speech(text, cancel, voice_name=DEFAULT_VOICE, speed_name=DEFAULT_SPEED):
    if cancel.is_set():
        return b"", "cancelled"
    if voice_name == WINDOWS_VOICE:
        return _windows_wav(text, cancel, speed_name), "Windows"
    try:
        return _edge_wav(text, cancel, voice_name, speed_name), "Edge"
    except Exception as error:
        if cancel.is_set():
            return b"", "cancelled"
        _record_fallback_reason(voice_name, error)
        return _windows_wav(text, cancel, speed_name), "Windows fallback"


def _record_voice_timing(sequence, engine, synth_seconds, queue_wait,
                         tts_wait, audible_gap, playback_seconds, prefetched):
    parts = [
        f"VOICE · sentence {sequence}",
        f"engine {engine}",
        f"synth {synth_seconds:.2f}s",
    ]
    if queue_wait is not None:
        parts.append(f"queue wait {queue_wait:.2f}s")
    parts.append(f"tts wait {tts_wait:.2f}s")
    if audible_gap is not None:
        parts.append(f"audible gap {audible_gap:.2f}s")
    parts.append(f"playback {playback_seconds:.2f}s")
    parts.append("prefetched yes" if prefetched else "prefetched no")
    message = " · ".join(parts)
    try:
        PERF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with PERF_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
    except OSError:
        pass
    print("DISPATCH", message)


def speak(text, device, cancel, voice_name=DEFAULT_VOICE, speed_name=DEFAULT_SPEED):
    """Speak selected text while pre-synthesizing any later queued sentences."""
    text = speech_text(text)
    if not text or cancel.is_set():
        if cancel.is_set():
            _SPEECH_PIPELINE.cancel_all()
        return "skipped"

    called_at = time.perf_counter()
    entry, sequence, previous_end = _SPEECH_PIPELINE.claim(
        text, voice_name, speed_name, cancel
    )
    if entry is None:
        return "skipped"

    while not entry.ready.wait(0.05):
        if cancel.is_set():
            _SPEECH_PIPELINE.cancel_all()
            return "cancelled"

    if entry.error is not None:
        _SPEECH_PIPELINE.finish(entry, time.perf_counter())
        raise entry.error
    if cancel.is_set() or entry.engine == "cancelled" or not entry.audio:
        _SPEECH_PIPELINE.cancel_all()
        return "cancelled"

    playback_started = time.perf_counter()
    queue_wait = None if previous_end is None else max(0.0, called_at - previous_end)
    tts_wait = max(0.0, playback_started - called_at)
    audible_gap = None if previous_end is None else max(0.0, playback_started - previous_end)
    prefetched = entry.ready_at is not None and entry.ready_at <= called_at

    play_wav(entry.audio, device, cancel)
    playback_ended = time.perf_counter()
    playback_seconds = playback_ended - playback_started
    engine = entry.engine or "unknown"
    synth_seconds = entry.synth_seconds
    _SPEECH_PIPELINE.finish(entry, playback_ended)

    _record_voice_timing(
        sequence, engine, synth_seconds, queue_wait, tts_wait,
        audible_gap, playback_seconds, prefetched
    )
    return engine
