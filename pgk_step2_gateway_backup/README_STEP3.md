# PGK Gateway — Step 3: mock eID + M1/M2

**What changes:** The external invitation page now contains a synthetic eID check. It does NOT display patient information to an unverified user. A recognized fake eID subject must be the **named person** on the doctor's request; knowing/forwarding the email link alone is insufficient. Verified people get a short-lived HttpOnly cookie and can open `/portal`. No document upload or FHIR filing yet.

**Important:** This is an intentionally limited local **mock identity provider**, not real ID Austria, not secure medical software. Use only synthetic data. Test credentials in this readme are PUBLIC DEMO FIXTURES, not actual credentials. A user with access to these codes can impersonate a synthetic identity: never treat this as strong authentication or deploy it with real health data.

## 1. Upgrade the running Step 2, not a new installation

Keep the previously created `pgk_step2_gateway/.env`, `pgk_step2_gateway/data/gateway.sqlite3`, `pgk_step1_matrix/` Synapse/Element setup, and Matrix account unchanged. Stop **FastAPI** and **matrix_bot.py** with `Ctrl+C` first, but keep Docker services running.

Extract the ZIP **at the root of your hackathon repository**. It contains paths under `pgk_step2_gateway/`. Overwrite `app/main.py`, `tests/test_gateway.py`, and `requirements.txt`; add `app/identity.py`, `tests/test_identity.py`, and `README_STEP3.md`.

If you made your own edits to `app/main.py`, back it up or compare the files before overwriting.

Do **not** replace `.env`. The ZIP contains `.env.step3.example` for reference only. Add these four entries to your existing `.env`:

```ini
# Synthetic local eID credentials: ONLY for demo/testing
PGK_MOCK_EID_EVA_PIN=demo-eva-8642
PGK_MOCK_EID_STEFAN_PIN=demo-stefan-6391
PGK_MOCK_EID_COLLEAGUE_PIN=demo-colleague-5728
PGK_MOCK_EID_OUTSIDER_PIN=demo-outsider-1946
```

Your existing `PGK_ALLOWED_ROOM`, `PGK_ALLOWED_SENDER`, `PGK_BOT_SECRET`, `PGK_PUBLIC_BASE_URL` and Matrix settings must remain unchanged. If you previously configured different server-side secrets, keep those instead of the example values.

Then in Windows PowerShell:

```powershell
cd pgk_step2_gateway
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
```

Expect **17 passed**. SQLite migrations are additive: Step 3 creates `identity_sessions` and `identity_attempts`, retaining all Step 2 requests and audit rows.

## 2. Run and test the successful flow

Make sure Synapse+Element (from Step 1) and Mailpit (from Step 2) are already running:

```powershell
docker compose ps
```

Open one terminal:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Open a second terminal in the same directory:

```powershell
.\.venv\Scripts\Activate.ps1
python matrix_bot.py
```

Enter your previous `pgkbot` username and password.

In Element, as Dr Lena Hofer, type:

```text
!request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example
```

Go to Mailpit: <http://127.0.0.1:8025>. Open the latest email and follow its link in a **fresh private/incognito browser window**. Before identity verification, the page must **not** show Maria's name, date of birth or document type.

Select **Dr. Eva Brandl** in the synthetic eID selector; enter `demo-eva-8642`. After verification, `/portal` should show Maria Beispiel and the requested type. You are not creating a PGK account — the eID fixture is pretending to be an outside credential provider.

**Note:** Invitations expire 20 minutes after creation. Request a fresh one for a new attempt.

## 3. Run M1: wrong email address

In Element:

```text
!request lab "Dr. Eva Brandl" eva.brandl@labor-kanaI.example
```

**Look carefully:** `kanaI` ends in a capital `I`, not a lowercase `l`. This mirrors the official wrong-address test.

Mailpit catches the email to the *wrong* address. Open its link in an **incognito window** as the unrelated person and use **Unrelated recipient** + `demo-outsider-1946`.

**Expected:** HTTP 403; no patient details or document type; backend logs `IDENTITY_CHECKED` (`result: denied`) and `MISDELIVERY_CAUGHT` (`reason: recipient_identity_mismatch`).

## 4. Run M2: forwarded email

Create a fresh correct lab request (same command as in section 2), then imagine Eva forwards that email to a colleague. The recipient opens the **same link** in a new incognito window. Select **Lab colleague** and enter `demo-colleague-5728`.

**Expected:** HTTP 403; no patient details; a `MISDELIVERY_CAUGHT` audit event. A colleague cannot send data as Eva. No FHIR resources are written in this step.

## 5. Inspect the audit log

The Matrix bot prints a generated `req_...` ID after each request. In PowerShell:

```powershell
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
$reqId = 'req_REPLACE_WITH_REAL_ID'
$result = Invoke-RestMethod -Uri "http://127.0.0.1:8000/internal/requests/$reqId" -Headers @{ 'X-Bot-Secret' = $secret }
$result.audit | Format-Table who, what, when
```

For M1/M2 you should find `REQUEST_CREATED`, `REQUEST_SENT`, `LINK_OPENED`, `IDENTITY_CHECKED`, `MISDELIVERY_CAUGHT`.

Raw mock eID verification codes are never written to the audit log. A successful ID check creates a 10-minute HttpOnly session; the session is also bounded by the invitation's original 20-minute expiry.

## 6. Design choices and limitations

- The `recipient_name` stored in Step 2 maps to a **fixed synthetic eID subject ID**. We never accept typed names alone as identity proof.
- The **mock identity provider** uses four server-configured fixture codes. In a real system, you would replace this with a vetted ID provider and validate signed assertions, authorization, subject binding and trust level. Public demo fixture codes do not provide real security.
- A secret invitation link does not itself prove identity.
- On mismatch, the server does not render the patient or document type, logs the attempt, and blocks continuation.
- Verification attempts are rate limited at five failures *per invitation*, for this demo; production requires a proper throttling/abuse strategy.
- Unknown outside names currently **fail closed** because only Eva and Stefan are in the mock identity directory. Before the jury's unseen-person tests you will need an extensible mock subject registry (or real eID integration). This is a known limitation, not a claim of full generalization.
- The backend has no document-upload endpoint or FHIR persistence yet. It cannot pass the full hackathon suite or M3 until later steps.
- There is no real E2EE for Matrix. Use this local demo only with synthetic data and loopback HTTP, never production health information.
- Open M1 and M2 links in separate incognito windows so you do not reuse an existing verified browser session from another request.

## 7. Files changed

```text
pgk_step2_gateway/
  app/main.py                 # adds identity schema migration and routes
  app/identity.py             # synthetic identity provider, M1/M2, session cookie
  requirements.txt            # adds python-multipart
  .env.step3.example          # example config; DO NOT overwrite existing .env
  tests/test_gateway.py      # original tests updated for new landing page
  tests/test_identity.py     # M1, M2, success/denial/session/rehab tests
  README_STEP3.md
```

The existing `matrix_bot.py`, `compose.yaml`, and your previous persistent DB are not replaced by this patch.

After success:

```bash
git add pgk_step2_gateway/app pgk_step2_gateway/requirements.txt pgk_step2_gateway/tests pgk_step2_gateway/README_STEP3.md pgk_step2_gateway/.env.step3.example
git commit -m "Add mock eID verification and M1 M2 misdelivery protection"
git push
```

Next step: receive the supplied Markdown document, verify the patient belongs to the request (M3), convert lab values to FHIR R4 Observations / rehab to DocumentReference, create Provenance and persist to the FHIR server.
