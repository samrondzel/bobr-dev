"""Export an accepted submission as Bundle + individual FHIR resources for HL7 CLI.

Usage: python tools/export_fhir.py req_abcdef...  (from pgk_step2_gateway/)
Reads existing PGK_BOT_SECRET from .env. Works whether HAPI is online or not.
"""
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].startswith('req_'):
        raise SystemExit('Usage: python tools/export_fhir.py req_YOUR_ID')
    secret = os.getenv('PGK_BOT_SECRET')
    if not secret:
        raise SystemExit('PGK_BOT_SECRET is not configured')
    url = os.getenv('PGK_GATEWAY_URL', 'http://127.0.0.1:8000').rstrip('/')
    req = Request(url + '/internal/fhir/export/' + sys.argv[1],
                  headers={'X-Bot-Secret': secret})
    with urlopen(req, timeout=10) as response:
        bundle = json.load(response)
    target = ROOT / 'fhir-validation' / sys.argv[1]
    target.mkdir(parents=True, exist_ok=True)
    (target/'bundle.json').write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding='utf-8')
    for n, entry in enumerate(bundle['entry'], 1):
        resource = entry['resource']
        path = target / f'{n:02d}-{resource["resourceType"]}.json'
        path.write_text(json.dumps(resource, indent=2, ensure_ascii=False), encoding='utf-8')
    print('FHIR resources exported to:', target)
    print('For each *.json use HL7 Validator: java -jar validator_cli.jar FILE -version 4.0.1')


if __name__ == '__main__':
    main()
