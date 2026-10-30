# PGK Hackathon — Step 2: Matrix -> FastAPI -> request -> email/SMS link

**Purpose:** Take the working Element+Synapse setup from Step 1 and make the `!request` command create a persisted request. A real email is captured in local Mailpit, or an SMS is recorded in a local dev outbox. The link opens a generic page with **no clinical details**.

This is a workshop prototype, **not a secure medical product**. Identity verification, document submission, FHIR and full misdelivery tests are **not implemented yet**.

## Directory placement

Put the folder `pgk_step2_gateway` next to `pgk_step1_matrix` in the root of your private hackathon repo:

```text
TRACK-2-interoperability/
  scenario/                  # supplied by organizers
  pgk_step1_matrix/matrix/   # Synapse + Element (already working)
  pgk_step2_gateway/         # this folder
    app/main.py
    matrix_bot.py
    tests/test_gateway.py
    compose.yaml
    .env.example
```

## Start on Windows PowerShell (or any terminal with equivalent commands)

1. Keep Synapse+Element running from the Step 1 compose file. **Stop the old `matrix_smoke.py` process** using Ctrl+C; the new bot will replace it.

2. In `pgk_step2_gateway/`, create a virtual environment, install dependencies, and copy config:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `.env` as `PGK_BOT_SECRET`. Set `PGK_ALLOWED_ROOM` to the actual `!roomid:klinikum.example` from Step 1. Keep `PGK_ALLOWED_SENDER` exactly `@lena.hofer:klinikum.example`. **Do not commit `.env`.**

Linux/macOS: `source .venv/bin/activate`, `cp .env.example .env`. For PowerShell execution-policy errors, use `Set-ExecutionPolicy -Scope Process Bypass` or skip activation and call `.venv\\Scripts\\python.exe` directly.

3. Start Mailpit in **another terminal** from `pgk_step2_gateway/`:

```powershell
docker compose up -d
```

Open `http://127.0.0.1:8025` (local mail capture dashboard).

4. Start FastAPI in a new terminal, with the virtualenv activated:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log
```

Open `http://127.0.0.1:8000/health` (expect `{"status":"ok","stage":"requests-only"}`). Also see generated API docs: `http://127.0.0.1:8000/docs`.

5. Start new Matrix bot in another terminal, with the virtualenv activated:

```powershell
python matrix_bot.py
```

Enter the `pgkbot` login and password you created in Step 1. The `.env` supplies the room ID and shared API secret; it does not store your Matrix password.

6. Back in Element (as Lena), post:

```text
!request lab "Dr. Eva Brandl" eva.brandl@labor-kanal.example
```

The previous short command also works: `!request lab eva.brandl@labor-kanal.example`.

Expected: bot replies with `req_...` and invitation status `sent`. The email appears at `http://127.0.0.1:8025`. Open its link. You should see the generic **Secure document request** page, without patient details. The API writes `REQUEST_CREATED`, `REQUEST_SENT`, and (on click) `LINK_OPENED` to SQLite.

Try the second scenario:

```text
!request rehab "Stefan Kern" "+43 660 000 0101"
```

The SMS is recorded locally (it is *not* sent externally). You can inspect it with PowerShell:

```powershell
$secret = ((Get-Content .env | Where-Object { $_ -match '^PGK_BOT_SECRET=' }) -split '=',2)[1]
Invoke-RestMethod -Uri http://127.0.0.1:8000/internal/dev/sms -Headers @{ 'X-Bot-Secret' = $secret }
```

## Automated tests

```powershell
python -m pytest -q
```

The tests cover: request creation, invitation privacy, click auditing, Matrix event idempotency, unauthorized sender/room rejection, SMS outbox, SMTP failure, command syntax, real outgoing email template, and invalid/expired link behavior.

## How the request flows

```text
Lena / Element Web
       |  !request lab ...
       v
Synapse (Matrix room event with sender, room_id, event_id)
       |
       v
matrix_bot.py  -- POST /internal/requests (X-Bot-Secret) --> FastAPI
       |                                                | 
       |                                                +-- SQLite: requests, audit_events
       |                                                +-- token_urlsafe(32), only sha256(token) stored
       |                                                +-- Mailpit SMTP or dev SMS outbox
       v
Matrix acknowledgement without invitation link

Outside recipient -> email/SMS link -> GET /r/{token}
                                         |
                                         +-- generic page, LINK_OPENED audit
```

### Key choices explained

- Matrix event ID is a **unique idempotency key**, so restarted/polled bot doesn't create two invitations for the same command.
- The API checks both an internal shared secret **and** expected Matrix sender/room; the bot obtains sender from Matrix event metadata, not from user-typed text.
- Recipient name is separate from email/phone: wrong-address M1 can be detected at identity-check stage even though the request was delivered to the wrong inbox.
- The invitation never includes patient name, date of birth, or document type. The token's hash, not raw token, is saved in SQLite.
- Token validity is 20 min, appropriate only for this demo. Actual production TTL and handling require a security review.
- The landing page does not permit uploads or reveal a patient until a later identity-verification step.
- **Not production-ready:** HTTP loopback only, plaintext Matrix room, no user identity verification yet, no file ingestion/FHIR. Never use real patient data. When deploying, use HTTPS, prevent token leakage into access logs, and handle secrets securely. The local Uvicorn command disables HTTP access logging to avoid printing bearer links into the terminal.

## Audit so far / next steps

Implemented (Step 2): `REQUEST_CREATED`, `REQUEST_SENT`, `LINK_OPENED`, `DELIVERY_FAILED` (if Mailpit down).

Still needed: `IDENTITY_CHECKED`, `ANSWER_SENT`, `ANSWER_FILED`, `MISDELIVERY_CAUGHT`, correct-patient validation and Matrix alert for M3, FHIR resource generation, HL7 validation.

The official metric specifies six audit checkpoints: request sent; link opened; identity checked; answer sent; answer filed; misdelivery caught. `REQUEST_CREATED` and `DELIVERY_FAILED` are internal extras.

## If something fails

- `request rejected`: check `.env` shared secret and exact `PGK_ALLOWED_ROOM`, backend running, bot restarted after editing `.env`.
- `invitation failed`: start Mailpit (`docker compose up -d`) and send a **new** Matrix command (the original failed event is intentionally not automatically retried in this version).
- No messages: ensure old smoke test is stopped; use unencrypted room and confirm the new bot is running.
- Port 8000 busy: inspect running processes or change both `PGK_GATEWAY_URL` and `PGK_PUBLIC_BASE_URL` alongside the Uvicorn port.
- PowerShell `!` and quoting: type request commands inside Element; not the PowerShell terminal.
