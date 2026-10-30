"""Step 4: full browser submission / M3 / synthetic Markdown transformation tests."""
from __future__ import annotations

from urllib.parse import urlparse
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import main as gateway
from app.documents import InvalidDocument, parse_lab_rows, parse_patient_claim, parse_submission
from matrix_bot import send_pending_notifications

SECRET = "unit-test-secret"
ROOM = "!testroom:klinikum.example"
SENDER = "@lena.hofer:klinikum.example"


def lab(name="Maria Beispiel", born="12 March 1961", value="1.0", extra=""):
    return (f"# Lab result\nPatient: {name}, born {born}\nSample taken: 22 October 2026\n\n"
            "| Test | Result | Unit | Reference range | LOINC code |\n"
            "|---|---|---|---|---|\n"
            f"| INR (prothrombin time) | {value} | | 0.8 to 1.2 | 6301-6 |\n"
            "| aPTT | 31 | s | 25 to 37 | 14979-9 |\n"
            f"{extra}\nValidated by: Dr. Eva Brandl\n")


def rehab():
    return "# Rehabilitation discharge report\nPatient: Maria Beispiel, born 12 March 1961\n## Course\nPatient recovering after surgery and completing physical therapy.\n"


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setenv("PGK_DB_PATH", str(tmp_path / "step4.sqlite"))
    monkeypatch.setenv("PGK_BOT_SECRET", SECRET)
    monkeypatch.setenv("PGK_ALLOWED_ROOM", ROOM)
    monkeypatch.setenv("PGK_ALLOWED_SENDER", SENDER)
    monkeypatch.setenv("PGK_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("PGK_MOCK_EID_EVA_PIN", "test-eva")
    monkeypatch.setenv("PGK_MOCK_EID_STEFAN_PIN", "test-stefan")
    monkeypatch.setenv("PGK_MOCK_EID_COLLEAGUE_PIN", "test-colleague")
    monkeypatch.setenv("PGK_MOCK_EID_OUTSIDER_PIN", "test-outsider")
    links = []
    monkeypatch.setattr(gateway, "deliver_email", lambda addr, url: links.append(url))
    with TestClient(gateway.app) as api:
        yield api, links


def create_verified(demo, *, kind="lab", event="$doc"):
    api, links = demo
    payload = {
        "matrix_event_id": event, "matrix_sender": SENDER,
        "matrix_room_id": ROOM, "document_kind": kind,
        "recipient_name": "Dr. Eva Brandl" if kind == "lab" else "Stefan Kern",
        "recipient_contact": "eva.brandl@labor-kanal.example" if kind == "lab" else "+43 660 000 0101",
    }
    r = api.post("/internal/requests", headers={"X-Bot-Secret": SECRET}, json=payload)
    assert r.status_code == 201, r.text
    req_id = r.json()["request_id"]
    if kind == "lab":
        link = urlparse(links[-1]).path
    else:
        inbox = api.get("/internal/dev/sms", headers={"X-Bot-Secret": SECRET}).json()["messages"]
        link = urlparse(inbox[0]["message"].split()[-1]).path
    v = api.post(link + "/verify", data={"identity_key": "eva" if kind == "lab" else "stefan",
                                         "pin": "test-eva" if kind == "lab" else "test-stefan"},
                 follow_redirects=False)
    assert v.status_code == 303, v.text
    page = api.get("/portal")
    assert page.status_code == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    return req_id, csrf


def audit(api, req_id):
    return api.get("/internal/requests/" + req_id, headers={"X-Bot-Secret": SECRET}).json()["audit"]


def submit(api, csrf, md, *, upload=True):
    if upload:
        return api.post("/portal/submit", data={"csrf": csrf},
                        files={"md_file": ("result.md", md.encode("utf-8"), "text/markdown")},
                        follow_redirects=False)
    return api.post("/portal/submit", data={"csrf": csrf, "markdown": md}, follow_redirects=False)


def test_m3_wrong_patient_caught_audited_queued_not_stored(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    rejected = submit(api, csrf, lab(name="Max Beispiel", born="1 January 1960", value="2.6"))
    assert rejected.status_code == 422
    assert "Patient mismatch" in rejected.text
    assert api.get("/internal/submissions/" + req_id, headers={"X-Bot-Secret": SECRET}).status_code == 404
    events = audit(api, req_id)
    assert events[-1]["what"] == "MISDELIVERY_CAUGHT"
    assert events[-1]["details"]["reason"] == "wrong_patient"
    assert "ANSWER_SENT" not in [e["what"] for e in events]
    notes = api.get("/internal/notifications", headers={"X-Bot-Secret": SECRET}).json()["notifications"]
    assert len(notes) == 1 and notes[0]["room_id"] == ROOM
    assert "DIFFERENT PATIENT" in notes[0]["body"]
    assert "Max Beispiel" not in notes[0]["body"]


def test_m3_cannot_fake_name_with_wrong_birth_date(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    assert submit(api, csrf, lab(name="Maria Beispiel", born="1 January 1960")).status_code == 422
    assert audit(api, req_id)[-1]["what"] == "MISDELIVERY_CAUGHT"


def test_lab_success_creates_structured_submission_not_yet_fhir(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    sent = submit(api, csrf, lab(value="1.1"))
    assert sent.status_code == 303
    assert sent.headers["location"] == "/portal/submitted"
    confirmation = api.get("/portal/submitted")
    assert confirmation.status_code == 200
    assert "not</strong> yet been filed" in confirmation.text
    data = api.get("/internal/submissions/" + req_id, headers={"X-Bot-Secret": SECRET}).json()
    assert data["patient_ref"] == "Patient/maria-beispiel"
    assert data["parsed"]["kind"] == "lab"
    assert len(data["parsed"]["observations"]) == 2
    assert data["parsed"]["observations"][0]["loinc"] == "6301-6"
    assert data["parsed"]["observations"][0]["value"] == pytest.approx(1.1)
    assert audit(api, req_id)[-1]["what"] == "ANSWER_SENT"
    assert submit(api, csrf, lab()).status_code == 409
    assert api.get("/internal/notifications", headers={"X-Bot-Secret": SECRET}).json()["notifications"] == []


def test_rehab_text_accepted(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, kind="rehab", event="$rehab")
    assert submit(api, csrf, rehab(), upload=False).status_code == 303
    data = api.get("/internal/submissions/" + req_id, headers={"X-Bot-Secret": SECRET}).json()
    assert data["parsed"]["kind"] == "rehab"
    assert data["parsed"]["body_text"].startswith("# Rehabilitation")


def test_no_session_cannot_submit_or_view(demo):
    api, _ = demo
    assert api.get("/portal/submitted").status_code == 403
    assert api.post("/portal/submit", data={"csrf": "abc", "markdown": lab()}).status_code == 403


def test_bad_csrf_rejected(demo):
    api, _ = demo
    create_verified(demo)
    assert submit(api, "x" * 64, lab()).status_code == 403


def test_bad_format_fails_closed_but_can_retry(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    assert submit(api, csrf, "Patient: Maria Beispiel, born 12 March 1961\nNothing else").status_code == 422
    assert audit(api, req_id)[-1]["what"] == "ANSWER_REJECTED"
    assert submit(api, csrf, lab()).status_code == 303


def test_bad_file_extension_too_large_and_nul(demo):
    api, _ = demo
    _, csrf = create_verified(demo)
    assert api.post("/portal/submit", data={"csrf": csrf},
                    files={"md_file": ("attack.exe", b"something", "application/octet-stream")}).status_code == 415
    assert submit(api, csrf, lab() + "a" * 65536).status_code == 413
    assert submit(api, csrf, lab() + "\x00").status_code == 422


def test_parser_patient_line_date_variants_and_variable_rows():
    assert parse_patient_claim("Patient: Maria Beispiel, born 12 March 1961").birth_date == "1961-03-12"
    assert parse_patient_claim("Patient: Maria Beispiel\nDOB: 1961-03-12").birth_date == "1961-03-12"
    assert parse_patient_claim("Patient: Maria Beispiel\nDOB: 12.03.1961").birth_date == "1961-03-12"
    claim, data = parse_submission(lab(value="1,3", extra="| Novel X | 3.4 | mg/L | 1 to 5 | 99999-1 |"), "lab")
    assert claim.name == "Maria Beispiel"
    assert len(data["observations"]) == 3
    assert data["observations"][0]["value"] == pytest.approx(1.3)


def test_parser_rejects_incomplete_patient_or_invalid_loinc():
    with pytest.raises(InvalidDocument):
        parse_patient_claim("# Test\nPatient: Maria Beispiel")
    with pytest.raises(InvalidDocument):
        parse_patient_claim("Patient: Maria Beispiel, born 12 March 1961\nPatient: Max Beispiel, born 1 January 1960")
    with pytest.raises(InvalidDocument):
        parse_lab_rows(lab().replace("6301-6", "NOPE"))


def test_notification_endpoints_protected_and_ack(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    submit(api, csrf, lab(name="Max Beispiel", born="1 January 1960"))
    assert api.get("/internal/notifications").status_code == 401
    notices = api.get("/internal/notifications", headers={"X-Bot-Secret": SECRET}).json()["notifications"]
    msg_id = notices[0]["notification_id"]
    assert api.post("/internal/notifications/" + msg_id + "/ack").status_code == 401
    assert api.post("/internal/notifications/" + msg_id + "/ack", headers={"X-Bot-Secret": SECRET}).status_code == 200
    assert api.get("/internal/notifications", headers={"X-Bot-Secret": SECRET}).json()["notifications"] == []
    assert api.post("/internal/notifications/not-exist/ack", headers={"X-Bot-Secret": SECRET}).status_code == 404


def test_bot_notification_delivery_uses_stable_txn_id(monkeypatch):
    calls = []
    def fake_api(base, method, path, payload=None, token=None, bot_secret=None):
        calls.append((method, path, payload, token, bot_secret))
        if method == "GET":
            return {"notifications": [{"notification_id": "abc123", "request_id": "req123", "room_id": ROOM,
                                        "body": "WARNING: wrong patient"}]}
        return {"ok": True}
    monkeypatch.setattr("matrix_bot.request_json", fake_api)
    send_pending_notifications("test-matrix-access", "test-gateway-secret")
    assert len(calls) == 3
    assert calls[1][0] == "PUT"
    assert calls[1][1].endswith("/abc123")
    assert calls[1][2]["body"].startswith("WARNING")
    assert calls[2][1].endswith("/abc123/ack")
