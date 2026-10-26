import asyncio
import tempfile
import unittest
from unittest.mock import patch
import httpx
from backend.app.config import SettingsStore, SettingsUpdate
from backend.app.llm import ModelClient


class ModelTransportTests(unittest.TestCase):
    def test_local_and_cloud_share_structured_protocol_without_leaking_key(self):
        real_client = httpx.AsyncClient
        requests = []
        def handle(request):
            requests.append(request)
            if request.url.path == '/api/chat':
                return httpx.Response(200, json={'message': {'content': '{"value":"local"}'}})
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"value":"cloud"}'}}]})
        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch('backend.app.llm.httpx.AsyncClient', side_effect=factory):
            store = SettingsStore(directory)
            model = ModelClient(store)
            self.assertEqual(asyncio.run(model.json('test', 'test')), {'value': 'local'})
            store.update(SettingsUpdate(provider='cloud', cloud_base_url='https://test.invalid/v1', cloud_model='medical-test', cloud_api_key='private-key'))
            self.assertEqual(asyncio.run(model.json('test', 'test')), {'value': 'cloud'})
            self.assertEqual(requests[1].headers['authorization'], 'Bearer private-key')
            self.assertNotIn('private-key', str(store.public()))
