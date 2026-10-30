# PGK Hackathon — Step 5: FHIR R4 filing

**Install as an overlay over your working Step 4. Keep `.env`, `.venv`, SQLite database, Synapse/Element and Mailpit.** Only synthetic medical data may be used. This is a prototype and not a medical system.

## What changed

- On a **valid, identity-checked Markdown submission**, backend saves it in SQLite (`ANSWER_SENT`) then attempts a FHIR R4 **transaction**. If the transaction succeeds, it writes `ANSWER_FILED` and queues a Matrix message. Bot from Step 4 already delivers queued notifications.
- Lab: creates/updates the scenario `Patient`, verified sender as `Practitioner`, source Markdown as `DocumentReference`, **one `Observation` per lab row** with source LOINC, and `Provenance` targeting all created clinical resources.
- Rehab: `Patient`, sender `Practitioner`, a `DocumentReference` with base64-encoded original Markdown text, and `Provenance`.
- Each Bundle entry uses `PUT` and a stable id derived from the request ID. Repeated attempts do not create extra resources. The original submission remains saved if FHIR is unavailable.
- `Provenance.activity` records that the submission followed a **simulated** eID check, and the Practitioner identifier records the mock-eID subject. This DOES NOT prove real identity. The local audit contains the detailed verification outcome.
- Internal endpoints (must have `X-Bot-Secret`):
  - `GET /internal/fhir/status/{request_id}` — filed/failed and resource list;
  - `GET /internal/fhir/export/{request_id}` — full transaction Bundle to validate;
  - `POST /internal/fhir/retry/{request_id}` — retry stored accepted submission.

## 0. Back up before merging files

On your Windows machine, from the repository root:

```powershell
Copy-Item pgk_step2_gateway pgk_step2_gateway_backup -Recurse
```

Extract the new ZIP **in the repository root**, replacing files inside `pgk_step2_gateway`. Do not copy the new directory *inside* the old one. Never overwrite or delete your `.env`, `.venv`, SQLite database, `pgk_step1_matrix`, or `scenario`.

## 1. Run HAPI FHIR (NEW CONTAINER, DIFFERENT PORT)

In PowerShell:

```powershell
cd pgk_step2_gateway
docker compose -f compose.fhir.yaml up -d
docker compose -f compose.fhir.yaml ps
```

HAPI first boot may take a little while. In browser open `http://127.0.0.1:8090/fhir/metadata` and confirm JSON contains `"resourceType": "CapabilityStatement"` and `"fhirVersion": "4.0.1"`.

The port **8090** is intentional: existing Element Web is on 8080. Container stays bound to localhost. The Compose file configures a volume for H2 persistence across restarts; this is a local demo setup only.

To inspect failed startups:

```powershell
docker compose -f compose.fhir.yaml logs --tail=120 fhir
```

## 2. Configure and run your existing backend + bot

Add to your existing `pgk_step2_gateway/.env`:

```ini
PGK_FHIR_BASE_URL=http://127.0.0.1:8090/fhir
```

Keep all other settings from Steps 2–4, including `PGK_BOT_SECRET`, Matrix room IDs, mock eID PINs. No new Python dependency is required. From `pgk_step2_gateway`:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

In a **second terminal** (same directory):

```powershell
.\.venv\Scripts\Activate.ps1
python matrix_bot.py
```

**Expected unit test output: `38 passed`** on the provided demo code. These use a mock FHIR HTTP response; **they do not prove your local HAPI server works**, which you check in the next steps.

## 3. Manual test: successful laboratory filing

1. In Element as Lena, send `!request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example`.
2. In Mailpit (`http://127.0.0.1:8025`), open the new email link.
3. Verify as Eva with the Step 3 mock eID PIN.
4. Upload `scenario/documents/lab-result-maria-beispiel.md` from the organizers' repository.
5. The portal should say **"filed on the FHIR R4 server"**. The Matrix bot should send an `answer was saved to FHIR R4` notification (poll cycle; bot must be running).
6. The official document contains 4 observations: INR LOINC 6301-6; aPTT 14979-9; platelets 777-3; fibrinogen 3255-7.

Note the `req_...` ID from the Matrix bot acknowledgment. In PowerShell:

```powershell
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
$reqId = 'req_YOUR_ID'
Invoke-RestMethod "http://127.0.0.1:8000/internal/fhir/status/$reqId" -Headers @{ 'X-Bot-Secret'=$secret }
Invoke-RestMethod 'http://127.0.0.1:8090/fhir/Observation?subject=Patient/maria-beispiel&_format=json' | ConvertTo-Json -Depth 8
```

Expect `status=filed`, and for **a fresh** HAPI instance at least 4 Observation resources.

To inspect FHIR resources for one request (without printing clinical data in the Matrix room):

```powershell
python tools/export_fhir.py $reqId
```

Exports transaction + separate resources under `fhir-validation/req_.../`.

## 4. Rehab document

Send in Element:

```text
!request rehab "Stefan Kern" "+43 660 000 0101"
```

Get the SMS link from the existing `GET /internal/dev/sms` endpoint, verify with Stefan's mock eID PIN, submit `scenario/documents/rehab-report-maria-beispiel.md`.

Expect one `DocumentReference` containing base64-encoded `text/markdown`, one `Provenance` plus Patient and Practitioner in transaction, and Matrix confirmation. No Observation is created for the rehab report.

## 5. M3 remains mandatory

Create a *new* lab request, verify Eva and upload `scenario/documents/lab-result-max-beispiel.md` (Max, not Maria). The backend must return HTTP 422, create `MISDELIVERY_CAUGHT`, notify Lena, and **NOT perform any FHIR transaction**. Tests cover this too.

## 6. HAPI unavailable / retry

If HAPI is stopped, the submission is still accepted into SQLite but shown as **pending or failed FHIR filing**. `ANSWER_FILED` is not written, and no successful Matrix notification is queued. Restart HAPI, then retry:

```powershell
docker compose -f compose.fhir.yaml up -d
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
$reqId = 'req_YOUR_ID'
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/internal/fhir/retry/$reqId" -Headers @{ 'X-Bot-Secret'=$secret }
```

If FHIR was successful and a local process crashed before recording it, repeating the request reuses the same **stable resource IDs**. Retrying a completed filing does not add an extra `ANSWER_FILED` audit event or extra Matrix notification. Do not wipe the HAPI storage volume while the SQLite database is in use; this local demo does not automatically reconcile a manually erased FHIR database.

## 7. IMPORTANT: Validate using the official HL7 CLI

Automated Python tests check construction, references, security and retry logic; **they are not HL7 validation**. Before claiming the challenge's "0 errors" metric, run the official Java validator on the generated output. The organizers provide this command in `scenario/README.md`.

Install a modern Java runtime if needed. Download the official JAR from the [HL7 FHIR Core releases](https://github.com/hapifhir/org.hl7.fhir.core/releases/latest/download/validator_cli.jar), save it in `pgk_step2_gateway/validator_cli.jar` (excluded by `.gitignore`), and run e.g. from `pgk_step2_gateway`:

```powershell
$reqId = 'req_YOUR_ID'
python tools/export_fhir.py $reqId
Get-ChildItem ".\fhir-validation\$reqId\*.json" | ForEach-Object {
  java -jar .\validator_cli.jar $_.FullName -version 4.0.1
}
```

Read the **error count and details**, not just the process return value. Also inspect warnings (e.g. unknown local coding systems). Fix any actual errors. The source LOINC codes must be semantically correct, not merely fit a numeric pattern; current parser trusts values supplied by the synthetic documents.

**Important:** HAPI accepting resources does **not** prove official HL7 validation yields zero errors. Validation has not been executed in the assistant environment, which lacks Java Validator and Docker.

## 8. What is still out of scope?

- Generalized mock identity provider for previously unseen people (currently fixture subjects from Step 3).
- Full resilient background job processing / auto-retry (the operator can manually retry via API).
- Full medical-grade authorization, audit, data retention, infrastructure security; NOT for real patient data.
- Real E2EE Matrix or official ID Austria.

## Troubleshooting

- **404 `/fhir/metadata`**: check HAPI startup and port 8090, not Element's port 8080.
- **`FHIR storage failed; retry is available`**: inspect HAPI logs, check `PGK_FHIR_BASE_URL` and the returned `fhir_filings.last_error` via `/internal/fhir/status/{request_id}`.
- **Submission accepted but Matrix silent**: backend queues success messages; use `matrix_bot.py` Step 4+ and check `/internal/notifications`.
- **Old Step 4 submission**: you can call `POST /internal/fhir/retry/{request_id}` without uploading again, even if no `fhir_filings` record exists yet.

## Commit

From repository root:

```powershell
git add pgk_step2_gateway/
git status
git commit -m "Add FHIR R4 transactions, provenance and filing notifications"
git push
```

Secrets in `.env`, `.venv`, SQLite, JAR and `fhir-validation/` output must **not** be committed. Check `.gitignore` in your existing repo before pushing.
