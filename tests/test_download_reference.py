import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from challenge.download_reference import download


class DownloadReferenceTests(unittest.TestCase):
    def test_wait_save_and_refuse_overwrite(self):
        locked = ValueError('Locked')
        locked.__cause__ = HTTPError('http://localhost', 423, 'Locked', {}, None)
        response = {'batch_id': 'batch-1', 'image': base64.b64encode(b'image bytes').decode()}
        client = Mock()
        client.request.side_effect = [locked, response]
        with tempfile.TemporaryDirectory() as directory, patch('challenge.download_reference.time.sleep') as sleep:
            output = Path(directory) / 'download'
            download(client, output)
            sleep.assert_called_once_with(1)
            self.assertEqual((output / 'source.png').read_bytes(), b'image bytes')
            self.assertEqual(json.loads((output / 'reference.json').read_text()), response)
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                download(client, output)
            self.assertEqual(client.request.call_count, 2)

    def test_authentication_failure_is_not_retried(self):
        client = Mock()
        client.request.side_effect = ValueError('Invalid token')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Invalid token'):
                download(client, Path(directory) / 'download')
            client.request.assert_called_once()
