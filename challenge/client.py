"""Small authenticated client shared by student and organizer tools."""
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class Client:
    def __init__(self, url, token=None):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use a plain http(s) server URL')
        self.url = url.rstrip('/')
        self.token = token or os.environ.get('CHALLENGE_TOKEN')
        if not self.token:
            raise ValueError('Set CHALLENGE_TOKEN to a team or organizer token')

    def request(self, path, payload=None, binary=False):
        if not path.startswith('/api/') or path.startswith('//'):
            raise ValueError('Client requests must use challenge API paths')
        request = Request(self.url + path, data=json.dumps(payload, allow_nan=False).encode() if payload is not None else None,
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ValueError(f'Challenge server rejected request ({exc.code}): {exc.read().decode()}') from exc
        return raw if binary else json.loads(raw)
