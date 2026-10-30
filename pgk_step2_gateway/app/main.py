"""Step 2: Matrix requests -> SQLite audit -> synthetic email/SMS invitation.

LOCAL DEMO ONLY. No identity verification, clinical data upload, or FHIR filing yet.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from hashlib import sha256
from pathlib import Path
from typing import Literal
import json
import os
import re
import secrets
import smtplib
import sqlite3
import uuid

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> Path:
    return Path(os.getenv("PGK_DB_PATH", str(ROOT / "data" / "gateway.sqlite3")))


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(path, timeout=15)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    try:
        yield cx
        cx.commit()
    except Exception:
        cx.rollback()
        raise
    finally:
        cx.close()


def init_db() -> None:
    with connect() as cx:
        cx.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            matrix_event_id TEXT NOT NULL UNIQUE,
            matrix_sender TEXT NOT NULL,
            matrix_room_id TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            document_kind TEXT NOT NULL,
            recipient_name TEXT NOT NULL,
            recipient_contact TEXT NOT NULL,
            delivery_channel TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            delivery_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES requests(request_id),
            who TEXT NOT NULL,
            what TEXT NOT NULL,
            when_at TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sms_outbox (
            sms_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES requests(request_id),
            phone TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PGK Last Mile Gateway (Step 2)", lifespan=lifespan)


class CreateRequest(BaseModel):
    matrix_event_id: str = Field(min_length=3, max_length=512)
    matrix_sender: str = Field(min_length=3, max_length=256)
    matrix_room_id: str = Field(min_length=3, max_length=512)
    document_kind: Literal["lab", "rehab"]
    recipient_name: str = Field(min_length=3, max_length=150)
    recipient_contact: str = Field(min_length=5, max_length=250)


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_PATTERN = re.compile(r"^\+[0-9][0-9() \-]{5,30}$")


def require_bot(x_bot_secret: str | None = Header(default=None)) -> None:
    expected = os.getenv("PGK_BOT_SECRET", "")
    if not expected:
        raise HTTPException(503, "Server missing PGK_BOT_SECRET configuration")
    if not x_bot_secret or not secrets.compare_digest(x_bot_secret, expected):
        raise HTTPException(401, "Bot authentication required")


def record_audit(cx: sqlite3.Connection, req_id: str, who: str, what: str, details: dict | None = None):
    cx.execute(
        "INSERT INTO audit_events (audit_id, request_id, who, what, when_at, details_json) VALUES (?, ?, ?, ?, ?, ?)",
        (uuid.uuid4().hex, req_id, who, what, now_iso(), json.dumps(details or {}, ensure_ascii=False)),
    )


def deliver_email(address: str, url: str) -> None:
    """Sends only a generic invitation. No patient name, DOB, or document kind."""
    message = EmailMessage()
    message["From"] = "PGK Gateway <no-reply@pgk-demo.example>"
    message["To"] = address
    message["Subject"] = "Secure document request"
    message.set_content(
        "You have a secure document request. Open this link to verify your identity "
        f"before any details are shown:\n\n{url}\n\n"
        "If you did not expect this invitation, ignore this message.\n"
    )
    host = os.getenv("PGK_SMTP_HOST", "127.0.0.1")
    port = int(os.getenv("PGK_SMTP_PORT", "1025"))
    with smtplib.SMTP(host=host, port=port, timeout=5) as smtp:
        smtp.send_message(message)


def request_public_response(row: sqlite3.Row, created: bool):
    return {
        "request_id": row["request_id"],
        "delivery_status": row["delivery_status"],
        "delivery_channel": row["delivery_channel"],
        "created": created,
    }


@app.get("/health")
def health():
    return {"status": "ok", "stage": "requests-only"}


@app.post("/internal/requests", dependencies=[Depends(require_bot)], status_code=201)
def create_request(payload: CreateRequest, response: Response):
    allowed_room = os.getenv("PGK_ALLOWED_ROOM", "")
    allowed_sender = os.getenv("PGK_ALLOWED_SENDER", "@lena.hofer:klinikum.example")
    if not allowed_room or payload.matrix_room_id != allowed_room or payload.matrix_sender != allowed_sender:
        raise HTTPException(403, "Matrix user or room not authorized")
    channel = "email" if payload.document_kind == "lab" else "sms"
    contact = payload.recipient_contact.strip()
    if channel == "email" and not EMAIL_PATTERN.fullmatch(contact):
        raise HTTPException(422, "Lab recipient requires a valid email address")
    if channel == "sms" and not PHONE_PATTERN.fullmatch(contact):
        raise HTTPException(422, "Rehab recipient requires an international phone number")

    # Matrix event ID is the idempotency key: reconnects MUST NOT resend invitations.
    with connect() as cx:
        old = cx.execute("SELECT * FROM requests WHERE matrix_event_id = ?", (payload.matrix_event_id,)).fetchone()
        if old:
            response.status_code = 200
            return request_public_response(old, created=False)

        request_id = "req_" + uuid.uuid4().hex[:16]
        token = secrets.token_urlsafe(32)
        token_hash = sha256(token.encode()).hexdigest()
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(timespec="seconds")
        cx.execute(
            """INSERT INTO requests (
                request_id, matrix_event_id, matrix_sender, matrix_room_id,
                patient_ref, document_kind, recipient_name, recipient_contact,
                delivery_channel, token_hash, expires_at, delivery_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (request_id, payload.matrix_event_id, payload.matrix_sender, payload.matrix_room_id,
             "Patient/maria-beispiel", payload.document_kind, payload.recipient_name.strip(), contact,
             channel, token_hash, expiry, "pending", now_iso()),
        )
        record_audit(cx, request_id, payload.matrix_sender, "REQUEST_CREATED", {"kind": payload.document_kind})

    base = os.getenv("PGK_PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    url = f"{base}/r/{token}"
    try:
        if channel == "email":
            deliver_email(contact, url)
        else:
            message = "You have a secure document request. Verify your identity at: " + url
            with connect() as cx:
                cx.execute(
                    "INSERT INTO sms_outbox (sms_id, request_id, phone, message, created_at) VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, request_id, contact, message, now_iso()),
                )
        state, event = "sent", "REQUEST_SENT"
    except (OSError, smtplib.SMTPException):
        # No secret links or patient details in the audit entry.
        state, event = "failed", "DELIVERY_FAILED"

    with connect() as cx:
        cx.execute("UPDATE requests SET delivery_status = ? WHERE request_id = ?", (state, request_id))
        record_audit(cx, request_id, "pgk-gateway", event, {"channel": channel})
        row = cx.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
    return request_public_response(row, created=True)


@app.get("/internal/requests/{request_id}", dependencies=[Depends(require_bot)])
def get_request(request_id: str):
    with connect() as cx:
        row = cx.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Request not found")
        events = cx.execute(
            "SELECT who, what, when_at, details_json FROM audit_events WHERE request_id = ? ORDER BY rowid ASC",
            (request_id,),
        ).fetchall()
    return {
        "request_id": row["request_id"],
        "patient_ref": row["patient_ref"],
        "recipient_name": row["recipient_name"],
        "recipient_contact": row["recipient_contact"],
        "document_kind": row["document_kind"],
        "delivery_status": row["delivery_status"],
        "audit": [{"who": e["who"], "what": e["what"], "when": e["when_at"],
                   "details": json.loads(e["details_json"])} for e in events],
    }


@app.get("/internal/dev/sms", dependencies=[Depends(require_bot)])
def get_sms_outbox():
    """Local synthetic SMS demonstration; do not expose publicly."""
    with connect() as cx:
        rows = cx.execute("SELECT phone, message, request_id, created_at FROM sms_outbox ORDER BY rowid DESC").fetchall()
    return {"messages": [dict(r) for r in rows]}


@app.get("/r/{token}", response_class=HTMLResponse)
def invitation_landing(token: str):
    """No clinical details are exposed before verification (implemented in step 3)."""
    token_hash = sha256(token.encode()).hexdigest()
    with connect() as cx:
        row = cx.execute("SELECT request_id, expires_at FROM requests WHERE token_hash = ?", (token_hash,)).fetchone()
        valid = row is not None and datetime.fromisoformat(row["expires_at"]) > datetime.now(timezone.utc)
        if valid:
            record_audit(cx, row["request_id"], "unverified-link-holder", "LINK_OPENED")
    content = (
        "<h1>Secure document request</h1>"
        "<p>Invitation received. Identity verification is not implemented in Step 2. "
        "No patient or document details are available.</p>"
        if valid else "<h1>Invitation unavailable</h1><p>The link has expired or is invalid.</p>"
    )
    return HTMLResponse(
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>PGK Gateway</title></head><body>" + content + "</body></html>",
        status_code=200 if valid else 404,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )
