import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.evidence import answer_question
from backend.app.llm import ModelError
from backend.app.main import create_app


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)

    async def json(self, *args):
        return next(self.replies)


class RetrievalTests(unittest.TestCase):
    def test_vector_index_invalidates_after_document_change(self):
        import numpy as np

        def fake_embeddings(texts, device):
            return np.tile(np.array([[1.0, 0.0]], dtype="float32"), (len(texts), 1))

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("backend.app.retrieval.embed", side_effect=fake_embeddings),
        ):
            client = TestClient(create_app(directory))
            client.post("/documents/text", json={"title": "索引测试", "text": "糖尿病索引测试"})
            self.assertEqual(client.post("/indexes/build").status_code, 200)
            self.assertTrue(client.get("/indexes/status").json()["ready"])
            retriever = client.app.state.retriever
            metadata = json.loads(retriever.meta_path.read_text(encoding="utf-8"))
            metadata["model_signature"] = "changed-model"
            retriever.meta_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertFalse(client.get("/indexes/status").json()["ready"])
            self.assertEqual(client.post("/indexes/build").status_code, 200)
            client.post("/documents/text", json={"title": "新资料", "text": "高血压索引测试"})
            self.assertFalse(client.get("/indexes/status").json()["ready"])

    def test_chinese_search_and_citation_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            client.post(
                "/documents/text",
                json={"title": "软件测试资料", "text": "这是糖尿病与血糖的检索测试文本，不作为医学依据。"},
            )
            result = client.post("/search", json={"query": "糖尿病"}).json()
            self.assertEqual(len(result["items"]), 1)
            source = result["items"][0]
            response = {
                "blocks": [{"text": "测试回答", "citations": [{"evidence_id": source["id"], "quote": source["text"]}]}]
            }
            good = asyncio.run(answer_question(FakeModel([response, {"supported": True}]), "糖尿病", result))
            self.assertEqual(good["status"], "draft")
            response["blocks"][0]["citations"][0]["quote"] = "这是原文中不存在的引用"
            with self.assertRaises(ModelError):
                asyncio.run(answer_question(FakeModel([response]), "糖尿病", result))
            graph = client.post("/graph/search", json={"keyword": "糖尿病"}).json()
            self.assertTrue(all(edge["kind"] == "cooccurrence" for edge in graph["links"]))

    def test_no_evidence_never_calls_model(self):
        with tempfile.TemporaryDirectory() as directory:
            result = TestClient(create_app(directory)).post("/ask", json={"query": "不存在的知识"}).json()
            self.assertEqual(result["status"], "insufficient_evidence")

    def test_deleted_documents_are_not_retrievable(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            item = client.post("/documents/text", json={"title": "检索测试", "text": "糖尿病检索测试"}).json()
            client.delete("/documents/" + item["id"])
            self.assertEqual(client.post("/search", json={"query": "糖尿病"}).json()["items"], [])
