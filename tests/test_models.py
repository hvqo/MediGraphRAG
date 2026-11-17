import asyncio
import tempfile
import unittest
from unittest.mock import patch
import httpx
from backend.app.config import SettingsStore, SettingsUpdate
from backend.app.llm import ModelClient
from backend.app.storage import Database


class ModelTransportTests(unittest.TestCase):
    def test_local_openai_compatible_backend_needs_no_cloud_key(self):
        import json

        real_client, requests = httpx.AsyncClient, []

        def handle(request):
            requests.append(request)
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "local-vision"}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"local"}'}}]})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with tempfile.TemporaryDirectory() as folder, patch("backend.app.llm.httpx.AsyncClient", side_effect=factory):
            store = SettingsStore(folder)
            store.update(
                SettingsUpdate(
                    provider="openai",
                    cloud_base_url="http://127.0.0.1:8081/v1",
                    cloud_model="local-vision",
                    vision_provider="openai",
                    vision_base_url="http://127.0.0.1:8081/v1",
                    vision_model="local-vision",
                )
            )
            model = ModelClient(store)
            self.assertTrue(asyncio.run(model.check())["ok"])
            self.assertEqual(asyncio.run(model.json("test", "test")), {"text": "local"})
            self.assertEqual(asyncio.run(model.vision_json("test", "test", ["image-data"])), {"text": "local"})
            self.assertTrue(all("authorization" not in r.headers for r in requests))
            self.assertEqual(
                json.loads(requests[-1].content)["messages"][-1]["content"][1]["image_url"]["url"],
                "data:image/jpeg;base64,image-data",
            )

    def test_independent_cloud_vision_uses_its_own_key_and_image_protocol(self):
        import json

        real_client, requests = httpx.AsyncClient, []

        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"text":"read"}'}}]})

        def factory(**kwargs):
            return real_client(transport=httpx.MockTransport(handle), **kwargs)

        with tempfile.TemporaryDirectory() as folder, patch("backend.app.llm.httpx.AsyncClient", side_effect=factory):
            store = SettingsStore(folder)
            store.update(
                SettingsUpdate(
                    cloud_api_key="text-secret",
                    vision_provider="cloud",
                    vision_base_url="https://vision.invalid/v1",
                    vision_model="vision-model",
                    vision_api_key="vision-secret",
                )
            )
            model = ModelClient(store, Database(folder))
            asyncio.run(model.vision_json("read", "extract", ["image-private"]))
            request = requests[0]
            self.assertEqual(str(request.url), "https://vision.invalid/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer vision-secret")
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "vision-model")
            self.assertEqual(
                payload["messages"][-1]["content"][1]["image_url"]["url"], "data:image/jpeg;base64,image-private"
            )
            self.assertEqual(store.key(), "text-secret")
            self.assertNotIn("secret", str(model.db.rows("SELECT * FROM traces")))
            self.assertNotIn("image-private", str(model.db.rows("SELECT * FROM traces")))
            # Saving unrelated settings preserves an independently saved visual credential.
            store.update(SettingsUpdate(vision_provider="cloud", vision_base_url="https://vision.invalid/v1"))
            self.assertEqual(store.role_key("vision"), "vision-secret")
            store.update(SettingsUpdate(vision_api_key=""))
            self.assertFalse(store.role_key("vision"))

    def test_old_ollama_is_reported_before_attempting_qwen3_vision(self):
        real_client = httpx.AsyncClient

        def factory(**kwargs):
            return real_client(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"version": "0.11.5"})), **kwargs
            )

        with tempfile.TemporaryDirectory() as folder, patch("backend.app.llm.httpx.AsyncClient", side_effect=factory):
            result = asyncio.run(ModelClient(SettingsStore(folder)).snapshot("vision").check())
            self.assertFalse(result["ok"])
            self.assertIn("0.12.7", result["message"])

    def test_truncated_model_response_cannot_be_treated_as_complete_ocr(self):
        from backend.app.llm import ModelError

        real_client = httpx.AsyncClient

        def factory(**kwargs):
            return real_client(
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, json={"message": {"content": '{"text":"only half"}'}, "done_reason": "length"}
                    )
                ),
                **kwargs,
            )

        with tempfile.TemporaryDirectory() as folder, patch("backend.app.llm.httpx.AsyncClient", side_effect=factory):
            with self.assertRaisesRegex(ModelError, "长度上限"):
                asyncio.run(ModelClient(SettingsStore(folder)).vision_json("read", "extract", ["private"]))

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
            self.assertEqual(trace["model"], "qwen3-vl:8b-instruct")
            self.assertEqual(captured[0]["keep_alive"], 0)
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
