"""Windows window capture and in-memory microphone/audio helpers."""
import base64
import ctypes
from ctypes import wintypes
import io
import sys
import threading
import time
import wave

import mss
import numpy as np
from PIL import Image
import sounddevice as sd


def enable_dpi_awareness():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            ctypes.windll.user32.SetProcessDPIAware()


def game_rect(title_fragment: str):
    if sys.platform != "win32":
        raise RuntimeError("Game-window capture requires Windows.")
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    matches = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
            user32.GetWindowTextW(hwnd, buffer, len(buffer))
            if title_fragment.casefold() in buffer.value.casefold():
                matches.append((hwnd, buffer.value))
        return True

    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows(visit, 0)
    if not matches:
        raise RuntimeError(f'No visible window matching "{title_fragment}". Start RE2, or choose its monitor.')
    foreground = user32.GetForegroundWindow()
    usable = [m for m in matches if not user32.IsIconic(m[0])]
    if not usable:
        raise RuntimeError("Game is minimized. Restore it before capturing.")
    hwnd, title = next((m for m in usable if m[0] == foreground), usable[0])
    rect = wintypes.RECT()
    origin = wintypes.POINT(0, 0)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise RuntimeError("Windows could not locate the game's client area.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        raise RuntimeError("Game window has no capturable area.")
    return dict(left=origin.x, top=origin.y, width=width, height=height), title


def capture(mode: str, fragment: str):
    with mss.mss() as screen:
        if mode == "Game window":
            rect, source = game_rect(fragment)
        else:
            index = int(mode.split()[-1])
            if not 1 <= index < len(screen.monitors):
                raise RuntimeError("Selected monitor is no longer available.")
            rect, source = screen.monitors[index], mode
        shot = screen.grab(rect)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
    # Preserve useful map text without sending enormous desktop frames.
    image.thumbnail((1920, 1920))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    return image, url, source


def record(stop: threading.Event, device, ready, maximum_seconds=30):
    device_info = sd.query_devices(device, "input")
    rate = int(device_info["default_samplerate"])
    chunks = []
    failures = []

    def callback(data, frames, timing, status):
        if status:
            failures.append(str(status))
        chunks.append(data.copy())

    with sd.InputStream(device=device, samplerate=rate, channels=1,
                        dtype="int16", callback=callback):
        ready()
        started = time.monotonic()
        while not stop.wait(0.02):
            if time.monotonic() - started >= maximum_seconds:
                break
    if failures:
        raise RuntimeError("Microphone dropped audio. Try another input device. " + failures[0])
    if not chunks:
        raise RuntimeError("No audio recorded. Hold F8 until LISTENING appears, then speak.")
    samples = np.concatenate(chunks)
    if len(samples) < rate * 0.25:
        raise RuntimeError("Recording was too short. Hold F8 while you ask your question.")
    if np.max(np.abs(samples.astype(np.int32))) < 100:
        raise RuntimeError("Microphone was nearly silent. Check the input device and Windows mic permissions.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    buffer.seek(0)
    buffer.name = "question.wav"
    return buffer


def play_wav(content: bytes, device, stop: threading.Event):
    with wave.open(io.BytesIO(content), "rb") as wav:
        if wav.getsampwidth() != 2:
            raise RuntimeError("Speech returned an unsupported WAV format.")
        channels, rate = wav.getnchannels(), wav.getframerate()
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
        samples = samples.reshape(-1, channels)
    # Explicit stream prevents microphone/playback cancellation from affecting
    # another operation's sounddevice convenience stream.
    with sd.OutputStream(device=device, samplerate=rate, channels=channels, dtype="int16") as stream:
        for start in range(0, len(samples), 2048):
            if stop.is_set():
                stream.abort()
                break
            stream.write(samples[start:start + 2048])
