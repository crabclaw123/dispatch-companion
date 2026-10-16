import ast
from collections import deque
from pathlib import Path
import threading
import time
import unittest


def pipeline_classes(synthesizer):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "local_voice.py").read_text())
    wanted = {"_SpeechEntry", "_SpeechPipeline"}
    nodes = [node for node in tree.body
             if isinstance(node, ast.ClassDef) and node.name in wanted]
    namespace = dict(threading=threading, deque=deque, time=time,
                     speech_text=lambda text: text.strip(),
                     _synthesize_speech=synthesizer)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "local_voice.py", "exec"), namespace)
    return namespace["_SpeechEntry"], namespace["_SpeechPipeline"]


class VoicePipelineTests(unittest.TestCase):
    def test_second_sentence_is_synthesized_before_first_playback_finishes(self):
        calls = []

        def synthesize(text, cancel, voice_name, speed_name):
            calls.append(text)
            time.sleep(0.02)
            return text.encode(), "Edge"

        _, pipeline_type = pipeline_classes(synthesize)
        pipeline = pipeline_type()
        cancel = threading.Event()
        stream_id = "response-1"
        pipeline.register("Sentence one.", stream_id)
        pipeline.register("Sentence two.", stream_id)

        first, sequence, previous_end = pipeline.claim(
            "Sentence one.", "Guy", "1.00x", cancel
        )
        self.assertEqual(sequence, 1)
        self.assertIsNone(previous_end)
        self.assertTrue(first.ready.wait(0.5))

        # The prefetch worker should move directly to sentence two even though
        # sentence one's playback has not been marked finished yet.
        second = next(item for item in pipeline.entries if item.text == "Sentence two.")
        self.assertTrue(second.ready.wait(0.5))
        self.assertEqual(calls, ["Sentence one.", "Sentence two."])
        self.assertEqual(second.engine, "Edge")

    def test_new_response_stream_does_not_use_old_prefetch_context(self):
        calls = []

        def synthesize(text, cancel, voice_name, speed_name):
            calls.append((text, voice_name))
            return text.encode(), "Edge"

        _, pipeline_type = pipeline_classes(synthesize)
        pipeline = pipeline_type()
        cancel = threading.Event()
        pipeline.register("Old sentence.", "old-stream")
        old, _, _ = pipeline.claim("Old sentence.", "Guy", "1.00x", cancel)
        self.assertTrue(old.ready.wait(0.5))
        pipeline.finish(old, time.perf_counter())

        pipeline.register("New sentence.", "new-stream")
        new = next(item for item in pipeline.entries if item.text == "New sentence.")
        time.sleep(0.03)
        self.assertFalse(new.ready.is_set())

        claimed, sequence, previous_end = pipeline.claim(
            "New sentence.", "Christopher", "1.00x", cancel
        )
        self.assertIs(claimed, new)
        self.assertEqual(sequence, 1)
        self.assertIsNone(previous_end)
        self.assertTrue(new.ready.wait(0.5))
        self.assertEqual(calls[-1], ("New sentence.", "Christopher"))


if __name__ == "__main__":
    unittest.main()
