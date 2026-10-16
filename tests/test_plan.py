"""Plan stream tests without network, OAuth credentials or installed SDK."""
import ast
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


def connection_class(openai, refresh):
    # Load just the class; the OAuth module is intentionally not initialized.
    tree = ast.parse((Path(__file__).resolve().parents[1] / "plan_connection.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    namespace = dict(OpenAI=openai, request_json=refresh, time=time,
                     AUTH="https://auth.openai.com", RESOURCE="https://api.openai.com/v1")
    exec(compile(ast.Module(body=[cls], type_ignores=[]), "plan_connection.py", "exec"), namespace)
    return namespace["PlanConnection"]


def user_message(text):
    return [{"role": "user", "content": [{"type": "input_text", "text": text}]}]


class PlanTests(unittest.TestCase):
    def setup_connection(self, events):
        client = MagicMock()
        client.responses.create.return_value.__enter__.return_value = iter(events)
        factory, refresh = MagicMock(return_value=client), MagicMock()
        cls = connection_class(factory, refresh)
        connection = cls(dict(access_token="fake", expires_at=time.time() + 1000), "test-model")
        return connection, client, factory, refresh

    def test_completed_stream_uses_plan_supported_parameters(self):
        connection, client, _, _ = self.setup_connection([
            SimpleNamespace(type="response.output_text.delta", delta="Hey Cam"),
            SimpleNamespace(type="response.completed", response=None)])
        self.assertEqual(connection.answer("prompt", [], threading.Event()), "Hey Cam")
        arguments = client.responses.create.call_args.kwargs
        self.assertTrue(arguments["stream"])
        self.assertFalse(arguments["store"])
        self.assertNotIn("max_output_tokens", arguments)
        self.assertNotIn("tools", arguments)
        client.audio.speech.create.assert_not_called()
        client.close.assert_called_once()

    def test_delta_callback_receives_text_without_changing_final_answer(self):
        connection, _, _, _ = self.setup_connection([
            SimpleNamespace(type="response.output_text.delta", delta="First sentence. "),
            SimpleNamespace(type="response.output_text.delta", delta="Second sentence."),
            SimpleNamespace(type="response.completed", response=None)])
        deltas = []
        answer = connection.answer("prompt", [], threading.Event(), on_delta=deltas.append)
        self.assertEqual(deltas, ["First sentence. ", "Second sentence."])
        self.assertEqual(answer, "First sentence. Second sentence.")

    def test_auto_web_exposes_search_tool_for_fresh_question_and_reports_events(self):
        connection, client, _, _ = self.setup_connection([
            SimpleNamespace(type="response.web_search_call.in_progress"),
            SimpleNamespace(type="response.web_search_call.searching"),
            SimpleNamespace(type="response.web_search_call.completed"),
            SimpleNamespace(type="response.output_text.delta", delta="Verified."),
            SimpleNamespace(type="response.completed", response=None)])
        web_events = []
        answer = connection.answer("prompt", user_message("What's the latest RE2 patch?"),
                                   threading.Event(), web_policy="auto",
                                   on_web_search=web_events.append)
        self.assertEqual(answer, "Verified.")
        arguments = client.responses.create.call_args.kwargs
        self.assertEqual(arguments["tools"], [{"type": "web_search", "search_context_size": "low"}])
        self.assertEqual(arguments["tool_choice"], "auto")
        self.assertEqual(web_events, ["response.web_search_call.in_progress",
                                      "response.web_search_call.searching",
                                      "response.web_search_call.completed"])

    def test_auto_web_keeps_routine_game_question_on_no_tool_fast_path(self):
        connection, client, _, _ = self.setup_connection([
            SimpleNamespace(type="response.output_text.delta", delta="Go through the west door."),
            SimpleNamespace(type="response.completed", response=None)])
        answer = connection.answer("prompt", user_message("How do I get back to the main hall?"),
                                   threading.Event(), web_policy="auto")
        self.assertEqual(answer, "Go through the west door.")
        arguments = client.responses.create.call_args.kwargs
        self.assertNotIn("tools", arguments)
        self.assertNotIn("tool_choice", arguments)

    def test_required_web_forces_search_and_returns_citations(self):
        citation = SimpleNamespace(type="url_citation", url="https://example.com/guide",
                                   title="Example Guide", start_index=0, end_index=8)
        response = SimpleNamespace(output=[SimpleNamespace(
            type="message", content=[SimpleNamespace(annotations=[citation])])])
        connection, client, _, _ = self.setup_connection([
            SimpleNamespace(type="response.web_search_call.in_progress"),
            SimpleNamespace(type="response.output_text.delta", delta="Verified"),
            SimpleNamespace(type="response.completed", response=response)])
        citations = []
        answer = connection.answer("prompt", [], threading.Event(), web_policy="required",
                                   on_citations=citations.extend)
        self.assertEqual(answer, "Verified")
        self.assertEqual(client.responses.create.call_args.kwargs["tool_choice"], "required")
        self.assertEqual(citations, [{"url": "https://example.com/guide",
                                      "title": "Example Guide",
                                      "start_index": 0, "end_index": 8}])

    def test_invalid_web_policy_is_rejected_before_request(self):
        connection, _, factory, _ = self.setup_connection([])
        with self.assertRaises(ValueError):
            connection.answer("prompt", [], threading.Event(), web_policy="sometimes")
        factory.assert_not_called()

    def test_failed_or_interrupted_stream_never_returns_partial_answer(self):
        for ending in [[], [SimpleNamespace(type="response.failed")]]:
            connection, client, _, _ = self.setup_connection([
                SimpleNamespace(type="response.output_text.delta", delta="partial"), *ending])
            with self.assertRaises(RuntimeError):
                connection.answer("prompt", [], threading.Event())
            client.close.assert_called_once()

    def test_cancel_before_request_spends_no_allowance(self):
        connection, client, factory, _ = self.setup_connection([])
        cancel = threading.Event()
        cancel.set()
        self.assertEqual(connection.answer("prompt", [], cancel), "")
        factory.assert_not_called()

    def test_refresh_rotates_token_before_inference(self):
        connection, client, factory, refresh = self.setup_connection([
            SimpleNamespace(type="response.completed", response=None)])
        connection.tokens.update(expires_at=0, refresh_token="old-refresh", client_id="issued",
                                 scope="chatgpt.tokens.use.direct")
        refresh.return_value = dict(access_token="new-access", refresh_token="new-refresh", expires_in=3600)
        connection.answer("prompt", [], threading.Event())
        self.assertEqual(connection.tokens["refresh_token"], "new-refresh")
        self.assertEqual(factory.call_args.kwargs["api_key"], "new-access")
        self.assertEqual(refresh.call_args.args[1]["client_id"], "issued")


if __name__ == "__main__":
    unittest.main()
