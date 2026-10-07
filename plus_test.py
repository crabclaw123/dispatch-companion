"""One-session ChatGPT plan connection test. Never uses .env/API billing."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uuid
import webbrowser

import jwt
from openai import OpenAI

AUTH = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"


def request_json(url, data=None, bearer=None):
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlencode(data).encode()
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        # Do not echo OAuth codes, tokens, or server response bodies.
        raise RuntimeError(f"OpenAI connection returned HTTP {error.code}. No paid fallback was attempted.") from None


def validate_callback(query, expected_state, issued_client=None):
    values = parse_qs(query)
    state = values.get("state", [""])[0]
    if not secrets.compare_digest(state, expected_state):
        raise ValueError("Sign-in state mismatch. Restart the test.")
    if "error" in values:
        raise ValueError("Sign-in was declined or unavailable. No inference request was sent.")
    client = values.get("client_id", [issued_client or ""])[0]
    if not client or client == "dynamic_agent_client":
        raise ValueError("Registration did not supply an issued client ID.")
    if issued_client and client != issued_client:
        raise ValueError("Returned registration does not match the selected account.")
    code = values.get("code", [""])[0]
    if not code:
        raise ValueError("No authorization code returned.")
    return client, code


def authenticate():
    print("DISPATCH - Continue with ChatGPT")
    print("Uses your ChatGPT plan allowance. Does not load an API key or call paid voice APIs.")
    print("Tokens stay in memory for this test; browser credentials are never read by Dispatch.")
    print("Review the permissions in the official OpenAI browser page before approving.\n")
    directory = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "DispatchCompanion"
    directory.mkdir(parents=True, exist_ok=True)
    host_file = directory / "host-id.txt"
    if not host_file.exists():
        host_file.write_text("urn:uuid:" + str(uuid.uuid4()), encoding="utf-8")
    host = host_file.read_text(encoding="utf-8").strip()
    registration_file = directory / "registration.json"
    registration = json.loads(registration_file.read_text()) if registration_file.exists() else {}
    issued = registration.get("client_id")
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # callback URL contains a secret authorization code

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            try:
                client, code = validate_callback(parsed.query, state, issued)
            except ValueError:
                self.send_error(400, "Invalid or declined sign-in. Check the test window.")
                # Ignore unsolicited invalid-state requests, but finish a genuine decline.
                returned = parse_qs(parsed.query).get("state", [""])[0]
                if secrets.compare_digest(returned, state):
                    result["error"] = "Sign-in declined or registration incomplete. Restart to retry."
                return
            result.update(client=client, code=code)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Sign-in received. Close this tab and return to the Dispatch test window.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 1
        redirect = f"http://127.0.0.1:{server.server_port}/auth/callback"
        params = dict(client_id=issued or "dynamic_agent_client", ext_agent_host_id=host,
                      response_type="code", redirect_uri=redirect,
                      scope="openid profile email offline_access resource.invoke chatgpt.tokens.use.direct",
                      resource=RESOURCE, state=state, nonce=nonce,
                      code_challenge_method="S256", code_challenge=challenge)
        if not issued:
            params["agent_name_hint"] = "Dispatch Companion"
        print("Opening your browser. Sign in to the account with Plus; allow up to 5 minutes.")
        if not webbrowser.open(AUTH + "/api/accounts/authorize?" + urlencode(params)):
            raise RuntimeError("Could not open a browser. Set a default browser and rerun.")
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if not result:
        raise RuntimeError("Sign-in timed out. Run the test again.")
    if "error" in result:
        raise RuntimeError(result["error"])
    tokens = request_json(AUTH + "/api/accounts/oauth/token",
                          dict(grant_type="authorization_code", client_id=result["client"],
                               code=result["code"], code_verifier=verifier,
                               redirect_uri=redirect, resource=RESOURCE))
    key = jwt.PyJWKClient(AUTH + "/.well-known/jwks.json", timeout=30).get_signing_key_from_jwt(tokens["id_token"])
    identity = jwt.decode(tokens["id_token"], key.key, algorithms=["RS256"],
                          audience=result["client"], issuer=AUTH,
                          options={"require": ["sub", "exp", "iat", "nonce"]}, leeway=5)
    if not secrets.compare_digest(identity["nonce"], nonce):
        raise RuntimeError("Identity nonce mismatch.")
    if registration.get("subject") and identity["sub"] != registration["subject"]:
        raise RuntimeError("Signed-in account differs from this saved registration.")
    if "chatgpt.tokens.use.direct" not in tokens.get("scope", "").split():
        raise RuntimeError("Sign-in succeeded but ChatGPT plan usage was not granted.")
    # Only non-secret registration identifiers are persisted; no OAuth tokens.
    temporary = registration_file.with_suffix(".tmp")
    temporary.write_text(json.dumps({"client_id": result["client"], "subject": identity["sub"]}))
    os.replace(temporary, registration_file)
    catalog = request_json(RESOURCE + "/models", bearer=tokens["access_token"])
    models = [m for m in catalog.get("models", []) if m.get("visibility") == "list"]
    if not models:
        raise RuntimeError("No eligible models were returned for your account.")
    print("\nAvailable models:")
    for index, model in enumerate(models, 1):
        print(f"{index}. {model.get('display_name', model['slug'])}")
    choice = input("Choose a model number (Enter = 1): ").strip() or "1"
    if not choice.isdigit() or not 1 <= int(choice) <= len(models):
        raise RuntimeError("Invalid model selection. Run the test again.")
    model = models[int(choice) - 1]["slug"]
    tokens["client_id"] = result["client"]
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
    return tokens, model


def main():
    tokens, model = authenticate()
    print("\nRequesting one short reply through your ChatGPT allowance...")
    client = OpenAI(api_key=tokens["access_token"], base_url=RESOURCE, max_retries=0, timeout=45)
    completed = False
    with client.responses.create(model=model, store=False, stream=True,
                                 instructions="You are Dispatch, Cam's friendly gaming radio companion. Reply in one short sentence.",
                                 input=[{"role": "user", "content": "Say hello to Cam and confirm you're ready for a Resident Evil dispatch shift."}]) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                print(event.delta, end="", flush=True)
            elif event.type in ("response.failed", "response.incomplete", "error"):
                raise RuntimeError("Plan request failed or was incomplete. Check your ChatGPT app usage/allowance. No paid fallback was attempted.")
            elif event.type == "response.completed":
                completed = True
    if not completed:
        raise RuntimeError("Stream ended without a completed reply.")
    print("\n\nSUCCESS: ChatGPT plan inference works. This test did not use paid audio APIs.")
    print("Next: integrate this connection, screenshot input, and local voice into Dispatch.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTest cancelled.")
    except Exception as error:
        # Avoid raw SDK errors which can include response data.
        safe = str(error) if isinstance(error, (RuntimeError, ValueError)) else type(error).__name__
        print("\nTEST FAILED:", safe)
        print("Share this status message, not browser URLs, codes, or credentials.")
        raise SystemExit(1)
