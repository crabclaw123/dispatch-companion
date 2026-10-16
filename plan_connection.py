"""ChatGPT plan inference only: never consumes an API key or audio endpoint."""
import time
from openai import OpenAI
from plus_test import AUTH, RESOURCE, request_json


class PlanConnection:
    def __init__(self, tokens, model):
        self.tokens = dict(tokens)
        self.model = model

    @staticmethod
    def _field(value, name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _extract_citations(cls, response):
        citations = []
        if response is None:
            return citations
        for item in cls._field(response, "output", []) or []:
            if cls._field(item, "type") != "message":
                continue
            for part in cls._field(item, "content", []) or []:
                for annotation in cls._field(part, "annotations", []) or []:
                    if cls._field(annotation, "type") != "url_citation":
                        continue
                    url = cls._field(annotation, "url", "")
                    if not url:
                        continue
                    citations.append({
                        "url": url,
                        "title": cls._field(annotation, "title", "") or url,
                        "start_index": cls._field(annotation, "start_index"),
                        "end_index": cls._field(annotation, "end_index"),
                    })
        return citations

    @classmethod
    def _last_user_text(cls, messages):
        for item in reversed(messages or []):
            if cls._field(item, "role") != "user":
                continue
            content = cls._field(item, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                chunks = []
                for part in content:
                    if cls._field(part, "type") == "input_text":
                        text = cls._field(part, "text", "")
                        if text:
                            chunks.append(text)
                return "\n".join(chunks)
        return ""

    def answer(self, instructions, messages, cancel, on_delta=None, web_policy="off",
               on_web_search=None, on_citations=None):
        if web_policy not in ("off", "auto", "required"):
            raise ValueError("Invalid web search policy")
        if time.time() >= self.tokens["expires_at"] - 90:
            old = self.tokens
            if not old.get("refresh_token"):
                raise RuntimeError("ChatGPT session expired. Restart Dispatch to sign in again.")
            fresh = request_json(AUTH + "/api/accounts/oauth/token", {
                "grant_type": "refresh_token", "client_id": old["client_id"],
                "refresh_token": old["refresh_token"], "resource": RESOURCE})
            scopes = fresh.get("scope", old.get("scope", "")).split()
            if "chatgpt.tokens.use.direct" not in scopes:
                raise RuntimeError("ChatGPT plan permission is no longer available. Restart and reconnect.")
            self.tokens = dict(old, **fresh)
            self.tokens["expires_at"] = time.time() + int(fresh.get("expires_in", 3600))
        if cancel.is_set():
            return ""
        client = OpenAI(api_key=self.tokens["access_token"], base_url=RESOURCE,
                        max_retries=0, timeout=45)
        request = dict(model=self.model, instructions=instructions,
                       input=messages, store=False, stream=True)
        effective_web_policy = web_policy
        if web_policy == "auto":
            # Advertising a tool on every turn adds routing overhead even when unused.
            # Use a cheap local relevance gate so routine game questions keep the exact
            # old fast path, while freshness/verification questions can still let the
            # model decide whether a search is necessary.
            from core import should_offer_web_lookup
            if not should_offer_web_lookup(self._last_user_text(messages)):
                effective_web_policy = "off"
        if effective_web_policy != "off":
            request["tools"] = [{"type": "web_search", "search_context_size": "low"}]
            request["tool_choice"] = "required" if effective_web_policy == "required" else "auto"
        try:
            pieces, completed = [], False
            with client.responses.create(**request) as stream:
                for event in stream:
                    if cancel.is_set():
                        return ""
                    event_type = event.type
                    if event_type == "response.output_text.delta":
                        pieces.append(event.delta)
                        if on_delta:
                            on_delta(event.delta)
                    elif event_type.startswith("response.web_search_call."):
                        if on_web_search:
                            on_web_search(event_type)
                    elif event_type in ("response.failed", "response.incomplete", "error"):
                        raise RuntimeError("ChatGPT plan request failed. Check your plan allowance/app permission. No paid fallback is enabled.")
                    elif event_type == "response.completed":
                        completed = True
                        if on_citations:
                            on_citations(self._extract_citations(getattr(event, "response", None)))
            if not completed:
                raise RuntimeError("ChatGPT connection ended before the reply completed. Try again.")
            return "".join(pieces).strip()
        finally:
            client.close()
