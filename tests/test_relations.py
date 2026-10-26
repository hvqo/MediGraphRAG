import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app.main import create_app


class RelationTests(unittest.TestCase):
    def test_review_required_path_and_source_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(folder))
            doc = client.post(
                "/documents/text", json={"title": "关系软件测试", "text": "测试标签甲关联标签乙，仅为软件测试声明。"}
            ).json()
            chunk = client.get("/documents/" + doc["id"]).json()["chunks"][0]
            data = {
                "subject": "标签甲",
                "predicate": "关联",
                "object": "标签乙",
                "evidence_id": chunk["id"],
                "quote": chunk["text"],
            }
            self.assertEqual(client.post("/relations", json={**data, "quote": "不存在的原文"}).status_code, 422)
            row = client.post("/relations", json=data).json()
            self.assertEqual(client.post("/relations/paths", json={"query": "标签甲"}).json()["paths"], [])
            client.post("/relations/" + row["id"] + "/review", json={"status": "approved"})
            path = client.post("/relations/paths", json={"query": "标签甲"}).json()["paths"][0]
            self.assertEqual(path[0]["quote"], chunk["text"])
            result = client.post("/search", json={"query": "标签甲", "mode": "graph"}).json()
            self.assertEqual(result["items"][0]["id"], chunk["id"])
            self.assertEqual(result["mode"], "reviewed_relations")
            client.delete("/documents/" + doc["id"])
            self.assertEqual(client.get("/relations").json()[0]["effective_status"], "outdated")
            self.assertEqual(
                client.post("/relations/" + row["id"] + "/review", json={"status": "approved"}).status_code, 422
            )
            self.assertEqual(client.post("/relations/paths", json={"query": "标签甲"}).json()["paths"], [])

    def test_unavailable_vector_never_reports_keyword_as_vector(self):
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(folder))
            client.post("/documents/text", json={"title": "软件测试", "text": "测试关键词仅用于验收。"})
            result = client.post("/search", json={"query": "测试", "mode": "vector"}).json()
            self.assertEqual(result["mode"], "unavailable")
            self.assertEqual(result["items"], [])
