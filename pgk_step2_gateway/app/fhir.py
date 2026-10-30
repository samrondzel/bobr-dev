"""FHIR R4 filing for already-verified *synthetic* markdown submissions.

The transaction uses deterministic REST IDs (PUT) so retry after a network
error/crash does not duplicate clinical resources. This is a hackathon prototype.
"""
from __future__ import annotations

import base64
from html import escape
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from fastapi import APIRouter

from . import main as gateway
from .documents import expected_patient_file

router = APIRouter()
ID_ROOT = "https://pgk-demo.example/identifiers"

# These labels have been confirmed by the HL7 validator for the organizer's codes.
# For other valid LOINC codes, omit coding.display until we can verify it;
# retain the source name separately in CodeableConcept.text.
LOINC_DISPLAY = {
    "6301-6": "INR in Platelet poor plasma by Coagulation assay",
    "14979-9": "aPTT in Platelet poor plasma by Coagulation assay",
    "777-3": "Platelets [#/volume] in Blood by Automated count",
    "3255-7": "Fibrinogen [Mass/volume] in Platelet poor plasma by Coagulation assay",
}


def add_narrative(resource: dict, summary: str) -> None:
    """Add a minimal human-readable FHIR R4 XHTML narrative (dom-6)."""
    if "text" not in resource:
        resource["text"] = {
            "status": "generated",
            "div": (
                '<div xmlns="http://www.w3.org/1999/xhtml">'
                '<p>' + escape(summary) + '</p></div>'
            ),
        }




class FhirFilingError(Exception):
    pass


def init_fhir_db(cx: sqlite3.Connection) -> None:
    cx.executescript("""
        CREATE TABLE IF NOT EXISTS fhir_filings (
            request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            resource_refs_json TEXT,
            filed_at TEXT
        );
    """)


def stable_id(request_id: str, resource_type: str, detail: str = "") -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"pgk-hackathon:{request_id}:{resource_type}:{detail}").hex


def parse_date_from_markdown(markdown: str) -> str | None:
    match = re.search(r"^Sample taken:\s*(\d{1,2} [A-Za-z]+ \d{4})", markdown, re.I | re.M)
    if not match:
        return None
    for pattern in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(match.group(1), pattern).date().isoformat()
        except ValueError:
            pass
    return None


def quantity(row: dict) -> dict:
    """Only claim UCUM coding for units we know. Preserve others as free text."""
    raw = (row["unit"] or "").strip()
    value = float(row["value"])
    if not raw:
        return {"value": value, "unit": "1", "system": "http://unitsofmeasure.org", "code": "1"}
    aliases = {"10^9/L": "10*9/L", "×10^9/L": "10*9/L", "10⁹/L": "10*9/L",
               "sec": "s", "seconds": "s", "g/L": "g/L", "s": "s",
               "mg/dL": "mg/dL", "g/dL": "g/dL", "mmol/L": "mmol/L", "U/L": "U/L",
               "10*9/L": "10*9/L", "%": "%"}
    if raw in aliases:
        return {"value": value, "unit": raw, "system": "http://unitsofmeasure.org", "code": aliases[raw]}
    return {"value": value, "unit": raw}  # unknown UCUM must not be invented


def range_quantity(number: float, exemplar: dict) -> dict:
    result = {"value": number}
    for key in ("unit", "system", "code"):
        if key in exemplar:
            result[key] = exemplar[key]
    return result


def maybe_reference_range(raw: str, exemplar: dict) -> list[dict] | None:
    match = re.fullmatch(r"\s*(-?\d+(?:[.,]\d+)?)\s*(?:to|–|—|-)\s*(-?\d+(?:[.,]\d+)?)\s*", raw)
    if not match:
        return None
    low = float(match.group(1).replace(",", "."))
    high = float(match.group(2).replace(",", "."))
    if high < low:
        return None
    return [{"low": range_quantity(low, exemplar), "high": range_quantity(high, exemplar)}]


def bundle_entry(resource: dict) -> dict:
    kind, resource_id = resource["resourceType"], resource["id"]
    # These are PUTs to stable REST identifiers, not temporary creates.
    # The absolute fullUrl must identify that very same resource. This
    # also lets validators resolve relative references between entries.
    base = os.getenv("PGK_FHIR_BASE_URL", "http://127.0.0.1:8090/fhir").rstrip("/")
    return {"fullUrl": f"{base}/{kind}/{resource_id}",
            "resource": resource, "request": {"method": "PUT", "url": f"{kind}/{resource_id}"}}


def build_transaction(row: sqlite3.Row | dict, submission: sqlite3.Row | dict) -> dict:
    """Build valid-shaped R4 JSON. Validate externally with HL7 validator before judging."""
    if row["request_id"] != submission["request_id"]:
        raise FhirFilingError("Request and submission mismatch")
    patient = json.loads(expected_patient_file().read_text(encoding="utf-8"))
    if patient.get("resourceType") != "Patient" or submission["patient_ref"] != f"Patient/{patient.get('id')}":
        raise FhirFilingError("Patient reference mismatch: refuse to file")
    parsed = json.loads(submission["parsed_json"])
    kind = row["document_kind"]
    if kind != parsed.get("kind") or kind != submission["document_kind"]:
        raise FhirFilingError("Document type mismatch: refuse to file")
    if kind not in ("lab", "rehab"):
        raise FhirFilingError("Unsupported document type")

    reqid = row["request_id"]
    created = submission["created_at"]
    practitioner_id = stable_id(reqid, "Practitioner", "sender")
    subject_id = submission["sender_subject"]
    if not subject_id or not subject_id.startswith("eid-demo-"):
        raise FhirFilingError("No verified mock eID subject")
    name = row["recipient_name"]
    practitioner = {
        "resourceType": "Practitioner", "id": practitioner_id, "active": True,
        "identifier": [{"system": ID_ROOT + "/verified-mock-eid", "value": subject_id}],
        "name": [{"text": name}],
    }
    md_bytes = submission["markdown"].encode("utf-8")
    doc_id = stable_id(reqid, "DocumentReference", "source")
    document_ref = {
        "resourceType": "DocumentReference", "id": doc_id,
        "status": "current", "subject": {"reference": submission["patient_ref"]},
        "date": created,
        "description": ("Blood clotting laboratory result" if kind == "lab"
                        else "Rehabilitation discharge report"),
        "author": [{"reference": f"Practitioner/{practitioner_id}"}],
        "content": [{"attachment": {"contentType": "text/markdown", "language": "en",
                                     "data": base64.b64encode(md_bytes).decode("ascii"),
                                     "size": len(md_bytes), "title": "Original synthetic Markdown answer"}}],
    }
    resources = [patient, practitioner, document_ref]
    targets = [{"reference": f"DocumentReference/{doc_id}"}]
    if kind == "lab":
        rows = parsed.get("observations")
        if not isinstance(rows, list) or not rows:
            raise FhirFilingError("No laboratory observations to file")
        effective = parse_date_from_markdown(submission["markdown"])
        for index, obs in enumerate(rows):
            if not re.fullmatch(r"\d{1,7}-\d", str(obs["loinc"])):
                raise FhirFilingError("Invalid LOINC code")
            oid = stable_id(reqid, "Observation", str(index))
            val = quantity(obs)
            loinc = str(obs["loinc"])
            loinc_coding = {"system": "http://loinc.org", "code": loinc}
            if loinc in LOINC_DISPLAY:
                loinc_coding["display"] = LOINC_DISPLAY[loinc]
            observation = {
                "resourceType": "Observation", "id": oid, "status": "final",
                "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                          "code": "laboratory", "display": "Laboratory"}]}],
                "code": {"coding": [loinc_coding], "text": obs["test"]},
                "subject": {"reference": submission["patient_ref"]},
                "performer": [{"reference": f"Practitioner/{practitioner_id}"}],
                "valueQuantity": val,
                "derivedFrom": [{"reference": f"DocumentReference/{doc_id}"}],
            }
            if effective:
                observation["effectiveDateTime"] = effective
            interval = maybe_reference_range(obs.get("reference_range", ""), val)
            if interval:
                observation["referenceRange"] = interval
            resources.append(observation)
            targets.append({"reference": f"Observation/{oid}"})
    prov_id = stable_id(reqid, "Provenance", "filing")
    provenance = {
        "resourceType": "Provenance", "id": prov_id,
        "target": targets,
        "occurredDateTime": created,
        "recorded": gateway.now_iso(),
        "activity": {"text": "Submitted after simulated eID identity verification"},
        "agent": [{"who": {"reference": f"Practitioner/{practitioner_id}"},
                   "type": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                                         "code": "author"}]}}],
    }
    resources.append(provenance)
    # FHIR's dom-6 narrative is a best-practice constraint. Keep it short and
    # escaped; these are exclusively synthetic hackathon data.
    for resource in resources:
        kind_name = resource["resourceType"]
        if kind_name == "Patient":
            summary = "Synthetic patient record"
        elif kind_name == "Practitioner":
            summary = "Synthetic sender, verified with simulated eID"
        elif kind_name == "DocumentReference":
            summary = resource["description"]
        elif kind_name == "Observation":
            summary = (f'{resource["code"]["text"]}: '
                       f'{resource["valueQuantity"]["value"]} '
                       f'{resource["valueQuantity"].get("unit", "")}')
        else:
            summary = "Recorded provenance of a synthetic medical document submission"
        add_narrative(resource, summary)
    return {"resourceType": "Bundle", "type": "transaction", "entry": [bundle_entry(r) for r in resources]}


def post_transaction(bundle: dict) -> dict:
    base = os.getenv("PGK_FHIR_BASE_URL", "http://127.0.0.1:8090/fhir").rstrip("/")
    if not base.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        raise FhirFilingError("FHIR endpoint must be local or HTTPS")
    data = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    req = Request(base, data=data, method="POST",
                  headers={"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"})
    try:
        with urlopen(req, timeout=12) as res:
            payload = json.load(res)
    except HTTPError as exc:
        raise FhirFilingError(f"FHIR HTTP {exc.code}: {exc.read(500).decode('utf-8', 'replace')}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise FhirFilingError("FHIR service unreachable or invalid response") from exc
    if payload.get("resourceType") != "Bundle" or payload.get("type") != "transaction-response":
        raise FhirFilingError("FHIR returned an unexpected bundle")
    entries = payload.get("entry", [])
    if len(entries) != len(bundle["entry"]):
        raise FhirFilingError("FHIR transaction returned an unexpected resource count")
    for entry in entries:
        status = str(entry.get("response", {}).get("status", ""))
        if not status.startswith(("200", "201", "204")):
            raise FhirFilingError("FHIR transaction entry failed: " + status[:30])
    return payload


def file_accepted_submission(request_id: str) -> dict:
    """Retry-safe: same FHIR IDs on every attempt, one audit+notice on success.

    SQL and FHIR cannot share a transaction. An HTTP success followed by a local
    crash can be retried safely because the transaction uses deterministic PUTs.
    """
    with gateway.connect() as cx:
        r = cx.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        s = cx.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
        if r is None or s is None:
            raise FhirFilingError("Request has no accepted submission")
        status = cx.execute("SELECT status FROM fhir_filings WHERE request_id=?", (request_id,)).fetchone()
        if status is not None and status["status"] == "filed":
            return {"status": "filed", "already_filed": True}
        cx.execute("INSERT OR IGNORE INTO fhir_filings (request_id) VALUES (?)", (request_id,))
        cx.execute("UPDATE fhir_filings SET status='pending', attempt_count=attempt_count+1 WHERE request_id=?", (request_id,))
        try:
            bundle = build_transaction(r, s)
        except (FhirFilingError, KeyError, TypeError, ValueError) as exc:
            cx.execute("UPDATE fhir_filings SET status='failed',last_error=? WHERE request_id=?",
                       (str(exc)[:250], request_id))
            return {"status": "failed", "error": "FHIR mapping rejected this submission"}

    try:
        post_transaction(bundle)
    except FhirFilingError as exc:
        with gateway.connect() as cx:
            cx.execute("UPDATE fhir_filings SET status='failed', last_error=? WHERE request_id=?",
                       (str(exc)[:250], request_id))
        return {"status": "failed", "error": "FHIR storage failed; retry is available"}

    refs = [f'{e["resource"]["resourceType"]}/{e["resource"]["id"]}' for e in bundle["entry"]]
    with gateway.connect() as cx:
        old = cx.execute("SELECT status FROM fhir_filings WHERE request_id=?", (request_id,)).fetchone()
        if old and old["status"] == "filed":
            return {"status": "filed", "already_filed": True, "resource_refs": refs}
        cx.execute("UPDATE fhir_filings SET status='filed', last_error=NULL,resource_refs_json=?,filed_at=? "
                   "WHERE request_id=?", (json.dumps(refs), gateway.now_iso(), request_id))
        gateway.record_audit(cx, request_id, "pgk-fhir-gateway", "ANSWER_FILED",
                             {"resources": refs, "server": "configured FHIR endpoint"})
        from .submissions import record_notification
        row = cx.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        record_notification(cx, row, f'Request {request_id}: answer was saved to FHIR R4 '
                                     f'({len(refs)} resources).')
    return {"status": "filed", "already_filed": False, "resource_refs": refs}


@router.get('/internal/fhir/status/{request_id}', dependencies=[gateway.Depends(gateway.require_bot)])
def fhir_status(request_id: str):
    with gateway.connect() as cx:
        status = cx.execute("SELECT status,attempt_count,last_error,resource_refs_json,filed_at "
                            "FROM fhir_filings WHERE request_id=?", (request_id,)).fetchone()
    if status is None:
        raise gateway.HTTPException(404, "No FHIR filing status for request")
    return {"status": status["status"], "attempts": status["attempt_count"],
            "error": status["last_error"], "resource_refs": json.loads(status["resource_refs_json"] or '[]'),
            "filed_at": status["filed_at"]}


@router.get('/internal/fhir/export/{request_id}', dependencies=[gateway.Depends(gateway.require_bot)])
def export_fhir_bundle(request_id: str):
    with gateway.connect() as cx:
        row = cx.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        submission = cx.execute("SELECT * FROM submissions WHERE request_id=?", (request_id,)).fetchone()
        if row is None or submission is None:
            raise gateway.HTTPException(404, "No accepted submission")
    try:
        return build_transaction(row, submission)
    except FhirFilingError:
        raise gateway.HTTPException(422, "FHIR mapping rejected submission")


@router.post('/internal/fhir/retry/{request_id}', dependencies=[gateway.Depends(gateway.require_bot)])
def retry_fhir(request_id: str):
    try:
        return file_accepted_submission(request_id)
    except FhirFilingError:
        raise gateway.HTTPException(404, "No accepted submission")
