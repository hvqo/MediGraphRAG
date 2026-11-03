import asyncio
import tempfile
import unittest
from unittest.mock import patch
import httpx
from backend.app.config import SettingsStore, SettingsUpdate
from backend.app.llm import ModelClient
from backend.app.storage import Database


class ModelTransportTests(unittest.TestCase):
    def test_vision_records_model_and_count_without_storing_image_payload(self):
        import json

        real_client = httpx.AsyncClient
        captured = []

        def handle(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"message": {"content": '{"text":"fixture"}'}})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with tempfile.TemporaryDirectory() as folder, patch("backend.app.llm.httpx.AsyncClient", side_effect=factory):
            store = SettingsStore(folder)
            store.update(
                SettingsUpdate(provider="cloud", cloud_base_url="https://text.invalid/v1", cloud_model="text-model")
            )
            model = ModelClient(store, Database(folder))
            asyncio.run(model.vision_json("read source", "extract", ["private-image-payload"]))
            self.assertEqual(captured[0]["messages"][-1]["images"], ["private-image-payload"])
            trace = model.db.rows("SELECT * FROM traces")[0]
            self.assertEqual(trace["model"], "qwen2.5vl:7b")
            self.assertEqual(json.loads(trace["input"])["image_count"], 1)
            self.assertNotIn("private-image-payload", str(trace))

    def test_independent_review_and_trace_replay_never_store_key(self):
        real_client = httpx.AsyncClient
        requests = []

        def handle(request):
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": '{"checked":true}'}}],
                    "usage": {"prompt_tokens": 12, "completion_tokens": 5},
                },
            )

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("backend.app.llm.httpx.AsyncClient", side_effect=factory),
        ):
            store, db = SettingsStore(directory), Database(directory)
            store.update(
                SettingsUpdate(
                    cloud_base_url="https://review.invalid/v1",
                    cloud_model="generator",
                    review_provider="cloud",
                    review_model="reviewer",
                    cloud_api_key="never-store-this-key",
                )
            )
            model = ModelClient(store, db).snapshot("review", "option-review-v2")
            asyncio.run(model.json("test system", "test prompt"))
            import json

            self.assertEqual(json.loads(requests[0].content)["model"], "reviewer")
            traces = db.rows("SELECT * FROM traces")
            self.assertEqual(traces[0]["input_tokens"], 12)
            self.assertEqual(traces[0]["output_tokens"], 5)
            self.assertNotIn("never-store-this-key", str(traces))
            self.assertEqual(traces[0]["role"], "review")

    def test_local_and_cloud_share_structured_protocol_without_leaking_key(self):
        real_client = httpx.AsyncClient
        requests = []

        def handle(request):
            requests.append(request)
            if request.url.path == "/api/chat":
                return httpx.Response(200, json={"message": {"content": '{"value":"local"}'}})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"value":"cloud"}'}}]})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("backend.app.llm.httpx.AsyncClient", side_effect=factory),
        ):
            store = SettingsStore(directory)
            model = ModelClient(store)
            self.assertEqual(asyncio.run(model.json("test", "test")), {"value": "local"})
            store.update(
                SettingsUpdate(
                    provider="cloud",
                    cloud_base_url="https://test.invalid/v1",
                    cloud_model="medical-test",
                    cloud_api_key="private-key",
                )
            )
            self.assertEqual(asyncio.run(model.json("test", "test")), {"value": "cloud"})
            self.assertEqual(requests[1].headers["authorization"], "Bearer private-key")
            self.assertNotIn("private-key", str(store.public()))
