"""Offline simulated eID issuer for synthetic hackathon people.

Administrative enrollment is independent of the public recipient portal: a person
cannot obtain a credential just by claiming to be the intended recipient. This is
NOT a real identity verification system. Never use with real patient data.
"""
from __future__ import annotations

from hashlib import pbkdf2_hmac
from hmac import compare_digest
import os
import secrets
import sqlite3
import uuid

from .documents import normalize_name

ITERATIONS = 160_000


def init_issuer_db(cx: sqlite3.Connection) -> None:
    cx.execute("""CREATE TABLE IF NOT EXISTS mock_issuer_identities (
      subject_id TEXT PRIMARY KEY,
      display_name TEXT NOT NULL,
      name_key TEXT NOT NULL UNIQUE,
      pin_salt TEXT NOT NULL,
      pin_digest TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    )""")


def register_identity(cx: sqlite3.Connection, display_name: str, *, pin: str | None = None) -> tuple[str, str]:
    """Issuer-admin operation; do not expose it on the public web app."""
    name = " ".join(display_name.split())
    if len(name) < 3 or len(name) > 150:
        raise ValueError("Identity name must be 3-150 characters")
    from .identity import EXPECTED_NAME_TO_SUBJECT
    name_key = normalize_name(name)
    if name_key in EXPECTED_NAME_TO_SUBJECT:
        raise ValueError("This name is reserved by a bundled demo identity")
    if cx.execute("SELECT 1 FROM mock_issuer_identities WHERE name_key=?", (name_key,)).fetchone():
        raise ValueError("This synthetic identity is already provisioned")
    code = pin if pin is not None else secrets.token_urlsafe(10)
    if len(code) < 8 or len(code) > 100:
        raise ValueError("Mock eID credential must be 8-100 characters")
    salt = os.urandom(16)
    digest = pbkdf2_hmac("sha256", code.encode(), salt, ITERATIONS).hex()
    subject = "eid-demo-" + uuid.uuid4().hex
    cx.execute("""INSERT INTO mock_issuer_identities
        (subject_id,display_name,name_key,pin_salt,pin_digest,created_at)
        VALUES (?,?,?,?,?,datetime('now'))""",
        (subject, name, name_key, salt.hex(), digest))
    return subject, code


def expected_subject(cx: sqlite3.Connection, name: str) -> str | None:
    from .identity import EXPECTED_NAME_TO_SUBJECT
    name_key = normalize_name(name)
    static = EXPECTED_NAME_TO_SUBJECT.get(name_key)
    if static:
        return static
    row = cx.execute("SELECT subject_id FROM mock_issuer_identities WHERE name_key=? AND enabled=1", (name_key,)).fetchone()
    return row[0] if row else None


def verify_issued_credential(cx: sqlite3.Connection, subject: str, code: str) -> tuple[str, str] | None:
    if not subject.startswith("eid-demo-") or len(subject) > 100 or not code or len(code) > 100:
        return None
    row = cx.execute("""SELECT subject_id,display_name,pin_salt,pin_digest
                        FROM mock_issuer_identities WHERE subject_id=? AND enabled=1""", (subject,)).fetchone()
    if row is None:
        return None
    digest = pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(row["pin_salt"]), ITERATIONS)
    if not compare_digest(digest.hex(), row["pin_digest"]):
        return None
    return row["subject_id"], row["display_name"]
