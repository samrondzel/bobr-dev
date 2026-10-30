# Operator commands (Windows PowerShell)

Commands assume current working directory is `pgk_step2_gateway` and the `pgk_step1_matrix` server is already configured. **All systems are local and synthetic.**

## Start

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d                        # Mailpit
docker compose -f compose.fhir.yaml up -d  # HAPI FHIR
Invoke-RestMethod http://127.0.0.1:8008/_matrix/client/versions
$cap = Invoke-RestMethod http://127.0.0.1:8090/fhir/metadata
$cap | Select-Object resourceType,fhirVersion
python -m pytest -q
```

In separate terminals from `pgk_step2_gateway`:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

```powershell
python matrix_bot.py
```

## SMS simulator (restricted local dev endpoint)

```powershell
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
$headers = @{ 'X-Bot-Secret' = $secret }
$sms = Invoke-RestMethod 'http://127.0.0.1:8000/internal/dev/sms' -Headers $headers
$sms.messages[0]
```

Do not take a screenshot that exposes the SMS invitation bearer link; open it in your local browser.

## Look up filing status and audit events

```powershell
$reqId = 'req_REPLACE'
Invoke-RestMethod "http://127.0.0.1:8000/internal/fhir/status/$reqId" -Headers $headers
$r = Invoke-RestMethod "http://127.0.0.1:8000/internal/requests/$reqId" -Headers $headers
$r.audit | Format-Table who,what,when
```

## Official HL7 FHIR R4 validation

```powershell
$reqId = 'req_REPLACE'
python tools/export_fhir.py $reqId
java -jar .\validator_cli.jar ".\fhir-validation\$reqId\bundle.json" -version 4.0.1
```

The validator requires Java 17+; use 21 if available. The validator's output must be checked; successful Java execution alone does not imply 0 errors. To inspect a recorded `DocumentReference`, use the `resource_refs` returned by the FHIR status endpoint and request that exact resource from HAPI.

## Misdelivery manual checks

**M1:** send request for named Eva with contact `eva.brandl@labor-kanaI.example` (capital I). Use a *different identity* when opening the link. Confirm: no patient/type disclosure, HTTP 403, `MISDELIVERY_CAUGHT`, no `ANSWER_FILED`.

**M2:** create normal Eva request; use the invitation in a fresh incognito session as a colleague, not Eva. Confirm: no filing and audit mismatch event. Do not fake email forwarding as a claim about transport; demonstrate the same bearer link was opened by a different credential.

**M3:** new Eva request, authenticate correctly, submit `scenario/documents/lab-result-max-beispiel.md`. Confirm 422, `MISDELIVERY_CAUGHT(reason=wrong_patient)`, no `ANSWER_FILED`, and Matrix warning was **delivered** to Lena. `pending` in the outbox is not the same as delivered.

## FHIR container permissions if H2 access denied

The HAPI container may lack `sh` and `id`. Use `docker image inspect` to determine its numeric user and a temporary BusyBox container to correct the volume owner; do not run the HAPI server permanently as root. Never run `docker compose down -v` unless intending to delete demo FHIR data.

## Isolation / security warnings

- `.env`, SQLite, `.state`, `.venv`, `validator_cli.jar`, generated FHIR exports, and raw verification logs should not be in a public Git repository. Publish **sanitized summaries**, not invitation links, secrets or full local paths.
- Do not use clinical data other than provided synthetic fixtures.
- Access to FHIR, portal and Mailpit is only bound to localhost in the provided Compose setup. For a genuine external recipient system, HTTPS and separate network access control are required.
