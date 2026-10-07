"""ChatGPT plan inference only: never consumes an API key or audio endpoint."""
import time
from openai import OpenAI
from plus_test import AUTH, RESOURCE, request_json


class PlanConnection:
    def __init__(self, tokens, model):
        self.tokens = dict(tokens)
        self.model = model

    def answer(self, instructions, messages, cancel):
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
        try:
            pieces, completed = [], False
            with client.responses.create(model=self.model, instructions=instructions,
                                         input=messages, store=False, stream=True) as stream:
                for event in stream:
                    if cancel.is_set():
                        return ""
                    if event.type == "response.output_text.delta":
                        pieces.append(event.delta)
                    elif event.type in ("response.failed", "response.incomplete", "error"):
                        raise RuntimeError("ChatGPT plan request failed. Check your plan allowance/app permission. No paid fallback is enabled.")
                    elif event.type == "response.completed":
                        completed = True
            if not completed:
                raise RuntimeError("ChatGPT connection ended before the reply completed. Try again.")
            return "".join(pieces).strip()
        finally:
            client.close()
