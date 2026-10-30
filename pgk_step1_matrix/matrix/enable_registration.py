"""Add a local-only shared registration secret to generated Synapse config.

Run AFTER `docker compose run --rm --no-deps synapse generate`.
This does not enable open public registration.
"""
from pathlib import Path
import subprocess

script = r'''
from pathlib import Path
import secrets
import yaml
p = Path('/data/homeserver.yaml')
if not p.exists():
    raise SystemExit('Missing /data/homeserver.yaml: run Synapse generate first')
data = yaml.safe_load(p.read_text(encoding='utf-8'))
if not data.get('registration_shared_secret'):
    data['registration_shared_secret'] = secrets.token_hex(32)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding='utf-8')
print('Registration secret configured (value hidden).')
'''
subprocess.run(
    ['docker', 'compose', 'run', '--rm', '--no-deps', '--entrypoint', 'python', 'synapse', '-c', script],
    cwd=Path(__file__).resolve().parent,
    check=True,
)
