"""Matrix -> FastAPI bridge, built on the preceding matrix_smoke.py step.

Only plaintext local test rooms; never use production patient data.
"""
from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
import getpass
import json
import os
import shlex
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
MATRIX_URL = os.getenv("MATRIX_URL", "http://127.0.0.1:8008").rstrip("/")
GATEWAY_URL = os.getenv("PGK_GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
STATE_FILE = ROOT / ".state" / "last_sync_token"


def request_json(base: str, method: str, path: str, payload=None, token=None, bot_secret=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if bot_secret:
        headers["X-Bot-Secret"] = bot_secret
    if payload is not None:
        headers["Content-Type"] = "application/json"
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request(base + path, headers=headers, method=method, data=body)
    try:
        with urlopen(req, timeout=35) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:250]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Service unreachable: {exc.reason}") from exc


def parse_command(text: str) -> dict | None:
    """!request lab 'Dr. Eva Brandl' eva.brandl@labor-kanal.example
    or legacy smoke test: !request lab eva.brandl@labor-kanal.example
    """
    if not text.strip().startswith("!request"):
        return None
    try:
        parts = shlex.split(text)
    except ValueError as exc:
        raise ValueError("Quote recipient names and phone numbers") from exc
    if len(parts) not in (3, 4) or parts[0] != "!request" or parts[1] not in ("lab", "rehab"):
        raise ValueError('Usage: !request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example')
    kind = parts[1]
    if len(parts) == 3:
        name = "Dr. Eva Brandl" if kind == "lab" else "Stefan Kern"
        contact = parts[2]
    else:
        name, contact = parts[2:]
    return {"document_kind": kind, "recipient_name": name, "recipient_contact": contact}


def send_message(token: str, room_id: str, body: str):
    path = ("/_matrix/client/v3/rooms/" + quote(room_id, safe="") +
            "/send/m.room.message/" + uuid4().hex)
    request_json(MATRIX_URL, "PUT", path, {"msgtype": "m.text", "body": body}, token=token)


def main():
    secret = os.getenv("PGK_BOT_SECRET", "")
    if not secret:
        raise RuntimeError("PGK_BOT_SECRET missing from .env")
    room_id = os.getenv("PGK_ALLOWED_ROOM", "").strip()
    if not room_id:
        raise RuntimeError("Set PGK_ALLOWED_ROOM in .env")
    username = input("Matrix bot username [pgkbot]: ").strip() or "pgkbot"
    password = getpass.getpass("Matrix bot password: ")
    login = request_json(MATRIX_URL, "POST", "/_matrix/client/v3/login", {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": password,
    })
    token, user_id = login["access_token"], login["user_id"]
    print("Logged in:", user_id)
    request_json(MATRIX_URL, "POST", "/_matrix/client/v3/join/" + quote(room_id, safe=""), {}, token=token)

    if STATE_FILE.exists():
        since = STATE_FILE.read_text(encoding="utf-8").strip()
        print("Resuming from last sync token")
    else:
        # Skip existing conversation backlog on first run (only new messages are processed).
        page = request_json(MATRIX_URL, "GET", "/_matrix/client/v3/sync?" + urlencode({"timeout": 0}), token=token)
        since = page["next_batch"]
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(since, encoding="utf-8")

    send_message(token, room_id, 'Gateway online. Try: !request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example')
    print("Listening for new !request commands (Ctrl+C to stop)...")
    while True:
        path = "/_matrix/client/v3/sync?" + urlencode({"since": since, "timeout": 15000})
        page = request_json(MATRIX_URL, "GET", path, token=token)
        events = page.get("rooms", {}).get("join", {}).get(room_id, {}).get("timeline", {}).get("events", [])
        for event in events:
            if event.get("type") != "m.room.message" or event.get("sender") == user_id:
                continue
            content = event.get("content", {})
            if content.get("msgtype") != "m.text":
                continue
            sender = event.get("sender", "")
            body = content.get("body", "")
            if not body.strip().startswith("!request"):
                continue
            if sender != os.getenv("PGK_ALLOWED_SENDER", "@lena.hofer:klinikum.example"):
                print("Ignoring unauthorized Matrix sender:", sender)
                continue
            try:
                command = parse_command(body)
                payload = {**command, "matrix_sender": sender, "matrix_room_id": room_id,
                           "matrix_event_id": event["event_id"]}
                result = request_json(GATEWAY_URL, "POST", "/internal/requests", payload, bot_secret=secret)
                print("Created:", result)
                status = result["delivery_status"]
                msg = f'Request {result["request_id"]}: invitation {status} ({result["delivery_channel"]}).'
                if status == "failed":
                    msg += " Check local Mailpit and backend logs."
                send_message(token, room_id, msg)
            except (ValueError, RuntimeError, KeyError) as exc:
                print("Request failed:", exc)
                send_message(token, room_id, "Request rejected. Check command syntax or backend connection.")
        since = page["next_batch"]
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".tmp")
        temp.write_text(since, encoding="utf-8")
        temp.replace(STATE_FILE)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped")
    except RuntimeError as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1)
