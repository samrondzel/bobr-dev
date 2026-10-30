"""Minimal Matrix client smoke test. Uses Python standard library only.

Logs in as the test bot, joins an invited room, sends a message,
and prints new plaintext messages received in that room.
"""
import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

BASE = os.getenv('MATRIX_URL', 'http://localhost:8008').rstrip('/')


def api(method, endpoint, *, token=None, payload=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = Request(BASE + endpoint, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=40) as response:
            data = response.read()
            return json.loads(data) if data else {}
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Matrix HTTP {exc.code}: {detail}') from exc
    except URLError as exc:
        raise RuntimeError(f'Cannot reach {BASE}: {exc.reason}') from exc


def main():
    print('PGK Matrix smoke test. For SYNTHETIC data only.')
    username = input('Bot local username [pgkbot]: ').strip() or 'pgkbot'
    password = getpass.getpass('Bot password (not echoed): ')
    room_id = input('Room ID (copy from Element room settings): ').strip()
    if not room_id:
        raise SystemExit('Room ID is required.')

    login = api('POST', '/_matrix/client/v3/login', payload={
        'type': 'm.login.password',
        'identifier': {'type': 'm.id.user', 'user': username},
        'password': password,
    })
    token, my_id = login['access_token'], login['user_id']
    print('Logged in as', my_id)

    encoded_room = quote(room_id, safe='')
    api('POST', '/_matrix/client/v3/join/' + encoded_room, token=token, payload={})
    print('Joined room:', room_id)
    sync_url = '/_matrix/client/v3/sync?' + urlencode({'timeout': 0})
    since = api('GET', sync_url, token=token)['next_batch']

    send_url = (f'/_matrix/client/v3/rooms/{encoded_room}/send/'
                f'm.room.message/{uuid4().hex}')
    api('PUT', send_url, token=token, payload={
        'msgtype': 'm.text',
        'body': 'PGK test bot connected. Type !request in this room.',
    })
    print('Message sent. Listening for new messages (Ctrl+C to stop)...')

    while True:
        params = urlencode({'since': since, 'timeout': 15000})
        page = api('GET', '/_matrix/client/v3/sync?' + params, token=token)
        since = page['next_batch']
        rooms = page.get('rooms', {}).get('join', {})
        events = rooms.get(room_id, {}).get('timeline', {}).get('events', [])
        for event in events:
            if event.get('type') != 'm.room.message' or event.get('sender') == my_id:
                continue
            content = event.get('content', {})
            if content.get('msgtype') != 'm.text':
                continue
            print(f"{event.get('sender')}: {content.get('body')}")
            if content.get('body', '').startswith('!request'):
                print('-> Command received! Next stage: forward to FastAPI.')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped.')
    except (RuntimeError, KeyError) as error:
        print('ERROR:', error, file=sys.stderr)
        raise SystemExit(1)
