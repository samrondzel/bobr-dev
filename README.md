# PGK Last Mile Gateway

**A reproducible synthetic-data prototype for AIM Austria / Track 2 — Health Data Interoperability.**

An internal clinician requests a document in a Matrix room; an external recipient receives a **generic** email or SMS link, proves their identity in a browser (simulated eID), sends an answer without joining the closed network, and the gateway stores clinical FHIR R4 resources with `Provenance` and informs the clinician through Matrix.

> **Scope and safety:** Hackathon demonstration only. All people and clinical data are synthetic. The eID issuer is simulated; Synapse demo room is not end-to-end encrypted; HAPI/SQLite and the recipient site are local services. Do **not** expose the demo services to the public Internet or process real medical records. Production use would need a real eID/authorization service, properly hardened HTTPS transport, access-controlled FHIR, and operational security controls.

## Quick demonstration

**Request 1 — laboratory by email**

1. Sign in to Element Web as `@lena.hofer:klinikum.example` and send:
   ```text
   !request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example
   ```
2. Open Mailpit (`http://127.0.0.1:8025`), follow the newest invitation, complete the **simulated** eID check as Eva, and upload `scenario/documents/lab-result-maria-beispiel.md`.
3. The gateway matches the patient's name/date of birth with Maria Beispiel, maps lab values to four LOINC-coded `Observation` resources, preserves the original Markdown as `DocumentReference`, and files these together with `Patient`, `Practitioner`, and `Provenance` on HAPI FHIR.
4. The Matrix bot posts the filing result in Lena's room. The gateway also logs `ANSWER_FILED`.

**Request 2 — rehabilitation by SMS**

1. In Element send:
   ```text
   !request rehab "Stefan Kern" "+43 660 000 0101"
   ```
2. The SMS is **simulated**. Retrieve the link through the authenticated local endpoint `/internal/dev/sms` (see [operator commands](docs/OPERATIONS.md)). Verify as Stefan, then upload `scenario/documents/rehab-report-maria-beispiel.md`.
3. The gateway files a `DocumentReference` with Markdown attachment, together with `Patient`, `Practitioner`, and `Provenance`. **No new `Observation` is created for this rehab request.**

Both email and SMS are supported for either type of document: channel is selected from the recipient contact, not from lab-vs-rehab type.

## Architecture

```text
Doctor (Element Web)     Matrix Synapse
          |                    |
          +--- Matrix event ---+
                               |
                          Python Matrix bot
                               |  restricted REST + bot secret
                          FastAPI gateway --------> SQLite
                               |                    requests, audit,
          +--------------------+                    sessions, submissions,
          |                    |                    notifications, FHIR status
       Mailpit              SMS outbox
          |                    |
          +--- generic secure-link invitation ---+
                                                  |
                                          Browser recipient portal
                                                  |
                                        synthetic eID verification
                                                  |
                                        Markdown intake + checks
                                                  |
                                          FHIR R4 mapper
                                                  |
                                      HAPI FHIR R4 (local)
                                                  |
                                audit + Matrix notification outbox
                                                  |
                                              Matrix bot
                                                  |
                                              Dr. Hofer
```

**Built:** FastAPI request gateway; Matrix bot; bearer-link invitation flow; email and simulated SMS adapters; synthetic credential issuer and session handling; Markdown parser with patient/type checks; FHIR transaction mapper, idempotent filing and retry; SQLite audit/notification outbox; automated tests.

**Existing tools/services:** Synapse + Element Web, Mailpit, HAPI FHIR JPA, Docker Compose, Python/FastAPI/SQLite, official HL7 FHIR Validator. No LLM or AI model is used; the clinical extraction is deterministic and rejects unclear input rather than inventing values. There is no custom Matrix client, fax integration or end-to-end encryption implementation.

## Running locally (Windows PowerShell)

Prerequisites: Python 3.11+, Docker Desktop with Compose, Java 17+ (Java 21 recommended for the current HL7 Validator), and an unencrypted **synthetic** Matrix demo room.

1. Start the Matrix/Element environment from `pgk_step1_matrix/matrix/` using its bundled README. Create the synthetic Lena and bot users and invite the bot to the room. Start Synapse and Element first.
2. From `pgk_step2_gateway/`:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   Copy-Item .env.example .env    # only if .env does not already exist
   ```
   Edit `.env`: `PGK_BOT_SECRET` (generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`), `PGK_ALLOWED_ROOM` (the **real** room ID), `PGK_ALLOWED_SENDER=@lena.hofer:klinikum.example`, `PGK_FHIR_BASE_URL=http://127.0.0.1:8090/fhir`, and the synthetic Eva/Stefan PINs used by the demo. **Never commit `.env`.**
3. Start local services in `pgk_step2_gateway/`:
   ```powershell
   docker compose up -d
   docker compose -f compose.fhir.yaml up -d
   ```
   Check `http://127.0.0.1:8090/fhir/metadata` responds with a FHIR R4 `CapabilityStatement` and open Mailpit at `http://127.0.0.1:8025`. HAPI JPA may require local volume ownership correction; see [operations](docs/OPERATIONS.md).
4. Start gateway and bot in two different terminals (both in `pgk_step2_gateway/`):
   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
   ```
   ```powershell
   python matrix_bot.py
   ```
5. Run the two demonstration flows above, or follow the detailed scripts in [docs/DEMO_VIDEO.md](docs/DEMO_VIDEO.md).
6. Run tests:
   ```powershell
   python -m pytest -q
   ```

**Data persistence:** SQLite in `pgk_step2_gateway/data/`; Docker HAPI volume persists across restarts. Never use `docker compose down -v` unless intentionally resetting synthetic data. The application is tested with only synthetic data.

## Adding a new external doctor (judge quick test)

The demo is **not limited to Eva Brandl and Stefan Kern**. A new external recipient can be added to the *synthetic identity issuer* by a trusted operator before sending a request. This does **not** create a PGK/Matrix account. The recipient only uses a browser.

From `pgk_step2_gateway/` with the Python environment activated:

```powershell
python tools/mock_eid_provider.py enroll --name "Dr. Nora Weiss"
```

The command prints **Subject ID** (e.g. `eid-demo-...`) and **One-time display of mock credential**. Keep both private; do not commit the credential or paste it into screenshots. To list provisioned people without exposing their credentials:

```powershell
python tools/mock_eid_provider.py list
```

The clinician then requests a document from Element Web:

```text
!request lab "Dr. Nora Weiss" nora.weiss@example.org
```

In Mailpit (`http://127.0.0.1:8025`), open that invitation. In the browser portal select **Other synthetic eID (issuer-provisioned)**, enter the issued **Subject ID** and **mock verification code** in their separate input fields, and submit. The recipient can then upload `pgk_step2_gateway/fixtures/step6/new-lab-maria.md`. Successful filing should produce two `Observation` resources, a `DocumentReference` and `Provenance` on the FHIR server and notify the clinician in Matrix. Verify the actual outcome and validator results locally.

**For security testing:** opening the same invitation with a different provisioned identity must be denied (HTTP 403), disclose no patient details, and log `MISDELIVERY_CAUGHT`. An external recipient cannot self-enroll from the public portal, since that would defeat the identity check. Provisioning is a **hackathon mock of an already established eID identity**, not real identity proofing, role verification or a PGK user registration. A *not-yet-provisioned* new name is intentionally rejected with HTTP 422 until the trusted operator enrolls it.

**Separate limitation:** adding a *new internal requesting doctor* to Matrix is not the same operation. The current demo allows only `PGK_ALLOWED_SENDER` in the configured Matrix room; it does not support self-service enrollment of additional internal doctors. Expanding that needs an authorization policy/allowlist and appropriate Matrix account and room permissions.

## Clinical data mapping and traceability

| Input | FHIR R4 resources | References and behavior |
|---|---|---|
| Laboratory Markdown | `Patient`, `Practitioner`, `DocumentReference`, one `Observation` per lab value, `Provenance` | `Observation.subject` and `DocumentReference.subject` → `Patient`; `Observation.derivedFrom` → `DocumentReference`; `Provenance.target` → the document and observations; sender is represented by `Practitioner`. Each test value uses the LOINC code in the supplied Markdown; known names are normalized to validator-approved displays; unknown displays are omitted rather than guessed. |
| Rehab Markdown | `Patient`, `Practitioner`, `DocumentReference`, `Provenance` | `DocumentReference.content.attachment.data` contains the original Markdown; no `Observation` for this request. `Provenance` identifies the sender and records the simulated identity-check context. |

All resources in a filing are sent as one `transaction` Bundle with stable deterministic REST identifiers, allowing retries without creating additional resource IDs. Filing success creates one `ANSWER_FILED` audit event and a Matrix notification. The source Markdown is preserved separately so a clinician can trace back to the provided content.

**Validation evidence:** Earlier supplied lab scenario was run with the HL7 Validator against FHIR 4.0.1 and yielded **0 errors** for the laboratory transaction Bundle, with **1 non-blocking warning** concerning optional `Provenance.activity` coding. This is a past run, **not a claim that every new document is validated**. Re-run validation and record the actual output for this submission; see [metrics](docs/METRICS.md).

## Design decisions — answers to all five organizer questions

### 1. How does an outside person prove identity without being in the directory?

PGK/Matrix membership is not required. A link leads to a verification step backed by a **synthetic mock identity issuer**. The issuer gives an independently provisioned `subject_id`/credential; the gateway compares the verified subject to the expected person bound to the request. Credentials cannot be provisioned by the public recipient form. This simulates an independent eID provider and does **not** constitute real ID Austria verification.

### 2. Which identity check for each document type and why?

Both lab and rehab submissions use the same simulated identity check bound to the **named individual**: these contain sensitive clinical information, and a colleague is not automatically allowed to substitute for the specified recipient. A random short-lived invitation token alone is not sufficient proof. The permitted contact channel (email or SMS) is independent of clinical document type. Real deployment would need eID assurance levels, sender role verification and clinic-defined authorization policy.

### 3. Which FHIR resources are created and how do they reference one another and the patient?

The mapping and cross-references are described in the table above. We retain source text in `DocumentReference`, store lab values in LOINC-coded `Observation`, and use `Provenance.target` and `Provenance.agent` to record what was filed and by whom. `Provenance.recorded` captures the recording time; the synthetic identity-check method is documented in activity text and the audit log. The transaction is sent to HAPI FHIR R4.

### 4. How do we notice misdelivery?

**M1 wrong address:** the unintended recipient can open only a generic invitation; their mock eID subject fails the expected-person comparison before patient disclosure. **M2 forwarded email:** a colleague cannot authenticate as the named sender and their answer is not filed. **M3 wrong patient:** name and date of birth from the uploaded document are compared against the requested patient **before** creating clinical FHIR resources; the response is rejected and a warning is queued and delivered to Dr. Hofer in Matrix. Audit events record each mismatch. Document type mismatches and ambiguous parsing are likewise rejected. The scenario-specific evidence and status are collected in `docs/METRICS.md`.

### 5. Where does the service run?

The demo runs on a **clinic-controlled local host** alongside its Matrix endpoint and FHIR server. This keeps request state, identity binding and audit under the clinical operator's control. For production, the network-facing recipient portal should be placed behind an HTTPS reverse proxy or secured gateway, while the clinical FHIR store stays restricted to authorized internal services. A production installation needs additional threat modeling, authorization, encryption/storage policy and monitoring.

## Metrics and repeatable testing

The four published targets are: **0 FHIR validation errors; 0 installations and 0 PGK accounts with response in under 2 minutes; M1/M2/M3 caught (3/3); audit coverage of request sent, link opened, identity checked, answer sent, answer filed, misdelivery caught (6/6).**

See [docs/METRICS.md](docs/METRICS.md) for the measurement procedure and **actual results**. Use `python tools/report_metrics.py` from `pgk_step2_gateway/` to generate a timestamped report from the existing SQLite records; it never fabricates user timing or manual misdelivery outcomes. See [docs/OPERATIONS.md](docs/OPERATIONS.md) for commands and troubleshooting.

## Limitations

**Known limitations:** synthetic identity issuer instead of government eID; no real delivery to `.example` contacts; testing on documented Markdown table variants rather than arbitrary PDFs; single configured synthetic patient and no full master patient index; no true E2EE in the demo Matrix room; local HTTP services without production access control/HTTPS; clinical terminology authenticity for unfamiliar LOINC codes cannot be guaranteed solely by check-digit verification. Unknown/ambiguous input fails closed. These are hackathon prototype limitations, not claimed production capabilities.

## Acknowledgment

Built for the public [AIM Austria Track 2 interoperability challenge](https://github.com/AIM-Austria/TRACK-2-interoperability). All clinical data and identities used for testing are synthetic.
