"""Step 4: authenticated Markdown submissions + patient mismatch detection (M3).

No FHIR resources are created in this step. Only synthetic data permitted.
"""
from __future__ import annotations

from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from html import escape
import json
import os
import secrets
import sqlite3
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from . import main as gateway
from .documents import InvalidDocument, expected_patient, normalize_name, parse_patient_claim, parse_submission
from .identity import denied, document, security_headers, session_request

router = APIRouter()
MAX_MARKDOWN_BYTES = 64 * 1024


def init_submission_db(cx: sqlite3.Connection) -> None:
    cx.executescript("""
        CREATE TABLE IF NOT EXISTS submissions (
            submission_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE REFERENCES requests(request_id),
            sender_subject TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            document_kind TEXT NOT NULL,
            markdown TEXT NOT NULL,
            parsed_json TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS matrix_notifications (
            notification_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES requests(request_id),
            room_id TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            sent_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_matrix_notifications_status
            ON matrix_notifications(status);
    """)


def csrf_for_cookie(raw_cookie: str) -> str:
    key = os.getenv("PGK_BOT_SECRET", "")
    if not key:
        raise RuntimeError("PGK_BOT_SECRET is required")
    return hmac_new(key.encode("utf-8"), ("pgk-upload-v1:" + raw_cookie).encode(), "sha256").hexdigest()


def record_notification(cx: sqlite3.Connection, row: sqlite3.Row, message: str) -> None:
    cx.execute(
        """INSERT INTO matrix_notifications
        (notification_id,request_id,room_id,body,status,created_at) VALUES (?,?,?,?,?,?)""",
        (uuid.uuid4().hex, row["request_id"], row["matrix_room_id"], message, "pending", gateway.now_iso()),
    )


def submission_form(row: sqlite3.Row, cookie: str, error: str = "") -> str:
    patient = expected_patient()
    kind_label = "Blood clotting laboratory result" if row["document_kind"] == "lab" else "Rehabilitation discharge report"
    error_html = f'<p role="alert" style="color:#a12323">{escape(error)}</p>' if error else ""
    token = csrf_for_cookie(cookie)
    return (
        '<h1>Identity verified</h1><p class="status">Synthetic eID check passed.</p>'
        f'<p><strong>Patient:</strong> {escape(patient["name"])} ({escape(patient["birth_date"])})</p>'
        f'<p><strong>Requested document:</strong> {escape(kind_label)}</p>'
        f'<p><strong>Recipient:</strong> {escape(row["recipient_name"])}</p>'
        '<p>Upload the supplied Markdown document or paste its contents below. '
        'The submission is checked against the requested patient before it is accepted.</p>'
        + error_html +
        '<form method="post" action="/portal/submit" enctype="multipart/form-data">'
        f'<input type="hidden" name="csrf" value="{escape(token)}">'
        '<label for="md_file">Markdown file (.md or .txt)</label>'
        '<input id="md_file" name="md_file" type="file" accept=".md,.txt,text/markdown,text/plain">'
        '<label for="markdown">Or paste Markdown</label>'
        '<textarea id="markdown" name="markdown" rows="10" '
        'style="width:100%;box-sizing:border-box;resize:vertical"></textarea>'
        '<button type="submit">Submit document</button></form>'
        '<p class="note">Synthetic data only. FHIR filing will be added in Step 5.</p>'
    )


@router.post("/portal/submit")
async def submit_markdown(request: Request, markdown: str = Form(default=""),
                          csrf: str = Form(...), md_file: UploadFile | None = File(default=None)):
    with gateway.connect() as cx:
        row = session_request(cx, request)
        if row is None:
            return denied("Verify your identity before submitting a document")
        cookie = request.cookies.get("pgk_session", "")
        if not compare_digest(csrf, csrf_for_cookie(cookie)):
            return denied("Invalid form token; please reload the page and retry")
        existing = cx.execute("SELECT submission_id FROM submissions WHERE request_id=?",
                              (row["request_id"],)).fetchone()
        if existing is not None:
            return document("Already submitted", "<h1>Request already answered</h1>", 409)

        if md_file is not None and md_file.filename:
            filename = md_file.filename.lower()
            if not filename.endswith((".md", ".txt")):
                return document("Unsupported file", "<h1>Upload .md or .txt only</h1>", 415)
            raw = await md_file.read(MAX_MARKDOWN_BYTES + 1)
            if len(raw) > MAX_MARKDOWN_BYTES:
                return document("Document too large", "<h1>64 KiB limit exceeded</h1>", 413)
            try:
                content = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return document("Invalid encoding", "<h1>Use UTF-8 text</h1>", 422)
        else:
            content = markdown
            if len(content.encode("utf-8")) > MAX_MARKDOWN_BYTES:
                return document("Document too large", "<h1>64 KiB limit exceeded</h1>", 413)
        if not content.strip() or "\x00" in content:
            return document("Invalid document", "<h1>Empty or invalid document</h1>", 422)

        try:
            claim = parse_patient_claim(content)
        except InvalidDocument as exc:
            gateway.record_audit(cx, row["request_id"], row["subject_id"], "ANSWER_REJECTED",
                                 {"reason": "unreadable_patient_claim"})
            return document("Cannot verify patient", "<h1>Document rejected</h1><p>" + escape(str(exc)) + "</p>", 422)
        patient = expected_patient()
        # Check patient BEFORE accepting or even performing FHIR-oriented parsing.
        if (normalize_name(claim.name) != normalize_name(patient["name"])
                or claim.birth_date != patient["birth_date"]
                or row["patient_ref"] != patient["reference"]):
            gateway.record_audit(cx, row["request_id"], row["subject_id"], "MISDELIVERY_CAUGHT", {
                "reason": "wrong_patient", "action": "rejected_before_fhir",
                "claimed_patient_name": claim.name, "claimed_birth_date": claim.birth_date,
                "expected_patient_ref": row["patient_ref"],
            })
            record_notification(
                cx, row, f'WARNING: Request {row["request_id"]} received a document for a DIFFERENT PATIENT. '
                         'The document was rejected and NOT filed. Please request a corrected document.'
            )
            return document("Wrong patient", "<h1>Patient mismatch</h1><p>This document is not for the "
                            "patient in the original request. It was rejected; the doctor will be notified in Matrix.</p>", 422)

        try:
            _, parsed = parse_submission(content, row["document_kind"])
        except InvalidDocument as exc:
            gateway.record_audit(cx, row["request_id"], row["subject_id"], "ANSWER_REJECTED",
                                 {"reason": "invalid_document_format"})
            return document("Invalid document", "<h1>Document rejected</h1><p>" + escape(str(exc)) + "</p>", 422)

        cx.execute(
            """INSERT INTO submissions
            (submission_id, request_id, sender_subject, patient_ref, document_kind,
             markdown, parsed_json, sha256, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (uuid.uuid4().hex, row["request_id"], row["subject_id"], patient["reference"],
             row["document_kind"], content, json.dumps(parsed, ensure_ascii=False),
             sha256(content.encode()).hexdigest(), gateway.now_iso()),
        )
        gateway.record_audit(cx, row["request_id"], row["subject_id"], "ANSWER_SENT", {
            "result": "accepted", "format": "markdown", "sha256": sha256(content.encode()).hexdigest(),
            "record_count": len(parsed.get("observations", [])) if row["document_kind"] == "lab" else None,
        })
    return RedirectResponse("/portal/submitted", status_code=303, headers=security_headers())


@router.get("/portal/submitted")
def submitted_page(request: Request):
    with gateway.connect() as cx:
        row = session_request(cx, request)
        if row is None:
            return denied()
        accepted = cx.execute("SELECT submission_id FROM submissions WHERE request_id=?", (row["request_id"],)).fetchone()
        if accepted is None:
            return RedirectResponse("/portal", status_code=303)
    return document("Answer received", "<h1>Document received</h1><p>Your Markdown answer was accepted "
                    "and queued for the next step: FHIR R4 mapping and storage.</p>"
                    "<p>It has <strong>not</strong> yet been filed on a FHIR server.</p>")


@router.get("/internal/notifications", dependencies=[gateway.Depends(gateway.require_bot)])
def list_notifications():
    """Notifications pending for Matrix; only bot can read them."""
    with gateway.connect() as cx:
        data = cx.execute("SELECT notification_id,request_id,room_id,body FROM matrix_notifications "
                          "WHERE status='pending' ORDER BY rowid ASC LIMIT 20").fetchall()
    return {"notifications": [dict(e) for e in data]}


@router.post("/internal/notifications/{notification_id}/ack", dependencies=[gateway.Depends(gateway.require_bot)])
def ack_notification(notification_id: str):
    with gateway.connect() as cx:
        result = cx.execute("UPDATE matrix_notifications SET status='sent',sent_at=? "
                            "WHERE notification_id=? AND status='pending'", (gateway.now_iso(), notification_id))
        if result.rowcount == 0:
            found = cx.execute("SELECT status FROM matrix_notifications WHERE notification_id=?", (notification_id,)).fetchone()
            if found is None:
                raise gateway.HTTPException(404, "Notification not found")
    return {"ok": True}


@router.get("/internal/submissions/{request_id}", dependencies=[gateway.Depends(gateway.require_bot)])
def get_submission(request_id: str):
    """Internal-only debug/Step-5 bridge. Never print/store auth tokens or PINs."""
    with gateway.connect() as cx:
        record = cx.execute("SELECT submission_id,request_id,patient_ref,document_kind,parsed_json,sha256 "
                            "FROM submissions WHERE request_id=?", (request_id,)).fetchone()
    if record is None:
        raise gateway.HTTPException(404, "No accepted submission")
    return {**{k: record[k] for k in ("submission_id", "request_id", "patient_ref", "document_kind", "sha256")},
            "parsed": json.loads(record["parsed_json"])}
