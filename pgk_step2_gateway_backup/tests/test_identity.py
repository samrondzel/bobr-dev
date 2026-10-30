"""Step 3: M1 and M2 require real *server-side* checks of mock identity fixtures."""
from __future__ import annotations

from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from app import main as gateway

SECRET = "unit-test-secret"
ROOM = "!testroom:klinikum.example"
SENDER = "@lena.hofer:klinikum.example"
PINS = {
    "eva": "fixture-eva-0912",
    "stefan": "fixture-stefan-1144",
    "colleague": "fixture-colleague-1749",
    "outsider": "fixture-outsider-2660",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PGK_DB_PATH", str(tmp_path / "step3.sqlite"))
    monkeypatch.setenv("PGK_BOT_SECRET", SECRET)
    monkeypatch.setenv("PGK_ALLOWED_ROOM", ROOM)
    monkeypatch.setenv("PGK_ALLOWED_SENDER", SENDER)
    monkeypatch.setenv("PGK_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    for key, value in PINS.items():
        monkeypatch.setenv(f"PGK_MOCK_EID_{key.upper()}_PIN", value)
    links = []
    monkeypatch.setattr(gateway, "deliver_email", lambda address, url: links.append((address, url)))
    with TestClient(gateway.app) as api:
        yield api, links


def make_email_request(client, links, event_id, email="eva.brandl@labor-kanal.example", name="Dr. Eva Brandl"):
    r = client.post("/internal/requests", headers={"X-Bot-Secret": SECRET}, json={
        "matrix_event_id": event_id,
        "matrix_sender": SENDER,
        "matrix_room_id": ROOM,
        "document_kind": "lab",
        "recipient_name": name,
        "recipient_contact": email,
    })
    assert r.status_code == 201, r.text
    assert r.json()["delivery_status"] == "sent"
    return r.json()["request_id"], urlparse(links[-1][1]).path


def audit(client, request_id):
    r = client.get("/internal/requests/" + request_id, headers={"X-Bot-Secret": SECRET})
    assert r.status_code == 200
    return r.json()["audit"]


def verify(client, link, person, pin=None):
    return client.post(link + "/verify", data={"identity_key": person, "pin": pin or PINS[person]},
                       follow_redirects=False)


def test_m1_wrong_address_outsider_blocked_and_logged(client):
    api, links = client
    req_id, link = make_email_request(api, links, "$m1", "eva.brandl@labor-kanaI.example")
    assert "kanaI" in links[0][0]
    landing = api.get(link)
    assert landing.status_code == 200
    for sensitive in ("Maria", "1961", "Blood clotting", "Rehabilitation"):
        assert sensitive not in landing.text
    assert verify(api, link, "outsider").status_code == 403
    assert "Maria" not in api.get("/portal").text
    events = audit(api, req_id)
    assert [e["what"] for e in events][-2:] == ["IDENTITY_CHECKED", "MISDELIVERY_CAUGHT"]
    assert events[-1]["details"]["action"] == "blocked_before_disclosure"


def test_m2_forwarded_to_colleague_is_blocked(client):
    api, links = client
    req_id, link = make_email_request(api, links, "$m2")
    assert verify(api, link, "colleague").status_code == 403
    assert api.get("/portal").status_code == 403
    events = audit(api, req_id)
    assert any(e["what"] == "MISDELIVERY_CAUGHT" and e["who"] == "eid-demo-colleague" for e in events)
    assert not any(e["what"] in ("ANSWER_SENT", "ANSWER_FILED") for e in events)


def test_expected_person_receives_scoped_session_and_restricted_portal(client):
    api, links = client
    req_id, link = make_email_request(api, links, "$success")
    assert api.get("/portal").status_code == 403
    accepted = verify(api, link, "eva")
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/portal"
    cookie = accepted.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    page = api.get("/portal")
    assert page.status_code == 200
    assert "Maria Beispiel" in page.text
    assert "Blood clotting" in page.text
    events = audit(api, req_id)
    assert events[-1]["what"] == "IDENTITY_CHECKED"
    assert events[-1]["details"]["result"] == "success"
    assert all("pin" not in str(e).lower() for e in events)


def test_bad_pin_cannot_impersonate_eva(client):
    api, links = client
    req_id, link = make_email_request(api, links, "$badpin")
    assert verify(api, link, "eva", "not-evas-pin").status_code == 403
    assert api.get("/portal").status_code == 403
    events = audit(api, req_id)
    assert events[-1]["what"] == "IDENTITY_CHECKED"
    assert events[-1]["details"]["reason"] == "invalid_mock_eid_credential"


def test_failed_attempt_limit(client):
    api, links = client
    _, link = make_email_request(api, links, "$lock")
    for _ in range(5):
        assert verify(api, link, "outsider").status_code == 403
    assert verify(api, link, "eva").status_code == 429


def test_unknown_expected_recipient_fails_closed(client):
    api, links = client
    req_id, link = make_email_request(api, links, "$unknown", name="Different Person")
    assert verify(api, link, "eva").status_code == 403
    assert audit(api, req_id)[-1]["what"] == "MISDELIVERY_CAUGHT"


def test_old_session_cannot_open_other_request(client):
    api, links = client
    _, link1 = make_email_request(api, links, "$evt-a")
    assert verify(api, link1, "eva").status_code == 303
    _, link2 = make_email_request(api, links, "$evt-b")
    # A previously verified browser may still access its own portal but cannot
    # bypass a new invitation's identity check (which never has patient data).
    landing = api.get(link2)
    assert "Maria" not in landing.text
    assert "blood" not in landing.text.lower()
    assert verify(api, link2, "colleague").status_code == 403


def test_rehab_works_with_stefan(client):
    api, _ = client
    created = api.post("/internal/requests", headers={"X-Bot-Secret": SECRET}, json={
        "matrix_event_id": "$rehab", "matrix_sender": SENDER, "matrix_room_id": ROOM,
        "document_kind": "rehab", "recipient_name": "Stefan Kern",
        "recipient_contact": "+43 660 000 0101"
    })
    assert created.status_code == 201
    outbox = api.get("/internal/dev/sms", headers={"X-Bot-Secret": SECRET}).json()["messages"]
    link = urlparse(outbox[0]["message"].split()[-1]).path
    assert verify(api, link, "eva").status_code == 403
    assert verify(api, link, "stefan").status_code == 303
    assert "Rehabilitation discharge report" in api.get("/portal").text
