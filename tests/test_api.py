import base64
import io
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pathlib import Path
from openpyxl import load_workbook
from challenge.demo import initialize

try:
    from fastapi.testclient import TestClient
    from challenge.api import create_app
except ModuleNotFoundError:
    TestClient = None


@unittest.skipIf(TestClient is None, 'Install requirements-api.txt')
class FastAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = initialize(self.tmp.name)
        self.client = TestClient(create_app(self.tmp.name))
        self.client.__enter__()
        self.headers = {'Authorization': 'Bearer ' + self.config['teams']['team_demo']}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_download_edit_upload_and_excel(self):
        with patch('challenge.store.time.time', return_value=1000):
            response = self.client.get('/api/reference/json', headers=self.headers)
            self.assertEqual(response.status_code, 423)
        with patch('challenge.store.time.time', return_value=1030):
            response = self.client.get('/api/reference/json', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            batch = response.json()
            with Image.open(io.BytesIO(base64.b64decode(batch['image']))) as image:
                self.assertEqual(image.size, (batch['image_width'], batch['image_height']))
            self.assertEqual(batch['image_url'], '/api/reference/json')
        edited = io.BytesIO()
        Image.new('RGB', (batch['image_width'], batch['image_height']), 'red').save(edited, format='PNG')
        payload = {'batch_id': batch['batch_id'], 'edited_image': base64.b64encode(edited.getvalue()).decode()}
        result = self.client.post('/api/reference/submissions', headers=self.headers, json=payload)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertTrue(result.json()['excel_updated'])
        self.assertEqual(self.client.post('/api/reference/submissions', headers=self.headers, json=payload).status_code, 400)
        book = load_workbook(Path(self.tmp.name) / 'results.xlsx')
        try:
            self.assertEqual(book['Reference uploads']['A2'].value, batch['batch_id'])
        finally:
            book.close()

    def test_auth_validation_limits_and_docs(self):
        for endpoint in ('/api/reference/json',):
            self.assertEqual(self.client.get(endpoint).status_code, 401)
            self.assertEqual(self.client.get(endpoint, headers={'Authorization': 'Bearer invalid'}).status_code, 401)
        self.assertEqual(self.client.post('/api/reference/submissions', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/reference/submissions', headers=self.headers, json={}).status_code, 400)
        self.assertEqual(self.client.post('/api/reference/submissions', headers=self.headers, content='bad').status_code, 415)
        with patch('challenge.api.MAX_BODY', 8):
            response = self.client.post('/api/reference/submissions', headers=self.headers, json={'batch_id': 'too-big'})
            self.assertEqual(response.status_code, 413)
        response = self.client.post('/api/reference/submissions', headers=self.headers,
                                    json={'batch_id': 'unknown', 'edited_image': 'bad'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get('/docs').status_code, 200)
        schema = self.client.get('/openapi.json').json()
        self.assertIn('requestBody', schema['paths']['/api/reference/submissions']['post'])
        self.assertEqual(set(schema['paths']), {'/api/reference/json', '/api/reference/submissions'})
        for endpoint in ('/', '/health', '/api/config', '/api/reference', '/api/reference/image', '/api/results.xlsx'):
            self.assertEqual(self.client.get(endpoint, headers=self.headers).status_code, 404)
