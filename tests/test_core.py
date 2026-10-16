import copy
import json
from pathlib import Path
import tempfile
import unittest

from core import (DEFAULT_STATE, append_turn, build_input, load_state,
                  requests_web_lookup, save_state, should_offer_web_lookup,
                  speech_text)


class StateTests(unittest.TestCase):
    def test_roundtrip_preserves_confirmed_notes_and_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local" / "state.json"
            state = load_state(path)
            state["confirmed_notes"] = "Leon — shotgun acquired; ammo not recounted"
            append_turn(state, "Where next?", "Open your map.")
            save_state(path, state)
            self.assertEqual(load_state(path), state)
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_advice_never_changes_confirmed_state(self):
        state = copy.deepcopy(DEFAULT_STATE)
        before = {key: value for key, value in state.items() if key != "history"}
        for i in range(15):
            append_turn(state, f"Question {i}", "Go to Library")
        self.assertEqual(len(state["history"]), 12)
        self.assertEqual(before, {key: value for key, value in state.items() if key != "history"})

    def test_request_has_only_current_frame_and_bounded_text_history(self):
        state = copy.deepcopy(DEFAULT_STATE)
        append_turn(state, "Earlier question", "Earlier answer")
        request = build_input(state, "Where am I?", "data:image/jpeg;base64,abc", "RE2")
        self.assertEqual(request[0]["role"], "developer")
        self.assertNotIn("history", json.loads(request[0]["content"].split("\n", 1)[1]))
        images = [part for item in request if isinstance(item["content"], list)
                  for part in item["content"] if part["type"] == "input_image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["detail"], "high")

    def test_invalid_state_does_not_silently_erase_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"confirmed_notes": 12}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_state(path)

    def test_history_ignores_invalid_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"history": [{"role": "developer", "content": "bad"},
                                                      {"role": "user", "content": "good"}]}))
            self.assertEqual(load_state(path)["history"], [{"role": "user", "content": "good"}])

    def test_explicit_web_request_phrases_are_detected(self):
        for question in ("Dispatch, look that up for me.",
                         "Can you search the web for that?",
                         "Retesting web search and speed of response.",
                         "Try an internet search for this.",
                         "Check online and verify the safe code.",
                         "Google it, bro."):
            self.assertTrue(requests_web_lookup(question), question)
        self.assertFalse(requests_web_lookup("How do I get back to the main hall?"))

    def test_auto_web_gate_only_opens_for_freshness_or_verification_cues(self):
        for question in ("What's the latest RE2 patch?",
                         "Is Resident Evil 2 on sale right now?",
                         "Are you sure that safe code is correct?",
                         "Double check that for me."):
            self.assertTrue(should_offer_web_lookup(question), question)
        self.assertFalse(should_offer_web_lookup("How do I get back to the main hall?"))
        self.assertFalse(should_offer_web_lookup("What is my current objective?"))

    def test_speech_text_strips_web_citations_but_keeps_normal_words(self):
        cited = ("Radio and web check complete, buddy. "
                 "([store.steampowered.com](https://store.steampowered.com/app/883710/?utm_source=openai))")
        self.assertEqual(speech_text(cited), "Radio and web check complete, buddy.")
        self.assertEqual(speech_text("Check [Steam](https://store.steampowered.com) for details."),
                         "Check Steam for details.")
        self.assertEqual(speech_text("Source: https://example.com/path?q=1"), "Source:")


if __name__ == "__main__":
    unittest.main()
