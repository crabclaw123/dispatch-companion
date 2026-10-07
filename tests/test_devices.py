"""Exercise audio bytes/cancellation without physical devices or API calls."""
import importlib.util
import io
import sys
import threading
import types
import unittest
from unittest.mock import patch
import wave

import numpy as np

# Headless build environments may lack these optional hardware dependencies.
for name in ("mss", "sounddevice"):
    if importlib.util.find_spec(name) is None:
        sys.modules[name] = types.ModuleType(name)

import devices


class FakeInput:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]

    def __enter__(self):
        self.callback(np.full((16000, 1), 800, dtype=np.int16), 16000, None, None)
        return self

    def __exit__(self, *args):
        pass


class AudioTests(unittest.TestCase):
    def test_recorded_wav_has_correct_sample_rate_and_pcm(self):
        stop = threading.Event()
        stop.set()
        ready_calls = []
        with patch.object(devices.sd, "query_devices", return_value={"default_samplerate": 16000}, create=True), \
             patch.object(devices.sd, "InputStream", FakeInput, create=True):
            buffer = devices.record(stop, None, lambda: ready_calls.append(True))
        self.assertEqual(ready_calls, [True])
        with wave.open(buffer, "rb") as wav:
            self.assertEqual(wav.getframerate(), 16000)
            self.assertEqual(wav.getnframes(), 16000)
            self.assertEqual(wav.getsampwidth(), 2)

    def test_cancelled_playback_writes_no_audio(self):
        content = io.BytesIO()
        with wave.open(content, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(np.zeros(10000, dtype=np.int16).tobytes())
        stop = threading.Event()
        stop.set()
        writes, aborts = [], []

        class FakeOutput:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def write(self, data):
                writes.append(data)

            def abort(self):
                aborts.append(True)

        with patch.object(devices.sd, "OutputStream", FakeOutput, create=True):
            devices.play_wav(content.getvalue(), None, stop)
        self.assertEqual(writes, [])
        self.assertEqual(aborts, [True])

    def test_capture_rejects_disconnected_monitor(self):
        class FakeScreen:
            monitors = [{}, {"left": 0, "top": 0, "width": 800, "height": 600}]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with patch.object(devices.mss, "mss", FakeScreen, create=True):
            with self.assertRaisesRegex(RuntimeError, "no longer available"):
                devices.capture("Monitor 2", "")


if __name__ == "__main__":
    unittest.main()
