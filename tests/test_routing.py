import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app.main import create_app


class RoutingTests(unittest.TestCase):
    def test_direct_question_avoids_graph_and_relational_question_uses_path(self):
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(folder))
            documents = []
            for text in ["软件节点甲连接软件节点乙。", "软件节点乙连接软件节点丙。"]:
                doc = client.post("/documents/text", json={"title": "软件验证", "text": text}).json()
                documents.append(client.get("/documents/" + doc["id"]).json())
            for i, (subject, obj) in enumerate([("软件节点甲", "软件节点乙"), ("软件节点乙", "软件节点丙")]):
                chunk = documents[i]["chunks"][0]
                row = client.post(
                    "/relations",
                    json={
                        "subject": subject,
                        "predicate": "连接",
                        "object": obj,
                        "evidence_id": chunk["id"],
                        "quote": chunk["text"],
                    },
                ).json()
                client.post("/relations/" + row["id"] + "/review", json={"status": "approved"})
            fast = client.post("/search", json={"query": "软件节点甲是什么"}).json()
            self.assertEqual(fast["requested_mode"], "auto")
            self.assertEqual(fast["routing"]["selected"], "fast")
            self.assertFalse(fast["routing"]["deep_attempted"])
            deep = client.post("/search", json={"query": "软件节点甲关联路径是什么"}).json()
            self.assertEqual(deep["routing"]["selected"], "deep")
            self.assertTrue(deep["routing"]["graph_used"])
            self.assertTrue(any(len(path) == 2 for path in deep["paths"]))
            # Current-chunk scope must never leak another document through graph path payloads.
            scoped = client.post(
                "/search", json={"query": "软件节点甲关联路径", "evidence_ids": [documents[0]["chunks"][0]["id"]]}
            ).json()
            self.assertTrue(
                all(edge["evidence_id"] == documents[0]["chunks"][0]["id"] for path in scoped["paths"] for edge in path)
            )
            client.delete("/documents/" + documents[0]["id"])
            after = client.post("/search", json={"query": "软件节点甲关联路径"}).json()
            self.assertFalse(after["routing"]["graph_used"])

    def test_no_graph_falls_back_and_empty_ask_never_calls_model(self):
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(folder))
            answer = client.post("/ask", json={"query": "比较不存在的资料"}).json()
            self.assertEqual(answer["status"], "insufficient_evidence")
            self.assertEqual(answer["retrieval"]["routing"]["selected"], "fast")
            self.assertIn("尚无已审核关系", answer["retrieval"]["routing"]["fallback"])
            self.assertEqual(client.get("/traces").json(), [])

    def test_explicit_strategy_override_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            client = TestClient(create_app(folder))
            doc = client.post("/documents/text", json={"title": "软件验证", "text": "软件节点甲测试原文。"}).json()
            result = client.post("/search", json={"query": "软件节点甲", "mode": "keyword"}).json()
            self.assertEqual(result["mode"], "keyword")
            self.assertNotIn("routing", result)
            self.assertEqual(result["items"][0]["document_id"], doc["id"])
