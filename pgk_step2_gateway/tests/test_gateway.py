from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main as gateway
from matrix_bot import parse_command

SECRET = "unit-test-secret"
ROOM = "!testroom:klinikum.example"
SENDER = "@lena.hofer:klinikum.example"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PGK_DB_PATH", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("PGK_BOT_SECRET", SECRET)
    monkeypatch.setenv("PGK_ALLOWED_ROOM", ROOM)
    monkeypatch.setenv("PGK_ALLOWED_SENDER", SENDER)
    monkeypatch.setenv("PGK_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    with TestClient(gateway.app) as cli:
        yield cli


def body(event_id="$event1", kind="lab", contact="eva.brandl@labor-kanal.example"):
    return {
        "matrix_event_id": event_id,
        "matrix_sender": SENDER,
        "matrix_room_id": ROOM,
        "document_kind": kind,
        "recipient_name": "Dr. Eva Brandl" if kind == "lab" else "Stefan Kern",
        "recipient_contact": contact,
    }


def post(client, payload):
    return client.post("/internal/requests", json=payload, headers={"X-Bot-Secret": SECRET})


def test_email_request_and_private_invitation(client, monkeypatch):
    messages = []
    def capture(to, url):
        messages.append((to, url))
    monkeypatch.setattr(gateway, "deliver_email", capture)
    response = post(client, body())
    assert response.status_code == 201
    assert response.json()["delivery_status"] == "sent"
    assert response.json()["created"] is True
    assert "token" not in response.text
    assert len(messages) == 1
    invite = client.get(messages[0][1].replace("http://127.0.0.1:8000", ""))
    assert invite.status_code == 200
    assert "Maria" not in invite.text
    assert "blood test" not in invite.text.lower()
    assert "rehab" not in invite.text.lower()
    stored = client.get("/internal/requests/" + response.json()["request_id"], headers={"X-Bot-Secret": SECRET})
    assert [e["what"] for e in stored.json()["audit"]] == ["REQUEST_CREATED", "REQUEST_SENT", "LINK_OPENED"]


def test_idempotent_matrix_replay_does_not_resend(client, monkeypatch):
    sent = []
    monkeypatch.setattr(gateway, "deliver_email", lambda to, url: sent.append(url))
    first = post(client, body())
    again = post(client, body())
    assert first.json()["request_id"] == again.json()["request_id"]
    assert again.status_code == 200
    assert again.json()["created"] is False
    assert len(sent) == 1


def test_reject_unauthorized_sender_and_secret(client):
    assert client.post("/internal/requests", json=body()).status_code == 401
    incorrect = body()
    incorrect["matrix_sender"] = "@outsider:klinikum.example"
    assert post(client, incorrect).status_code == 403
    incorrect = body()
    incorrect["matrix_room_id"] = "!other:klinikum.example"
    assert post(client, incorrect).status_code == 403


def test_rehab_sms_simulator_is_private(client):
    r = post(client, body(kind="rehab", contact="+43 660 000 0101"))
    assert r.json()["delivery_channel"] == "sms"
    assert client.get("/internal/dev/sms").status_code == 401
    sms = client.get("/internal/dev/sms", headers={"X-Bot-Secret": SECRET}).json()["messages"][0]["message"]
    assert "Maria" not in sms and "rehab" not in sms.lower()
    assert "/r/" in sms


def test_email_delivery_failure_is_recorded(client, monkeypatch):
    def fail(*args):
        raise ConnectionRefusedError("Mailpit offline")
    monkeypatch.setattr(gateway, "deliver_email", fail)
    result = post(client, body())
    assert result.json()["delivery_status"] == "failed"
    details = client.get("/internal/requests/" + result.json()["request_id"], headers={"X-Bot-Secret": SECRET}).json()
    assert details["audit"][-1]["what"] == "DELIVERY_FAILED"


def test_command_parsing_supports_previous_syntax():
    assert parse_command("!request lab eva.brandl@labor-kanal.example")["recipient_name"] == "Dr. Eva Brandl"
    assert parse_command('!request rehab "Stefan Kern" "+43 660 000 0101"')["recipient_contact"] == "+43 660 000 0101"
    assert parse_command("Hello") is None
    with pytest.raises(ValueError):
        parse_command("!request lab")


def test_wrong_address_creates_invitation_but_no_patient_leak(client, monkeypatch):
    """M1 will require an identity block in Step 3; Step 2 must at least hide data."""
    captured = []
    monkeypatch.setattr(gateway, "deliver_email", lambda to, url: captured.append((to, url)))
    r = post(client, body(event_id="$wrong-address", contact="eva.brandl@labor-kanaI.example"))
    assert r.status_code == 201
    assert captured[0][0] == "eva.brandl@labor-kanaI.example"
    link = captured[0][1].removeprefix("http://127.0.0.1:8000")
    text = client.get(link).text
    assert "Maria" not in text and "Beispiel" not in text
    assert "identity verification is not implemented" in text.lower()


def test_expired_or_unknown_link_is_rejected(client):
    r = client.get("/r/nonexistent123")
    assert r.status_code == 404
    assert "Maria" not in r.text
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_real_email_template_has_no_clinical_details(monkeypatch):
    emails = []
    class FakeSMTP:
        def __init__(self, host, port, timeout):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def send_message(self, message):
            emails.append(message)

    monkeypatch.setattr(gateway.smtplib, "SMTP", FakeSMTP)
    gateway.deliver_email("eva.brandl@labor-kanal.example", "http://127.0.0.1:8000/r/SECURETOKEN")
    assert len(emails) == 1
    body = str(emails[0])
    assert "SECURETOKEN" in body
    assert "Maria" not in body
    assert "1961" not in body
    assert "blood" not in body.lower()
    assert "lab result" not in body.lower()
