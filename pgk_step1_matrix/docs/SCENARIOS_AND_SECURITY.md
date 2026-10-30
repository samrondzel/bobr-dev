# Step 1 — Scenario, trust boundaries and test specification

Sources: `scenario/README.md`, `scenario/misdelivery.md` in AIM-Austria/TRACK-2-interoperability.

## Actors

- `@lena.hofer:klinikum.example` — doctor, internal Matrix user; requests results for Maria Beispiel.
- Dr. Eva Brandl — the **named** external lab physician, `eva.brandl@labor-kanal.example`.
- Stefan Kern — the **named** external rehab discharge manager, `+43 660 000 0101`.
- Maria Beispiel — FHIR Patient ID `maria-beispiel`, MRN `KB-000123`, born `1961-03-12`.
- A colleague is **not permitted** to answer on the named recipient's behalf.

## User journeys

### R1: Lab via email

1. Lena creates a lab request to Eva for Maria, using Matrix.
2. Gateway produces a one-use expiring invitation, logs `REQUEST_SENT`, and sends it to Mailpit (no PHI in email).
3. Eva opens link: `LINK_OPENED`; sees **no medical details** before authentication.
4. Simulated identity provider returns an authenticated identity; server matches the verified name to Eva: `IDENTITY_CHECKED`.
5. Eva uploads Markdown: `scenario/documents/lab-result-maria-beispiel.md`.
6. Server **parses document identity itself**, verifies name and birth date match Maria, parses 4 lab tests, validates and stores FHIR Observations + Provenance: `ANSWER_SENT`, `ANSWER_FILED`.
7. Lena receives Matrix notification.

### R2: Rehab via simulated SMS

Same request/security workflow for named recipient Stefan Kern. He uploads `scenario/documents/rehab-report-maria-beispiel.md`. Save as FHIR DocumentReference with attached text + Provenance and notify Lena.

## Mandatory negative tests — all use R1

- M1: mistyped `eva.brandl@labor-kanaI.example` (`I` uppercase, not `l` lowercase). Wrong recipient opens invitation. Verified identity != Eva. **Do not reveal patient or document type; do not allow answer; record audit failure.**
- M2: Eva forwards invitation to `kollege@labor-kanal.example`. The colleague opens link. Identity != Eva. **Block answer** (or flag the non-Eva sender to Lena and don't file as Eva). Record event.
- M3: Eva successfully authenticates, submits `scenario/documents/lab-result-max-beispiel.md`, patient Max Beispiel, born `1960-01-01`. **Do not file as Maria; notify Lena in Matrix; record event.**

A test counts as caught only when the required behaviour **and an audit entry** are demonstrated.

## Critical security decisions

- The invitation token is NOT proof of identity. Authenticate the named person separately.
- Dr. Hofer knows only name, role and contact: she cannot be assumed to know a national eID number. For the hackathon, simulated eID can assert verified legal name, which the gateway compares to the expected name. Real production must address identical names and role/organisation verification.
- The simulated identity must originate from an identity-provider/mock-test fixture, **not a free-text "type your own name" field**.
- Hide request details until verified: not only in email/SMS, but also on the pre-authenticated landing page.
- Compare the patient information extracted *from the uploaded Markdown* to the request's patient; not just the uploader's text-form declaration.
- Store generated request IDs, token digests (not plaintext tokens), expiration, expected recipient name/contact and patient reference. Do not log access tokens, raw invitation tokens or clinical content.
- Synthetic data only. This dev stack is HTTP on loopback, not remotely accessible production infrastructure.

## Recommended minimal model

`Request {request_id, matrix_room_id, requested_by_matrix_id, patient_fhir_id, patient_name, patient_birth_date, recipient_name, recipient_role, recipient_contact, channel, document_type, token_hash, expires_at, status}`

`Audit {request_id, actor_id, event_type, timestamp_utc, outcome, reason}`

Possible status flow:

`CREATED -> LINK_SENT -> LINK_OPENED -> IDENTITY_VERIFIED -> ANSWER_RECEIVED -> FILED`

Negative paths:

`IDENTITY_FAILED -> MISDELIVERY_CAUGHT` OR `PATIENT_MISMATCH -> MISDELIVERY_CAUGHT -> DOCTOR_NOTIFIED`

## Six audit events for scoring

`REQUEST_SENT`, `LINK_OPENED`, `IDENTITY_CHECKED`, `ANSWER_SENT`, `ANSWER_FILED`, `MISDELIVERY_CAUGHT`.

Each should record **who, what, when** and request ID. The last event occurs in a negative test.

## Suggested integration contract (next development stage)

- Matrix: `!request lab eva.brandl@labor-kanal.example` or `!request rehab +436600000101` (synthetic demo syntax; bot should allow only approved Matrix users).
- Bot -> backend: `POST /requests` with patient ref, recipient, channel, doc type, `matrix_room_id`, `requested_by_matrix_id`.
- Backend -> Mailpit / simulated SMS: invitation URL only, no PHI.
- Portal -> backend: `POST /requests/{id}/verify` (identity token from mock provider, not self-reported name).
- Portal -> backend: `POST /requests/{id}/submit` (Markdown file).
- Backend -> bot: `POST /internal/notifications` or an internal event queue to send status to the correct Matrix room.
- Bot -> Matrix: status messages. For M3, clearly state patient mismatch; avoid forwarding untrusted document content in the message.

## End-of-step-1 checklist

- [ ] Read scenario/README.md and scenario/misdelivery.md.
- [ ] Identify named recipients and the difference between contact proof and identity proof.
- [ ] Understand homeserver, room, user ID, bot, token, m.room.message and /sync.
- [ ] Start Synapse and Element locally (if Docker is available).
- [ ] Register `lena.hofer` and `pgkbot`.
- [ ] Create an UNENCRYPTED test room and invite `@pgkbot:klinikum.example`.
- [ ] Send a Matrix command and see it printed by the smoke-test bot.
- [ ] Agree API contract with backend teammate.
- [ ] Commit study notes and Matrix smoke files; exclude all secrets/config data volumes.
