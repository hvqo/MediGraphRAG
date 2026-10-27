import io
import tempfile
import unittest
import zipfile
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.questions import Question
from backend.app.storage import Database


class ProvenanceTests(unittest.TestCase):
    def test_additive_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Database(directory)
            second = Database(directory)
            self.assertEqual(len(second.rows("SELECT * FROM schema_migrations")), 5)
            with first.connect() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)

    def test_version_change_retires_old_evidence_and_flags_question(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            client = TestClient(app)
            old = client.post(
                "/documents/text", json={"title": "旧测试版本", "text": "糖尿病是旧版软件验收标签，不作医学依据。"}
            ).json()
            new = client.post(
                "/documents/text", json={"title": "新测试版本", "text": "高血压是新版软件验收标签，不作医学依据。"}
            ).json()
            evidence = client.get("/documents/" + old["id"]).json()["chunks"][0]
            question = Question(
                topic="软件验收中哪个标签来自旧版资料？",
                options=dict(zip("ABCD", ["旧版标签", "其他乙", "其他丙", "其他丁"])),
                answer=["A"],
                analysis="软件测试解析。",
                citations=[{"evidence_id": evidence["id"], "quote": evidence["text"]}],
            )
            identifier = app.state.questions.save(question)
            client.post("/questions/" + identifier + "/review", json={"status": "approved"})
            response = client.post("/documents/" + new["id"] + "/version", json={"predecessor": old["id"]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["impact"]["questions"][0]["id"], identifier)
            row = client.get("/questions/" + identifier).json()
            self.assertFalse(row["sources_valid"])
            self.assertEqual(row["status"], "pending_review")
            self.assertEqual(client.post("/search", json={"query": "糖尿病"}).json()["items"], [])
            self.assertFalse(client.get("/documents/" + old["id"] + "/reader").json()["active"])

    def test_docx_table_structure_and_rechunk(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(directory))
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>标签</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>编号</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
                )
            result = client.post("/documents/upload", files={"file": ("表格.docx", stream.getvalue())}).json()
            row = client.get("/documents/" + result["id"]).json()
            self.assertEqual(row["chunks"][0]["kind"], "table")
            self.assertIn("| 标签 | 编号 |", row["chunks"][0]["text"])
            self.assertEqual(
                client.post("/documents/" + result["id"] + "/rechunk", json={"size": 300, "overlap": 40}).status_code,
                200,
            )
            self.assertEqual(
                client.put("/documents/" + result["id"] + "/metadata", json={"edition": "测试版", "year": 2026}).json()[
                    "metadata"
                ]["edition"],
                "测试版",
            )
