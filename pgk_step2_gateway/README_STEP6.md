# Step 6 — Generalization & Reliability (Synthetic demo only)

This is an **overlay** for the working Step 5 project `pgk_step2_gateway/`.
Keep `.env`, `data/gateway.sqlite3`, `.venv`, Synapse, Element, Mailpit and HAPI as they are. Do not run `docker compose down -v`.

## Changes

1. **Mock issuer for new people** — offline, administrator-provisioned synthetic eID identities stored in SQLite with salted PBKDF2-HMAC credentials. No PGK user account, and no public self-enrollment endpoint. Old Eva/Stefan demo PINs still work.
2. **Per-request binding** — new requests save an expected eID subject identifier, so a forwarded link or a typo address cannot authenticate as another person. Unprovisioned recipients fail before an invitation is sent.
3. **Independent delivery channel** — both `lab` and `rehab` accept either email or international phone number, chosen from the contact format.
4. **Markdown variability** — columns can be reordered (`Value`/`Result`, `Units`/`Unit`, `LOINC`/`LOINC code`), multiple lab tables are processed, numeric decimal comma and `<`/`>` comparators supported. Missing data, duplicate patient claims, malformed tables and bad LOINC check digits are rejected instead of silently filed.
5. **FHIR mapping** — `Observation.valueQuantity.comparator` retained; unknown but valid-format LOINC names are not guessed (`coding.display` omitted). Known organizer codes keep validated canonical displays.
6. Added generalization regression tests and synthetic test documents.

## Install (PowerShell; from the repository root)

```powershell
# Stop FastAPI and matrix_bot.py first (Ctrl+C). Docker services can stay running.
Copy-Item .\pgk_step2_gateway .\pgk_step2_gateway_before_step6 -Recurse
Expand-Archive .\pgk_step6_generalization_overlay.zip -DestinationPath . -Force
cd pgk_step2_gateway
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

The initial local run of the updated test suite gave **52 passed** (Python 3.13).
External HAPI/HL7 Java validation and live Matrix integration must be checked locally.

## Manual scenario A — NEW external person

**Provision a synthetic identity on the server, not through the recipient portal:**

```powershell
python tools/mock_eid_provider.py enroll --name "Dr. Nora Weiss"
```

Save the printed **subject ID** and **mock credential**. This step simulates the external identity provider already knowing the person. It is **not** a PGK account and must not be used as an actual identity system.

Restart FastAPI and Matrix bot, then in Element Web (logged in as Lena):

```text
!request lab "Dr. Nora Weiss" nora.weiss@example.org
```

Open Mailpit `http://127.0.0.1:8025`; click the new link. On the mock eID screen choose **Other synthetic eID (issuer-provisioned)** and enter the exact subject ID and credential. The recipient installs nothing and creates no PGK account.

Upload `fixtures/step6/new-lab-maria.md`. Expect success, **two Observations** (Hb and glucose) and a `DocumentReference` plus `Provenance`. The doctor's Matrix room should receive a FHIR filing notification.

For an additional negative test: open a new request link, choose `Unrelated recipient` with your existing outsider PIN or use a different issuer subject. Result must be HTTP 403, no patient disclosure, and `MISDELIVERY_CAUGHT` in the audit log.

## Manual scenario B — new Markdown for WRONG patient

Create a fresh request for Dr. Nora Weiss, verify as Nora, upload `fixtures/step6/new-lab-max.md`.
Expected: HTTP 422 before FHIR, `MISDELIVERY_CAUGHT` with `wrong_patient`, warning in Matrix, and **no new Observation** from that rejected request.

## Manual scenario C — invalid LOINC / malformed data

Create a fresh request and upload `fixtures/step6/bad-loinc.md`. Expect rejection (HTTP 422), no FHIR write. Uploading an incomplete laboratory table likewise fails closed.

## Manual scenario D — rehab sent by email

The project now permits either channel for either document:

```text
!request rehab "Stefan Kern" stefan.kern@example.org
```

The invitation appears in Mailpit (instead of SMS outbox). Verify with Stefan's existing synthetic eID and submit the provided rehab report. Only `DocumentReference`, `Patient`, `Practitioner`, `Provenance` should be created for this new request, with **no Observation**.

Official organizer scenario still uses Stefan's SMS number; demo both if useful.

## Run tests

```powershell
python -m pytest -q
python -m pytest -q tests/test_generalization.py
```

If you want to inspect the saved FHIR resources, use the Step 5 export and validator commands:

```powershell
python tools/export_fhir.py req_YOUR_NEW_REQUEST_ID
java -jar .\validator_cli.jar .\fhir-validation\req_YOUR_NEW_REQUEST_ID\bundle.json -version 4.0.1
```

**Report actual validator output**: these new test documents were checked in Python tests, **not** against a running HL7 Validator in this environment. Unknown but valid LOINC codes must be checked for terminology accuracy; the check digit does not prove that a code exists or matches its label.

## Remaining limitations (state honestly in the README)

- The identity issuer is a *synthetic administrative fixture*, not real ID Austria. If the initial email goes to the wrong person, the recipient cannot bypass the issuer credential check; it is not possible to prove sender authorization clinically without real organizational identity/authorization infrastructure.
- The app currently uses the configured Patient (`scenario/patient.json`) for the hackathon's Maria Beispiel request. It does **not** provide a general patient registry or clinical master-patient-index resolution.
- Parser handles Markdown tables close to the organizer's format, not arbitrary unstructured medical PDFs or every Markdown dialect. If parsing or patient matching is ambiguous, the service rejects the submission rather than silently filing partial data.
- The official HL7 validator and real HAPI/Matrix services must be verified on a local machine and the new resource counts must be reported in submission metrics.
- Use **only synthetic data**. No public medical deployment or Internet exposure of these demo endpoints.

## Committing

```powershell
git status
git add pgk_step2_gateway/app pgk_step2_gateway/tests pgk_step2_gateway/tools pgk_step2_gateway/fixtures/step6 pgk_step2_gateway/README_STEP6.md
git commit -m "Generalize synthetic identity and Markdown intake with security tests"
git push
```
