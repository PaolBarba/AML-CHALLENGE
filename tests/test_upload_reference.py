import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from challenge.upload_reference import upload


class UploadReferenceTests(unittest.TestCase):
    def test_sends_saved_batch_and_edited_image(self):
        client = Mock()
        client.request.return_value = {'status': 'accepted'}
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / 'reference.json'
            image = Path(directory) / 'edited.png'
            reference.write_text(json.dumps({'batch_id': 'batch-1'}))
            image.write_bytes(b'edited image')
            self.assertEqual(upload(client, reference, image), {'status': 'accepted'})
            client.request.assert_called_once_with('/api/reference/submissions', {
                'batch_id': 'batch-1',
                'edited_image': base64.b64encode(b'edited image').decode('ascii'),
            })

    def test_invalid_reference_does_not_submit(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / 'reference.json'
            for invalid in ({}, {'batch_id': ''}, []):
                reference.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, 'batch_id'):
                    upload(client, reference, 'missing.png')
            client.request.assert_not_called()
