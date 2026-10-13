"""Download a student's reference image and retain its submission batch ID."""
import argparse
import base64
import binascii
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError

if __package__:
    from .client import Client
else:
    from client import Client


def download(client, output):
    output = Path(output)
    if output.exists():
        raise ValueError(f'Output already exists: {output}; choose a new --output folder')
    while True:
        try:
            response = client.request('/api/reference/json')
            break
        except ValueError as exc:
            if not isinstance(exc.__cause__, HTTPError) or exc.__cause__.code != 423:
                raise
            print('Reference locked; retrying in 1 second.', flush=True)
            time.sleep(1)
    if not isinstance(response.get('batch_id'), str) or not response['batch_id']:
        raise ValueError('Server response is missing its batch ID')
    raw = base64.b64decode(response['image'], validate=True)
    output.mkdir(parents=True)
    (output / 'reference.json').write_text(json.dumps(response, indent=2) + '\n')
    (output / 'source.png').write_bytes(raw)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.2:8000')
    parser.add_argument('--output', default='reference-download', help='New folder for source.png and reference.json')
    args = parser.parse_args()
    try:
        output = download(Client(args.url), args.output)
    except (ValueError, KeyError, OSError, URLError, binascii.Error) as exc:
        parser.exit(1, f'Download failed: {exc}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Download cancelled.\n')
    print(f'Saved {output / "source.png"} and {output / "reference.json"}')


if __name__ == '__main__':
    main()
