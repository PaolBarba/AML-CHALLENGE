"""Submit an edited RGB PNG using a downloaded reference's batch ID."""
import argparse
import base64
import json
from pathlib import Path
from urllib.error import URLError

if __package__:
    from .client import Client
else:
    from client import Client


def upload(client, reference, image):
    reference = json.loads(Path(reference).read_text())
    if not isinstance(reference, dict) or not isinstance(reference.get('batch_id'), str) or not reference['batch_id']:
        raise ValueError('Reference JSON must contain the downloaded batch_id')
    payload = {
        'batch_id': reference['batch_id'],
        'edited_image': base64.b64encode(Path(image).read_bytes()).decode('ascii'),
    }
    return client.request('/api/reference/submissions', payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='Edited RGB PNG with the same dimensions as source.png')
    parser.add_argument('--reference', default='reference-download/reference.json')
    parser.add_argument('--url', default='http://127.0.0.2:8000')
    args = parser.parse_args()
    try:
        result = upload(Client(args.url), args.reference, args.image)
    except (ValueError, OSError, URLError) as exc:
        parser.exit(1, f'Upload failed: {exc}\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Upload interrupted; check submission status before retrying.\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
