import unittest
from backend.app.concepts import select_evidence


class ConceptCoverageTests(unittest.TestCase):
    def test_source_notes_are_excluded_but_later_body_is_included(self):
        chunks = [
            {
                "id": "cover",
                "document_id": "one",
                "text": "PubMed abstract, PMID 1\nSource: https://example.org\nFor software demonstration only",
            },
            {"id": "question", "document_id": "one", "text": "What is the result?"},
            {"id": "body", "document_id": "one", "text": "正文的受试者总数为219人，结果描述保留原文以供软件功能验证。"},
            {"id": "later", "document_id": "one", "text": "第十页还有一个容易在首段采样中丢失的教学知识点。"},
        ]
        selected, eligible = select_evidence(chunks)
        self.assertEqual([c["id"] for c in selected], ["body", "later"])
        self.assertEqual(eligible, 2)

    def test_sampling_covers_multiple_documents_and_their_ends(self):
        chunks = [
            {"id": f"{doc}-{i}", "document_id": doc, "text": "正文知识点。"}
            for doc in ["one", "two"]
            for i in range(10)
        ]
        selected, eligible = select_evidence(chunks, limit=4)
        self.assertEqual(eligible, 20)
        self.assertEqual({c["id"] for c in selected}, {"one-0", "one-9", "two-0", "two-9"})
