# PGK Gateway — Step 4: Markdown submission + wrong-patient M3

**Purpose:** Extend the existing working Step 3 (Matrix + FastAPI + Mailpit + mock eID) with a verified-only Markdown upload form, deterministic extraction of the patient's name/date of birth, and a **misdelivery M3** check. Rejected wrong-patient documents are **not accepted** and Dr. Hofer gets a warning in Matrix through the existing bot. Correct documents are stored locally in SQLite as accepted submissions, ready for FHIR R4 transformation in the next step.

> **Only synthetic data.** This is an educational local demo, not medical-grade software. It does not yet create or store FHIR resources, and its eID authentication is simulated.

## Install onto the existing project

Stop the FastAPI and Matrix bot Python processes (Ctrl+C). Keep Synapse, Element and Mailpit Docker containers running. Do **not** delete `.env`, `data/gateway.sqlite3`, the Matrix configuration or the previous bot account.

Extract the ZIP at the **root of your hackathon repository** so it merges into the **existing** `pgk_step2_gateway/` directory. New files are `app/documents.py`, `app/submissions.py`, `fixtures/patient.json`, `tests/test_submissions.py`, `README_STEP4.md`; updated files include `app/main.py`, `app/identity.py`, and `matrix_bot.py`. This package also carries the already-working Step-3 tests and requirements for consistency. **Back up your local edits** if you have modified any of these files. Do not overwrite `.env`; it is not included.

The included `fixtures/patient.json` is a minimal local fallback for the official synthetic FHIR Patient. When you have the organizer's `scenario/patient.json` alongside `pgk_step2_gateway/`, the server uses **that file** automatically. You can explicitly set `PGK_PATIENT_JSON=...` in `.env` to override the path (e.g. absolute path). Do not point this at real patient data.

From a **PowerShell** terminal:

```powershell
cd pgk_step2_gateway
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Expected on this package: **29 passed** (tested locally). Existing SQLite tables/data are preserved; `submissions` and `matrix_notifications` tables are created automatically at startup.

Run **two** terminals from `pgk_step2_gateway/`:

```powershell
# Terminal A: backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

```powershell
# Terminal B: Matrix bot — STOP the old bot first!
.\.venv\Scripts\Activate.ps1
python matrix_bot.py
```

Enter `pgkbot` login. The Step-4 bot now *also* polls an internal queue and sends notifications to the doctor's Matrix room. It uses a stable transaction ID per notice to avoid duplicate Matrix events after a retry.

## Test A: valid lab Markdown for Maria Beispiel

1. In Element as Lena, send:

   ```text
   !request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example
   ```
2. Open the newest email in Mailpit: http://127.0.0.1:8025. Follow its link; the landing page must not reveal patient details.
3. Pass synthetic eID: `Dr. Eva Brandl` and your configured `PGK_MOCK_EID_EVA_PIN` (the example value from Step 3 was `demo-eva-8642`).
4. `/portal` now has a file upload and a Markdown textarea. Upload the organizer's original file:

   `scenario/documents/lab-result-maria-beispiel.md`
5. Click **Submit document**. You should see **Document received** and a clear note: **not yet filed on a FHIR server**.

The backend parses laboratory rows into an intermediate JSON object with test names, numeric values, units and LOINC codes. This is **not** yet FHIR. It adds an `ANSWER_SENT` audit event. The original Markdown is kept in the local SQLite database for Step 5.

## Test B: M3 — Max Beispiel sent for Maria

**Use a fresh request and a fresh incognito browser session** (the previous request has already been answered).

1. Repeat the Matrix command above; open its new Mailpit link.
2. Complete the synthetic eID as Eva.
3. Upload instead:

   `scenario/documents/lab-result-max-beispiel.md`
4. Click **Submit document**.

Expected:

- Browser displays **Patient mismatch**, HTTP 422.
- No accepted submission is created for the request; no FHIR data is filed.
- `MISDELIVERY_CAUGHT` audit event with `reason=wrong_patient`.
- **Matrix room shows a new warning** from `pgkbot` similar to:

  ```text
  WARNING: Request req_... received a document for a DIFFERENT PATIENT.
  The document was rejected and NOT filed. Please request a corrected document.
  ```

If the backend reports a mismatch but Matrix gets no warning, keep **both** bot and backend running, and check the bot terminal for `Delivered backend notification: ...`. The bot polls every ~2 seconds. You can inspect pending notifications with the internal API shown below.

## Test C: rehab Markdown from Stefan Kern

1. Create a rehab request:
   ```text
   !request rehab "Stefan Kern" "+43 660 000 0101"
   ```
2. Get the simulated SMS using the internal API (`/internal/dev/sms` with `X-Bot-Secret`).
3. Open its link, pass mock eID `Stefan Kern` with the configured `PGK_MOCK_EID_STEFAN_PIN`.
4. Upload `scenario/documents/rehab-report-maria-beispiel.md` or paste its text.
5. The document should be accepted and stored locally as a text report (for `DocumentReference` in Step 5).

## Inspect requests, audits, parsed data, and pending notifications

The existing internal endpoints remain protected by `X-Bot-Secret`. From PowerShell in `pgk_step2_gateway/`:

```powershell
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
$headers = @{ 'X-Bot-Secret' = $secret }
$reqId = 'req_REPLACE_WITH_YOUR_ID'

# Request and audit events
Invoke-RestMethod -Uri "http://127.0.0.1:8000/internal/requests/$reqId" -Headers $headers | ConvertTo-Json -Depth 8

# Accepted parsed Markdown, only for a successful answer
Invoke-RestMethod -Uri "http://127.0.0.1:8000/internal/submissions/$reqId" -Headers $headers | ConvertTo-Json -Depth 8

# Notifications not yet delivered to Matrix
Invoke-RestMethod -Uri "http://127.0.0.1:8000/internal/notifications" -Headers $headers | ConvertTo-Json -Depth 8
```

**Important:** In Step 4 there is no `ANSWER_FILED` event. `ANSWER_SENT` means an accepted response was received by the gateway, not persisted to FHIR. We will implement FHIR `Observation` / `DocumentReference` / `Provenance`, validation, transaction storage and `ANSWER_FILED` in Step 5.

## Code overview

- `app/documents.py`: strict parser for patient information, lab tables, LOINC code strings and rehab text. For an unknown format, it rejects the input rather than inventing results. It checks patient identity **before accepting** the answer. The parser is designed for the supplied Markdown format, but does not hardcode lab values.
- `app/submissions.py`: verified-only form upload/paste, per-session CSRF token, 64 KiB upload limit, authorization, patient mismatch check, acceptance into SQLite, and internal Matrix-notification queue.
- `app/identity.py`: `/portal` displays upload UI only after eID verification.
- `app/main.py`: initializes new SQLite tables and registers routes.
- `matrix_bot.py`: handles `!request` as before and polls/sends pending backend notifications to Matrix with idempotent transaction IDs.
- `tests/test_submissions.py`: M3, good lab, rehab, alternate patient DOB, session/CSRF, file type/size, parser edge cases, queue/ack, Matrix send.

## Limitations and next step

- No external FHIR server, no FHIR R4 resources, no HL7 validation yet.
- The bot must be running to deliver the warning to Dr Hofer; pending messages survive restarts in SQLite.
- Identity is synthetic, not trustworthy for real medical data; the web server runs locally over loopback HTTP.
- Document content is stored in SQLite for the next step, **not encrypted at rest**; only synthetic inputs should be used.
- Patient name + birth date are the available attributes in scenario documents. For real use, match reliable identifiers and apply manual review for ambiguity.
- Unknown Markdown field arrangements or unsupported dates fail closed. Judge tests using substantially different layouts require parser improvements, not guesswork.
- The Step-3 demo identity list still only recognizes Eva and Stefan (and two test outsiders). Support for arbitrary outside persons remains future work.

After you verify all flows:

```bash
git add pgk_step2_gateway/app pgk_step2_gateway/matrix_bot.py pgk_step2_gateway/fixtures pgk_step2_gateway/tests pgk_step2_gateway/README_STEP4.md
git commit -m "Add verified Markdown submission and M3 patient mismatch notifications"
git push
```

**Next:** transform accepted lab values into valid FHIR R4 `Observation` resources, rehab reports into `DocumentReference`, add `Provenance` and file them using a FHIR server. Run the official HL7 validator and log `ANSWER_FILED` only after successful persistence.
