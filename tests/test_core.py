import copy
import json
from pathlib import Path
import tempfile
import unittest

from core import DEFAULT_STATE, append_turn, build_input, load_state, save_state


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


if __name__ == "__main__":
    unittest.main()
