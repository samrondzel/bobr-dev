"""FHIR Step 5: tests use a fake FHIR transaction endpoint; no Docker required."""
import base64
import json
import pytest

from app import main as gateway
from app import fhir
from test_submissions import SECRET, ROOM, SENDER, create_verified, demo, lab, rehab, submit, audit


def entries_by_type(bundle, resource_type):
    return [e['resource'] for e in bundle['entry'] if e['resource']['resourceType'] == resource_type]


def export_bundle(api, req_id):
    r = api.get('/internal/fhir/export/' + req_id, headers={'X-Bot-Secret': SECRET})
    assert r.status_code == 200, r.text
    return r.json()


def filing_status(api, req_id):
    r = api.get('/internal/fhir/status/' + req_id, headers={'X-Bot-Secret': SECRET})
    assert r.status_code == 200
    return r.json()


def test_lab_fhir_transaction_and_references(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo)
    assert submit(api, csrf, lab(value='1.1')).status_code == 303
    bundle = export_bundle(api, req_id)
    assert bundle['type'] == 'transaction'
    assert [e['request']['method'] for e in bundle['entry']] == ['PUT'] * 6  # Patient, Practitioner, doc, 2 obs, provenance
    assert len(entries_by_type(bundle, 'Patient')) == 1
    assert len(entries_by_type(bundle, 'Practitioner')) == 1
    assert len(entries_by_type(bundle, 'DocumentReference')) == 1
    obs = entries_by_type(bundle, 'Observation')
    assert len(obs) == 2
    assert [o['code']['coding'][0]['code'] for o in obs] == ['6301-6', '14979-9']
    assert obs[0]['valueQuantity']['value'] == 1.1
    assert obs[0]['valueQuantity']['code'] == '1'
    assert obs[1]['valueQuantity']['code'] == 's'
    assert all(o['subject']['reference'] == 'Patient/maria-beispiel' for o in obs)
    prov = entries_by_type(bundle, 'Provenance')[0]
    assert {x['reference'] for x in prov['target']} == {'Observation/'+o['id'] for o in obs} | {'DocumentReference/'+entries_by_type(bundle, 'DocumentReference')[0]['id']}
    assert 'mock-eid' in entries_by_type(bundle, 'Practitioner')[0]['identifier'][0]['system']
    assert prov['agent'][0]['who']['reference'].startswith('Practitioner/')
    assert 'simulated eID' in prov['activity']['text']
    assert filing_status(api, req_id)['status'] == 'filed'
    assert audit(api, req_id)[-1]['what'] == 'ANSWER_FILED'
    assert all(e['request']['url'].startswith(e['resource']['resourceType']+'/') for e in bundle['entry'])


def test_rehab_attachment_roundtrip(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, kind='rehab', event='$fhir-rehab')
    text = rehab()
    assert submit(api, csrf, text, upload=False).status_code == 303
    bundle = export_bundle(api, req_id)
    assert len(entries_by_type(bundle, 'Observation')) == 0
    doc = entries_by_type(bundle, 'DocumentReference')[0]
    att = doc['content'][0]['attachment']
    assert att['contentType'] == 'text/markdown'
    assert base64.b64decode(att['data']).decode('utf-8') == text
    assert doc['subject']['reference'] == 'Patient/maria-beispiel'
    assert len(entries_by_type(bundle, 'Provenance')) == 1
    assert len(bundle['entry']) == 4


def test_fhir_fails_closed_offline_and_retries(demo, monkeypatch):
    api, _ = demo
    from app import fhir
    def offline(_):
        raise fhir.FhirFilingError('FHIR offline')
    monkeypatch.setattr(fhir, 'post_transaction', offline)
    req_id, csrf = create_verified(demo, event='$fhir-offline')
    assert submit(api, csrf, lab()).status_code == 303
    assert filing_status(api, req_id)['status'] == 'failed'
    assert 'FHIR filing is pending or failed' in api.get('/portal/submitted').text
    assert [a['what'] for a in audit(api, req_id)].count('ANSWER_FILED') == 0
    assert api.get('/internal/submissions/'+req_id, headers={'X-Bot-Secret':SECRET}).status_code == 200
    called = []
    def online(bundle):
        called.append(bundle)
        return {'resourceType': 'Bundle', 'type': 'transaction-response', 'entry': [{'response':{'status':'200 OK'}} for _ in bundle['entry']]}
    monkeypatch.setattr(fhir, 'post_transaction', online)
    result = api.post('/internal/fhir/retry/'+req_id, headers={'X-Bot-Secret':SECRET})
    assert result.status_code == 200 and result.json()['status'] == 'filed'
    assert len(called) == 1
    assert [a['what'] for a in audit(api, req_id)].count('ANSWER_FILED') == 1
    again = api.post('/internal/fhir/retry/'+req_id, headers={'X-Bot-Secret':SECRET})
    assert again.json()['already_filed'] is True
    assert len(called) == 1
    assert [a['what'] for a in audit(api, req_id)].count('ANSWER_FILED') == 1


def test_wrong_patient_never_reaches_fhir(demo, monkeypatch):
    api, _ = demo
    calls = []
    monkeypatch.setattr(fhir, 'post_transaction', lambda bundle: calls.append(bundle))
    req_id, csrf = create_verified(demo, event='$fhir-m3')
    assert submit(api, csrf, lab('Max Beispiel','1 January 1960')).status_code == 422
    assert calls == []
    assert api.get('/internal/fhir/status/'+req_id, headers={'X-Bot-Secret':SECRET}).status_code == 404
    assert api.post('/internal/fhir/retry/'+req_id, headers={'X-Bot-Secret':SECRET}).status_code == 404


def test_api_restricted_fhir_routes(demo):
    api, _ = demo
    assert api.get('/internal/fhir/export/req_unknown').status_code == 401
    assert api.get('/internal/fhir/status/req_unknown').status_code == 401
    assert api.post('/internal/fhir/retry/req_unknown').status_code == 401


def test_idempotent_transaction_ids(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, event='$fhir-stable')
    submit(api, csrf, lab())
    first, second = export_bundle(api, req_id), export_bundle(api, req_id)
    ids1 = [x['request']['url'] for x in first['entry']]
    ids2 = [x['request']['url'] for x in second['entry']]
    assert ids1 == ids2
    assert len(ids1) == len(set(ids1))
    assert [x['resource']['resourceType'] for x in first['entry']] == [x['resource']['resourceType'] for x in second['entry']]


def test_unknown_ucum_unit_fails_to_claim_ucum():
    q = fhir.quantity({'value': 3, 'unit': 'unrecognized-unit'})
    assert q == {'value': 3.0, 'unit': 'unrecognized-unit'}
    assert fhir.quantity({'value': 245, 'unit':'10^9/L'})['code'] == '10*9/L'


def test_fhir_transaction_checks_response_shape(monkeypatch):
    class FakeResponse:
        def __enter__(self):return self
        def __exit__(self, *args):return False
        def read(self, *args):return b'{}'
    monkeypatch.setattr(fhir, 'urlopen', lambda request, timeout: FakeResponse())
    with pytest.raises(fhir.FhirFilingError, match='unexpected bundle'):
        fhir.post_transaction({'entry':[{'resource':{'resourceType':'Patient','id':'abc'}}]})


def test_four_organizer_loinc_codes_are_preserved(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, event='$fhir-4-values')
    src = ('# Labor Kanalstraße: lab report\n'
           'Patient: Maria Beispiel, born 12 March 1961\n'
           'Sample taken: 22 October 2026, 08:10\n'
           '| Test | Result | Unit | Reference range | LOINC code |\n'
           '|---|---|---|---|---|\n'
           '| INR (prothrombin time) | 1.0 | | 0.8 to 1.2 | 6301-6 |\n'
           '| aPTT | 31 | s | 25 to 37 | 14979-9 |\n'
           '| Platelets | 245 | 10^9/L | 150 to 400 | 777-3 |\n'
           '| Fibrinogen | 3.1 | g/L | 2.0 to 4.0 | 3255-7 |\n')
    assert submit(api, csrf, src).status_code == 303
    obs = entries_by_type(export_bundle(api, req_id), 'Observation')
    assert len(obs) == 4
    assert [o['code']['coding'][0]['code'] for o in obs] == ['6301-6', '14979-9', '777-3', '3255-7']
    assert [o['valueQuantity']['value'] for o in obs] == [1, 31, 245, 3.1]
    assert obs[2]['valueQuantity']['code'] == '10*9/L'
    assert obs[0]['effectiveDateTime'] == '2026-10-22'
    assert obs[0]['referenceRange'][0]['low']['value'] == .8
    assert obs[0]['referenceRange'][0]['high']['value'] == 1.2


def test_bundle_fullurls_resolve_relative_references(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, event='$fhir-valid-fullurls')
    assert submit(api, csrf, lab()).status_code == 303
    bundle = export_bundle(api, req_id)
    from urllib.parse import urlsplit
    entries = bundle['entry']
    urls = {entry['fullUrl'] for entry in entries}
    assert len(urls) == len(entries)
    for entry in entries:
        resource = entry['resource']
        assert entry['fullUrl'].endswith('/' + resource['resourceType'] + '/' + resource['id'])
        assert entry['request']['url'] == resource['resourceType'] + '/' + resource['id']
        assert resource['text']['status'] == 'generated'
        assert 'xmlns="http://www.w3.org/1999/xhtml"' in resource['text']['div']
    base = entries[0]['fullUrl'].split('/Patient/')[0]
    for resource in (entry['resource'] for entry in entries):
        refs = []
        if resource['resourceType'] == 'Observation':
            refs = [resource['subject'], resource['performer'][0], resource['derivedFrom'][0]]
        if resource['resourceType'] == 'DocumentReference':
            refs = [resource['subject'], resource['author'][0]]
        if resource['resourceType'] == 'Provenance':
            refs = resource['target'] + [resource['agent'][0]['who']]
        assert all(base + '/' + r['reference'] in urls for r in refs)


def test_canonical_loinc_displays_and_source_text(demo):
    api, _ = demo
    req_id, csrf = create_verified(demo, event='$fhir-loinc-display')
    source = (
        '# Lab result\n'
        'Patient: Maria Beispiel, born 12 March 1961\n'
        '| Test | Result | Unit | Reference range | LOINC code |\n'
        '|---|---|---|---|---|\n'
        '| INR (prothrombin time) | 1.0 | | 0.8 to 1.2 | 6301-6 |\n'
        '| aPTT | 31 | s | 25 to 37 | 14979-9 |\n'
        '| Platelets | 245 | 10^9/L | 150 to 400 | 777-3 |\n'
        '| Fibrinogen | 3.1 | g/L | 2.0 to 4.0 | 3255-7 |\n'
    )
    assert submit(api, csrf, source).status_code == 303
    obs = entries_by_type(export_bundle(api, req_id), 'Observation')
    assert len(obs) == 4
    for o in obs:
        coding = o['code']['coding'][0]
        assert coding['display'] == fhir.LOINC_DISPLAY[coding['code']]
        assert o['code']['text'] in ['INR (prothrombin time)', 'aPTT', 'Platelets', 'Fibrinogen']
