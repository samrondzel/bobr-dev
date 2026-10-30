"""Step 6: unseen recipients/docs, security regression and schema variation."""
from __future__ import annotations

from urllib.parse import urlparse
import json
import re

import pytest
from fastapi.testclient import TestClient

from app import main as gateway
from app.documents import InvalidDocument, parse_submission, parse_patient_claim, valid_loinc_code
from app.mock_issuer import register_identity, expected_subject

SECRET = 'step6-test-secret'
ROOM = '!step6:klinikum.example'
SENDER = '@lena.hofer:klinikum.example'


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv('PGK_DB_PATH', str(tmp_path / 'stage6.sqlite'))
    monkeypatch.setenv('PGK_BOT_SECRET', SECRET)
    monkeypatch.setenv('PGK_ALLOWED_ROOM', ROOM)
    monkeypatch.setenv('PGK_ALLOWED_SENDER', SENDER)
    monkeypatch.setenv('PGK_PUBLIC_BASE_URL', 'http://127.0.0.1:8000')
    monkeypatch.setenv('PGK_MOCK_EID_EVA_PIN', 'test-fixture-eva-pin')
    monkeypatch.setenv('PGK_MOCK_EID_OUTSIDER_PIN', 'test-fixture-outsider-pin')
    sent = []
    monkeypatch.setattr(gateway, 'deliver_email', lambda address, url: sent.append((address, url)))
    from app import fhir
    monkeypatch.setattr(fhir, 'post_transaction', lambda bundle: {
        'resourceType': 'Bundle', 'type': 'transaction-response',
        'entry': [{'response': {'status': '200 OK'}} for _ in bundle['entry']],
    })
    with TestClient(gateway.app) as api:
        yield api, sent


def request_lab(api, recipient, email, event_id='$test'):
    return api.post('/internal/requests', headers={'X-Bot-Secret': SECRET}, json={
        'matrix_event_id': event_id,
        'matrix_sender': SENDER, 'matrix_room_id': ROOM,
        'document_kind': 'lab', 'recipient_name': recipient,
        'recipient_contact': email,
    })


def test_new_issuer_recipient_completes_end_to_end_without_pgk_account(harness):
    api, sent = harness
    with gateway.connect() as cx:
        subject, pin = register_identity(cx, 'Dr. Nora Weiss')
        assert expected_subject(cx, '  DR.  NORA WEISS ') == subject
        stored = cx.execute('SELECT * FROM mock_issuer_identities WHERE subject_id=?', (subject,)).fetchone()
        assert pin not in repr(dict(stored))
    r = request_lab(api, 'Dr. Nora Weiss', 'nora@example.org', '$new-person')
    assert r.status_code == 201, r.text
    req_id = r.json()['request_id']
    assert sent[-1][0] == 'nora@example.org'
    link = urlparse(sent[-1][1]).path
    landing = api.get(link)
    assert landing.status_code == 200
    for sensitive in ('Maria', '1961', 'lab result', 'Blood clotting'):
        assert sensitive not in landing.text
    wrong = api.post(link + '/verify', data={
        'identity_key': 'issued', 'subject_id': subject, 'pin': 'wrong-credential'})
    assert wrong.status_code == 403
    wrong_user = api.post(link + '/verify', data={
        'identity_key': 'outsider', 'pin': 'test-fixture-outsider-pin'})
    assert wrong_user.status_code == 403
    ok = api.post(link + '/verify', data={
        'identity_key': 'issued', 'subject_id': subject, 'pin': pin}, follow_redirects=False)
    assert ok.status_code == 303
    portal = api.get('/portal')
    assert portal.status_code == 200
    csrf = re.search(r'name="csrf" value="([^"]+)"', portal.text).group(1)
    markdown = ("# New synthetic lab report\nPatient: Maria Beispiel\nDOB: 1961-03-12\n"
                "| Test | Result | Unit | LOINC code |\n| --- | ---: | --- | --- |\n"
                "| Hemoglobin | 14.2 | g/dL | 718-7 |\n")
    submitted = api.post('/portal/submit', data={'markdown': markdown, 'csrf': csrf}, follow_redirects=False)
    assert submitted.status_code == 303, submitted.text
    fhir = api.get('/internal/fhir/export/' + req_id, headers={'X-Bot-Secret': SECRET})
    assert fhir.status_code == 200
    bundle = fhir.json()
    obs = [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == 'Observation']
    assert len(obs) == 1
    assert obs[0]['code']['coding'][0] == {'system': 'http://loinc.org', 'code': '718-7'}
    assert obs[0]['valueQuantity']['value'] == 14.2
    audit = api.get('/internal/requests/'+req_id, headers={'X-Bot-Secret': SECRET}).json()['audit']
    assert {'IDENTITY_CHECKED', 'ANSWER_SENT', 'ANSWER_FILED'} <= {e['what'] for e in audit}


def test_new_recipient_cannot_be_impersonated_by_eva_or_other_issuer_credential(harness):
    api, sent = harness
    with gateway.connect() as cx:
        subject_a, pin_a = register_identity(cx, 'Dr. Nora Weiss')
        subject_b, pin_b = register_identity(cx, 'Dr. Paula Vogel')
    r = request_lab(api, 'Dr. Nora Weiss', 'nora@example.org', '$mixup')
    link = urlparse(sent[-1][1]).path
    mismatch = api.post(link + '/verify', data={
        'identity_key': 'issued', 'subject_id': subject_b, 'pin': pin_b})
    assert mismatch.status_code == 403
    assert api.get('/portal').status_code == 403
    audit = api.get('/internal/requests/'+r.json()['request_id'], headers={'X-Bot-Secret': SECRET}).json()['audit']
    assert any(x['what'] == 'MISDELIVERY_CAUGHT' for x in audit)


def test_issuer_identity_must_exist_before_request(harness):
    api, sent = harness
    assert request_lab(api, 'Unknown Person', 'other@example.org').status_code == 422
    assert not sent


def test_lab_and_rehab_contacts_are_independent_of_document_kind(harness):
    api, sent = harness
    r = api.post('/internal/requests', headers={'X-Bot-Secret': SECRET}, json={
        'matrix_event_id': '$rehab-email', 'matrix_sender': SENDER, 'matrix_room_id': ROOM,
        'document_kind': 'rehab', 'recipient_name': 'Stefan Kern',
        'recipient_contact': 'stefan@example.org'
    })
    assert r.status_code == 201
    assert r.json()['delivery_channel'] == 'email'
    assert sent[-1][0] == 'stefan@example.org'
    sms = request_lab(api, 'Dr. Eva Brandl', '+43 660 000 0199', '$lab-sms')
    assert sms.status_code == 201
    assert sms.json()['delivery_channel'] == 'sms'


def test_patient_name_and_dob_are_both_required_for_matching():
    with pytest.raises(InvalidDocument):
        parse_patient_claim('Patient: Maria Beispiel\n')
    with pytest.raises(InvalidDocument):
        parse_patient_claim('Patient: Maria Beispiel\nDOB: 1961-03-12\nDOB: 1960-01-01')
    with pytest.raises(InvalidDocument):
        parse_patient_claim('Patient: Maria Beispiel\nPatient: Max Beispiel\nDOB: 1961-03-12')


def test_reordered_columns_new_codes_and_multiple_tables():
    doc = ("Patient: Maria Beispiel\nDOB: 1961-03-12\n\n"
           "| LOINC | Units | Value | Test |\n|---|---|---|---|\n"
           "| 718-7 | g/dL | 14.1 | Hb |\n\n"
           "| Test | Result | Unit | LOINC code |\n|---|---|---|---|\n"
           "| Serum glucose | 95 | mg/dL | 2345-7 |\n")
    _, parsed = parse_submission(doc, 'lab')
    assert len(parsed['observations']) == 2
    assert [r['loinc'] for r in parsed['observations']] == ['718-7', '2345-7']


def test_comparator_and_fractional_values():
    doc = ('Patient: Maria Beispiel, born 12 March 1961\n'
           '| Test | Result | Unit | LOINC code |\n|---|---|---|---|\n'
           '| Hb | < 0,5 | g/dL | 718-7 |\n')
    _, result = parse_submission(doc, 'lab')
    assert result['observations'][0]['comparator'] == '<'
    assert result['observations'][0]['value'] == 0.5


def test_invalid_loinc_checkdigit_and_partial_tables_fail():
    assert valid_loinc_code('6301-6')
    assert not valid_loinc_code('6301-7')
    doc = ('Patient: Maria Beispiel, born 12 March 1961\n'
           '| Test | Result | Unit | LOINC code |\n|---|---|---|---|\n'
           '| INR | 1 | | 6301-7 |\n')
    with pytest.raises(InvalidDocument):
        parse_submission(doc, 'lab')
    partial = ('Patient: Maria Beispiel, born 12 March 1961\n'
               '| Test | Result | LOINC |\n|---|---|---|\n| INR | 1.0 | 6301-6 |\n')
    with pytest.raises(InvalidDocument):
        parse_submission(partial, 'lab')


def test_rehab_without_observations_while_new_lab_has_observations():
    _, rehab = parse_submission('Patient: Maria Beispiel\nDOB: 1961-03-12\nTherapy notes: improved strength.\n', 'rehab')
    assert rehab['kind'] == 'rehab'
    assert 'observations' not in rehab


def test_duplicate_issuer_name_is_rejected(harness):
    _, _ = harness
    with gateway.connect() as cx:
        register_identity(cx, 'Dr. Nora Weiss', pin='abc123456')
        with pytest.raises(ValueError):
            register_identity(cx, ' dr.   NORA weiss ', pin='abc123456')


def test_new_recipient_wrong_patient_rejected_before_fhir_and_notice_queued(harness):
    api, sent = harness
    with gateway.connect() as cx:
        subject, pin = register_identity(cx, 'Dr. Nora Weiss')
    created = request_lab(api, 'Dr. Nora Weiss', 'nora@example.org', '$wrong-patient')
    req_id = created.json()['request_id']
    link = urlparse(sent[-1][1]).path
    assert api.post(link + '/verify', data={
        'identity_key': 'issued', 'subject_id': subject, 'pin': pin}, follow_redirects=False).status_code == 303
    portal = api.get('/portal')
    csrf = re.search(r'name="csrf" value="([^"]+)"', portal.text).group(1)
    wrong_md = ('Patient: Max Beispiel\nDOB: 1960-01-01\n'
                '| Test | Result | Unit | LOINC code |\n|---|---|---|---|\n'
                '| Hemoglobin | 13.8 | g/dL | 718-7 |\n')
    rejected = api.post('/portal/submit', data={'markdown': wrong_md, 'csrf': csrf})
    assert rejected.status_code == 422
    assert api.get('/internal/fhir/status/' + req_id, headers={'X-Bot-Secret': SECRET}).status_code == 404
    audit = api.get('/internal/requests/'+req_id, headers={'X-Bot-Secret': SECRET}).json()['audit']
    assert any(e['what'] == 'MISDELIVERY_CAUGHT' and e['details']['reason'] == 'wrong_patient' for e in audit)
    assert not any(e['what'] == 'ANSWER_FILED' for e in audit)
    notifications = api.get('/internal/notifications', headers={'X-Bot-Secret': SECRET}).json()['notifications']
    assert any('DIFFERENT PATIENT' in n['body'] for n in notifications)


def test_bad_table_after_good_one_is_not_silently_ignored():
    markdown = ('Patient: Maria Beispiel\nDOB: 1961-03-12\n'
                '| Test | Result | Unit | LOINC code |\n|---|---|---|---|\n'
                '| Hb | 14.2 | g/dL | 718-7 |\n\n'
                '| Test | Result | LOINC |\n|---|---|---|\n'
                '| Glucose | 95 | 2345-7 |\n')
    with pytest.raises(InvalidDocument):
        parse_submission(markdown, 'lab')
