import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app.main import create_app


class SettingsTests(unittest.TestCase):
    def test_start_without_model_and_secret_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            self.assertEqual(client.get('/health').status_code, 200)
            self.assertEqual(client.get('/api/health').status_code, 200)
            payload = client.get('/settings').json()
            payload.pop('cloud_api_key_configured')
            payload.pop('cloud_api_key_from_environment')
            payload['cloud_api_key'] = 'test-private-value'
            response = client.put('/settings', json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('test-private-value', response.text)
            self.assertTrue(response.json()['cloud_api_key_configured'])
            self.assertTrue(TestClient(create_app(directory)).get('/settings').json()['cloud_api_key_configured'])

    def test_reject_embedded_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            self.assertEqual(client.put('/settings', json={'cloud_base_url': 'https://secret@example.org/v1'}).status_code, 422)
