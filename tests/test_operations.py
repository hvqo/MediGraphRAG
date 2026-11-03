import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from PIL import Image
from backend.app.main import create_app

TEXT = "软件测试中的糖尿病是索引标签，不代表诊疗知识。软件标签的编号为 TEST-001。"


class Model:
    async def vision_json(self, *args):
        return {"text": TEXT, "description": "", "warnings": []}

    async def json(self, system, prompt):
        if "从资料提炼" in prompt:
            values = json.JSONDecoder().raw_decode(prompt.split("资料：", 1)[1])[0]
            return {
                "points": [
                    {
                        "title": "软件标签编号",
                        "text": "只考察软件验收编号",
                        "citations": [{"evidence_id": values[0]["evidence_id"], "quote": values[0]["text"]}],
                    }
                ]
            }
        if "独立审题环节" in prompt:
            return {
                "supported": True,
                "answer_valid": True,
                "ambiguous": False,
                "leaks_answer": False,
                "reason": "软件测试审核理由",
                "options": {
                    key: {
                        "correct": key == "A",
                        "reason": "软件测试逐项判断理由",
                        "citations": self.question["citations"],
                    }
                    for key in "ABCD"
                },
            }
        values = json.JSONDecoder().raw_decode(prompt.split("资料：", 1)[1])[0]
        self.question = {
            "topic": "软件验收中索引标签的编号是什么？",
            "options": {"A": "TEST-001", "B": "TEST-002", "C": "TEST-003", "D": "TEST-004"},
            "answer": ["A"],
            "analysis": "根据软件原文确定编号，不构成医学知识。",
            "citations": [{"evidence_id": values[0]["evidence_id"], "quote": values[0]["text"]}],
            "question_type": "single_choice",
            "difficulty": "medium",
        }
        return self.question


def finished(client, identifier):
    for _ in range(200):
        row = client.get("/workspace/operations/" + identifier).json()
        if row["status"] in ["completed", "failed"]:
            return row
        time.sleep(0.02)
    raise AssertionError(row)


class OperationTests(unittest.TestCase):
    def test_english_terms_archive_without_becoming_approved_medical_assertions(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch(
                "backend.app.operations.model_paths", return_value=(Path(folder) / "missing", Path(folder) / "missing")
            ),
            TestClient(create_app(folder)) as client,
        ):
            client.app.state.model = Model()
            text = "Software-only index fixtures mention myocardial and insulin. These are fictional acceptance labels, not medical facts."
            row = client.post(
                "/workspace/submit",
                data={"instruction": "提炼知识点"},
                files=[("files", ("fixture.txt", text.encode()))],
            ).json()
            self.assertEqual(finished(client, row["id"])["status"], "completed")
            relations = client.get("/relations").json()
            self.assertTrue(relations)
            self.assertTrue(all(r["object"] in r["quote"] and r["status"] == "literal_verified" for r in relations))
            result = client.post("/search", json={"query": "relationship myocardial insulin"}).json()
            self.assertFalse(result["routing"]["graph_used"])

    def test_plain_generation_requests_need_no_mode_selection(self):
        from backend.app.operations import intent, generation_options

        for text in ["生成3道题", "请根据这个PDF出5道单选题", "帮我生成一套试卷", "generate 3 questions"]:
            self.assertEqual(intent(text), "generate", text)
        self.assertEqual(intent("这个术语是什么意思"), "ask")
        self.assertEqual(intent("总结这份资料"), "summarize")
        self.assertEqual(
            generation_options("生成五道基础多选题"),
            {"count": 5, "question_type": "multiple_choice", "difficulty": "easy"},
        )
        self.assertEqual(generation_options("生成十二道病例题")["count"], 10)

    def test_batch_upload_image_word_and_text_generates_and_archives(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch(
                "backend.app.operations.model_paths", return_value=(Path(folder) / "missing", Path(folder) / "missing")
            ),
            TestClient(create_app(folder)) as client,
        ):
            model = Model()
            client.app.state.model = model
            client.app.state.jobs.model = model
            image = io.BytesIO()
            Image.new("RGB", (150, 80), "white").save(image, format="PNG")
            word = io.BytesIO()
            with zipfile.ZipFile(word, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{TEXT}</w:t></w:r></w:p></w:body></w:document>',
                )
            response = client.post(
                "/workspace/submit",
                data={"instruction": "根据资料生成1道练习题"},
                files=[
                    ("files", ("图.png", image.getvalue(), "image/png")),
                    ("files", ("Word.docx", word.getvalue())),
                    ("files", ("说明.txt", TEXT.encode())),
                ],
            )
            self.assertEqual(response.status_code, 202)
            row = finished(client, response.json()["id"])
            self.assertEqual(row["status"], "completed")
            self.assertEqual(len(row["result"]["document_ids"]), 3)
            self.assertEqual(len(row["result"]["question_ids"]), 1)
            self.assertEqual(row["result"]["background"]["vectors"], "awaiting_model")
            self.assertEqual(row["result"]["background"]["graph"], "ready")
            self.assertTrue(any(r["status"] == "literal_verified" for r in client.get("/relations").json()))
            self.assertEqual(client.get("/questions").json()[0]["status"], "pending_review")
            self.assertTrue(all(Path(item["path"]).exists() for item in row["manifest"]))

    def test_personal_libraries_isolate_files_questions_and_operations(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder, personal=True)) as client:
            response = client.get("/profile")
            first = response.json()
            cookie = client.cookies.get("medigraph_library")
            doc = client.post("/documents/text", json={"title": "A的私有资料", "text": TEXT}).json()
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            client.cookies.clear()
            second = client.get("/profile").json()
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(client.get("/documents").json(), [])
            self.assertEqual(client.get("/documents/" + doc["id"]).status_code, 404)
            self.assertEqual(client.get("/workspace/operations").json(), [])
            client.cookies.clear()
            client.cookies.set("medigraph_library", cookie)
            self.assertEqual(client.get("/documents").json()[0]["title"], "A的私有资料")

    def test_cannot_scope_generation_to_another_personal_library(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder, personal=True)) as client:
            doc = client.post("/documents/text", json={"title": "私有", "text": TEXT}).json()
            client.cookies.clear()
            client.get("/profile")
            result = client.post("/search", json={"query": "糖尿病", "document_ids": [doc["id"]]}).json()
            self.assertEqual(result["items"], [])
