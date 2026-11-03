"""Reproducible Chinese retrieval smoke comparison, no medical accuracy claim or model call."""

import json
from pathlib import Path
import sys
import tempfile
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.main import create_app


def main():
    root = Path(__file__).resolve().parents[1]
    seed = json.loads((root / "docs/evaluation-seed.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
        ids = []
        for document in seed["documents"]:
            row = client.post("/documents/text", json=document).json()
            chunk = client.get("/documents/" + row["id"]).json()["chunks"][0]
            ids.append(chunk["id"])
            subject = document["text"].split("：")[1].split("标签")[0]
            relation = client.post(
                "/relations",
                json={
                    "subject": subject,
                    "predicate": "软件测试编号",
                    "object": document["text"].split("为 ")[1].split("。")[0],
                    "evidence_id": chunk["id"],
                    "quote": chunk["text"],
                    "conditions": "仅限软件测试标签，不是医学关系",
                },
            ).json()
            client.post(
                "/relations/" + relation["id"] + "/review",
                json={"status": "approved", "note": "非临床软件验收声明核对"},
            )
        suite = client.post(
            "/evaluations",
            json={
                "name": seed["name"],
                "samples": [
                    {"query": s["query"], "expected_evidence_ids": [ids[s["expected_document"]]]}
                    for s in seed["samples"]
                ],
            },
        ).json()
        response = client.post(
            "/evaluations/" + suite["id"] + "/run", json={"modes": ["keyword", "vector", "graph", "hybrid"], "top_k": 5}
        )
        response.raise_for_status()
        result = response.json()
        output = root / ".runtime/retrieval-benchmark.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "scope": seed["name"],
                    "metrics": result["report"]["metrics"],
                    "source_revision": result["report"]["source_revision"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
