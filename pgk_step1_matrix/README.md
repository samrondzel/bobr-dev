# PGK Hackathon — Step 1: Matrix + Scenarios + Misdelivery

Ready-to-run **local-only** Matrix learning stack and a minimum bot smoke test. This is *not* a complete solution or a secure clinical deployment.

## Prerequisites

- Docker Desktop with Compose v2 running (on Windows, start Docker Desktop).
- Python 3.10+ for `enable_registration.py` and `matrix_smoke.py` (Python scripts have no third-party dependencies).
- A modern web browser.

## Start Synapse and Element

Open a terminal inside the `matrix` directory:

```bash
cd matrix
# Generate Synapse config and a persistent Docker volume. First time only:
docker compose run --rm --no-deps synapse generate
# Add random local test registration secret; it is never printed:
python enable_registration.py
# Start both services:
docker compose up -d
# Check server status:
docker compose ps
```

Open `http://localhost:8008/_matrix/client/versions`: JSON means Synapse responds.
Open `http://localhost:8080`: Element Web should load.

### Create two local users

Run this **twice** and follow the interactive prompts (use unique test-only passwords):

```bash
docker compose exec synapse register_new_matrix_user -c /data/homeserver.yaml http://localhost:8008
```

1. `lena.hofer` (admin: no)
2. `pgkbot` (admin: no)

These generate Matrix IDs `@lena.hofer:klinikum.example` and `@pgkbot:klinikum.example`.

### Create test room

1. In `http://localhost:8080`, log in as `lena.hofer` (server should be set to `http://localhost:8008`).
2. Create a **new room**, e.g. `Document Requests`, and **turn encryption OFF during room creation**. In many Matrix clients encryption cannot be switched off after creation.
3. Invite `@pgkbot:klinikum.example`.
4. Get the room ID (Element: room settings -> Advanced -> internal room ID), e.g. `!abc123:klinikum.example`.

### Run the smoke test

From inside `matrix`, in another terminal:

```bash
python matrix_smoke.py
```

- Enter username `pgkbot`, its password, and the copied room ID.
- Script logs in, joins the invited room, posts `PGK test bot connected ...` and waits for events.
- Back in Element Web, as Lena, type `!request lab eva.brandl@labor-kanal.example`.
- Expect script output `-> Command received! Next stage: forward to FastAPI.`
- Press Ctrl+C to exit.

**Important:** This test only proves Matrix connectivity. No email, patient data, identity check, FHIR or auditing is implemented yet.

## Common problems

- `docker` not found: install/start Docker Desktop.
- Registration error: confirm `python enable_registration.py` ran; inspect `docker compose logs synapse`.
- Element cannot connect: verify `http://localhost:8008/_matrix/client/versions` and browser developer console; services must be running locally.
- Bot cannot join: make sure `@pgkbot:klinikum.example` was invited to the correct room.
- Bot gets no message text: make sure the test room is unencrypted; the smoke bot is intentionally plaintext-only.
- Port 8008 or 8080 occupied: change the host-side mapping and Element's `base_url` accordingly.

## Security / scope

- Both services are bound to `127.0.0.1` (local host); Synapse is HTTP for local test only. HTTPS is mandatory for remote deployment.
- Do not commit real credentials, access tokens, invite tokens or Synapse data volumes. All scenario data must be synthetic.
- If using WSL/Docker on a different machine, `localhost` may need to be replaced and access secured.
- Matrix IDs are linked to the server name chosen at generation time, which is not trivial to change afterward; use the disposable Docker volume for this workshop.

Read [docs/SCENARIOS_AND_SECURITY.md](docs/SCENARIOS_AND_SECURITY.md) for our analysis, API contract, checks and requirements checklist.
