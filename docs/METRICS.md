# Hackathon metric results — fill in **measured** values

**Source:** [AIM Austria / TRACK-2-interoperability](https://github.com/AIM-Austria/TRACK-2-interoperability). Do not change measurement criteria or substitute Python tests for the official Java validator.

| Metric | Required | Measured for submission | Evidence |
|---|---|---|---|
| FHIR validation | 0 errors in all filed resources | **Lab example: 0 errors in Bundle** in previously provided HL7 run; **new lab / rehab: NOT YET CONFIRMED** | Save `java -jar validator_cli.jar .../bundle.json -version 4.0.1` logs |
| Outside recipient effort | 0 installs, 0 accounts, < 120 s | 0 installs / 0 PGK accounts by design; **elapsed seconds: NOT MEASURED** | Have a new user open request 1 email and stopwatch until upload submitted; record seconds |
| Misdelivery M1/M2/M3 | 3/3 caught | **MANUAL CONFIRMATION REQUIRED** | M1 and M2: 403/no disclosure/no filing and audit; M3: HTTP 422, no FHIR filing, Matrix warning marked sent |
| Audit coverage | 6/6 event types | **RUN report_metrics.py** | Request sent, link opened, identity checked, answer sent, answer filed, misdelivery caught — each with who/what/when |

### Record final values here before submitting

- Lab request ID: `req_...`
- Rehab request ID: `req_...`
- M1 wrong-address request ID: `req_...` — UI check (YES/NO): ____
- M2 forwarded-link request ID: `req_...` — UI check (YES/NO): ____
- M3 wrong-patient request ID: `req_...` — Matrix warning delivered (YES/NO): ____
- Lab transaction validation: ____ errors, ____ warnings
- Rehab transaction validation: ____ errors, ____ warnings
- New Markdown transaction validation (if tested): ____ errors, ____ warnings
- First-time recipient walkthrough: ____ seconds; ____ installations; ____ PGK accounts
- Pytest on submitting machine: ____ passed

### Quick collection

From `pgk_step2_gateway` in PowerShell:

```powershell
python -m pytest -q
python tools/report_metrics.py --lab req_YOUR_LAB --rehab req_YOUR_REHAB --m1 req_YOUR_M1 --m2 req_YOUR_M2 --m3 req_YOUR_M3 --outside-seconds 95 --installs 0 --accounts 0
```

**Replace IDs and elapsed seconds with real results.** If no timings or some requests are available, leave those flags out; the tool will explicitly report `NOT MEASURED` or `NOT VERIFIED`. To capture the result for an individual FHIR bundle:

```powershell
$reqId = "req_REPLACE"
python tools/export_fhir.py $reqId
java -jar .\validator_cli.jar ".\fhir-validation\$reqId\bundle.json" -version 4.0.1 2>&1 |
  Tee-Object ".\fhir-validation\$reqId\validator-output.txt"
```

Then link or paste the **actual** summary from `validator-output.txt` in this document. If the test failed, report the failure (do not hide it).

**Interpretation:** Python unit tests verify code behavior; they are not a replacement for network-level demo or official HL7 validation. The generated FHIR export is a current rendering of the stored synthetic submission, not proof of a prior HAPI server write; check `fhir_filings.status='filed'` and a direct read from HAPI.
