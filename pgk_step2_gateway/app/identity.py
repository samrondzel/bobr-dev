"""Step 3: *synthetic* identity proof + misdelivery M1/M2.

This is a pedagogical identity-provider simulator, not ID Austria and not safe for
real medical data. The recipient never self-certifies a name: a fixture credential
is checked server-side, producing a synthetic subject identifier.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from hmac import compare_digest
from html import escape
import os
import secrets
import sqlite3
import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import main as gateway

router = APIRouter()

# Local test identities; the subject IDs are deliberately not email addresses.
# A deployment would replace this entire module with a real identity provider.
IDENTITIES = {
    "eva": ("eid-demo-eva-brandl", "Dr. Eva Brandl", "PGK_MOCK_EID_EVA_PIN"),
    "stefan": ("eid-demo-stefan-kern", "Stefan Kern", "PGK_MOCK_EID_STEFAN_PIN"),
    "colleague": ("eid-demo-colleague", "Lab colleague", "PGK_MOCK_EID_COLLEAGUE_PIN"),
    "outsider": ("eid-demo-outsider", "Unrelated recipient", "PGK_MOCK_EID_OUTSIDER_PIN"),
}
EXPECTED_NAME_TO_SUBJECT = {
    "dr. eva brandl": "eid-demo-eva-brandl",
    "eva brandl": "eid-demo-eva-brandl",
    "stefan kern": "eid-demo-stefan-kern",
}

MAX_FAILURES = 5
SESSION_MINUTES = 10


def init_identity_db(cx: sqlite3.Connection) -> None:
    cx.executescript("""
    CREATE TABLE IF NOT EXISTS identity_sessions (
        session_hash TEXT PRIMARY KEY,
        request_id TEXT NOT NULL REFERENCES requests(request_id),
        subject_id TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_identity_sessions_request ON identity_sessions(request_id);
    CREATE TABLE IF NOT EXISTS identity_attempts (
        request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
        failed_count INTEGER NOT NULL DEFAULT 0
    );
    """)


def security_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def document(title: str, content: str, status_code: int = 200) -> HTMLResponse:
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>PGK Gateway</title><style>
      body{font-family:system-ui,Arial,sans-serif;background:#f1f5f9;color:#13232f;margin:0;padding:34px 16px}
      main{max-width:530px;margin:auto;background:white;border:1px solid #dde4e8;border-radius:12px;padding:28px;box-shadow:0 8px 28px #172b4010}
      h1{font-size:26px;margin-top:0}p{line-height:1.55}label{display:block;font-weight:600;margin:15px 0 6px}
      select,input,button{box-sizing:border-box;width:100%;font-size:16px;padding:12px;border-radius:7px;border:1px solid #a4b6c3}
      button{margin-top:20px;background:#087f70;color:white;border:none;cursor:pointer;font-weight:600}
      .note{color:#536473;font-size:13px}.status{padding:12px;background:#f0f6f5;border-radius:8px}
    </style></head><body><main>""" + content + "</main></body></html>"
    return HTMLResponse(html, status_code=status_code, headers=security_headers())


def resolve_link(cx: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    if len(token) > 256:
        return None
    hash_ = sha256(token.encode("utf-8")).hexdigest()
    row = cx.execute("SELECT * FROM requests WHERE token_hash = ?", (hash_,)).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    if row["delivery_status"] != "sent":
        return None
    return row


def denied(message: str = "Identity verification failed.", status: int = 403) -> HTMLResponse:
    return document("Identity verification", "<h1>Unable to continue</h1><p>" + escape(message) + "</p>"
                    "<p class='note'>No medical information has been disclosed.</p>", status)


def recorded_failure(cx: sqlite3.Connection, row: sqlite3.Row, who: str, reason: str, identity_confirmed: bool) -> None:
    # Never store raw PINs in the audit log.
    gateway.record_audit(cx, row["request_id"], who, "IDENTITY_CHECKED", {
        "result": "denied", "method": "synthetic-mock-eid", "reason": reason
    })
    if identity_confirmed:
        gateway.record_audit(cx, row["request_id"], who, "MISDELIVERY_CAUGHT", {
            "reason": "recipient_identity_mismatch", "action": "blocked_before_disclosure"
        })
    cx.execute("""INSERT INTO identity_attempts (request_id, failed_count)
                  VALUES (?,1) ON CONFLICT(request_id)
                  DO UPDATE SET failed_count = failed_count + 1""", (row["request_id"],))


@router.get("/r/{token}", response_class=HTMLResponse)
def invitation_landing(token: str):
    with gateway.connect() as cx:
        row = resolve_link(cx, token)
        if row:
            gateway.record_audit(cx, row["request_id"], "unverified-link-holder", "LINK_OPENED")
    if not row:
        return denied("This invitation is unavailable or has expired.", 404)
    # No patient name, birth date, request type, or expected recipient on this page.
    safe_token = escape(token, quote=True)
    options = "".join(f'<option value="{escape(key)}">{escape(identity[1])}</option>'
                      for key, identity in IDENTITIES.items())
    content = (
        "<h1>Secure document request</h1>"
        "<p>Verify your identity using the local synthetic eID simulator. "
        "Clinical request details will only be displayed after verification.</p>"
        f'<form method="post" action="/r/{safe_token}/verify">'
        '<label for="identity_key">Simulated eID identity</label>'
        f'<select id="identity_key" name="identity_key" required>{options}</select>'
        '<label for="pin">Mock eID verification code</label>'
        '<input type="password" id="pin" name="pin" maxlength="100" autocomplete="off" required>'
        '<button type="submit">Verify identity</button></form>'
        "<p class='note'>Local demonstration only: this is not real ID Austria. "
        "No PGK account or installation is required.</p>"
    )
    return document("Secure document request", content)


@router.post("/r/{token}/verify")
def verify_identity(token: str, identity_key: str = Form(...), pin: str = Form(...)):
    with gateway.connect() as cx:
        row = resolve_link(cx, token)
        if row is None:
            return denied("This invitation is unavailable or has expired.", 404)
        attempt = cx.execute("SELECT failed_count FROM identity_attempts WHERE request_id = ?",
                             (row["request_id"],)).fetchone()
        if attempt and attempt["failed_count"] >= MAX_FAILURES:
            gateway.record_audit(cx, row["request_id"], "unverified-link-holder", "IDENTITY_CHECKED",
                                 {"result": "denied", "reason": "attempt_limit"})
            return denied("This invitation is locked after too many failed checks.", 429)

        identity = IDENTITIES.get(identity_key)
        configured_pin = os.getenv(identity[2], "") if identity else ""
        # Both fixture credentials and the server-side secret MUST be configured.
        authenticated = bool(identity and configured_pin and pin and compare_digest(pin, configured_pin))
        if not authenticated:
            recorded_failure(cx, row, "unverified-link-holder", "invalid_mock_eid_credential", False)
            return denied()

        actual_subject_id, display_name, _ = identity
        expected_subject_id = EXPECTED_NAME_TO_SUBJECT.get(row["recipient_name"].strip().casefold())
        if not expected_subject_id or not compare_digest(actual_subject_id, expected_subject_id):
            recorded_failure(cx, row, actual_subject_id, "recipient_identity_mismatch", True)
            return denied()

        raw_session = secrets.token_urlsafe(32)
        session_hash = sha256(raw_session.encode("utf-8")).hexdigest()
        expiration = min(datetime.now(timezone.utc) + timedelta(minutes=SESSION_MINUTES),
                         datetime.fromisoformat(row["expires_at"]))
        cx.execute("""INSERT INTO identity_sessions
                      (session_hash, request_id, subject_id, expires_at, created_at)
                      VALUES (?, ?, ?, ?, ?)""",
                   (session_hash, row["request_id"], actual_subject_id,
                    expiration.isoformat(timespec="seconds"), gateway.now_iso()))
        gateway.record_audit(cx, row["request_id"], actual_subject_id, "IDENTITY_CHECKED", {
            "result": "success", "method": "synthetic-mock-eid", "subject_id": actual_subject_id
        })
    resp = RedirectResponse("/portal", status_code=303, headers=security_headers())
    resp.set_cookie(
        "pgk_session", raw_session,
        httponly=True, samesite="strict", secure=os.getenv("PGK_PUBLIC_BASE_URL", "").startswith("https://"),
        max_age=SESSION_MINUTES * 60, path="/",
    )
    return resp


def session_request(cx: sqlite3.Connection, request: Request) -> sqlite3.Row | None:
    cookie = request.cookies.get("pgk_session", "")
    if not cookie or len(cookie) > 256:
        return None
    session_hash = sha256(cookie.encode("utf-8")).hexdigest()
    row = cx.execute("""SELECT r.*, s.subject_id, s.expires_at AS session_expires_at
                        FROM identity_sessions s
                        JOIN requests r ON r.request_id = s.request_id
                        WHERE s.session_hash = ?""", (session_hash,)).fetchone()
    if not row or datetime.fromisoformat(row["session_expires_at"]) <= datetime.now(timezone.utc):
        return None
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return row


@router.get("/portal", response_class=HTMLResponse)
def portal(request: Request):
    with gateway.connect() as cx:
        row = session_request(cx, request)
    if row is None:
        return denied("You must verify your identity before accessing this page.")
    # Patient DOB is known from the supplied scenario. Later stages should load
    # patient metadata from Patient resource, NOT embed it here.
    kind = "Blood clotting laboratory result" if row["document_kind"] == "lab" else "Rehabilitation discharge report"
    body = (
        "<h1>Identity verified</h1><p class='status'>Simulated eID check passed.</p>"
        "<p><strong>Patient:</strong> Maria Beispiel (12 March 1961)</p>"
        "<p><strong>Requested document:</strong> " + escape(kind) + "</p>"
        "<p><strong>Recipient:</strong> " + escape(row["recipient_name"]) + "</p>"
        "<p>Document submission and FHIR filing will be implemented in Step 4.</p>"
        "<p class='note'>Synthetic medical data only.</p>"
    )
    return document("Verified portal", body)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303, headers=security_headers())
    resp.delete_cookie("pgk_session", path="/")
    return resp
