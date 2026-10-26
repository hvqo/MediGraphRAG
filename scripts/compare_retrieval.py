"""Auditable retrieval comparisons; synthetic ground truth and weak legacy lookup stay separate."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import ROOT, SettingsUpdate
from backend.app.main import create_app
from backend.app.relations import RelationInput, RelationReview
from backend.app.retrieval import revision
from backend.app.storage import now


def functional(app):
    samples = []
    for i in range(1, 9):
        root, mid, end = f"初始码-{i:03d}", f"中继码-{i + 100:03d}", f"终点码-{i + 200:03d}"
        chunks = []
        for subject, obj, text in [
            (root, mid, f"{root}的登记编号是REG_{i:03d}，登记连接到{mid}。这是软件功能测试，不提供医学知识。"),
            (mid, end, f"{mid}的后续连接登记为{end}。这是软件功能测试，不提供医学知识。"),
        ]:
            doc = app.state.documents.add(f"{subject}.txt", text.encode())
            chunk = app.state.documents.get(doc["id"])["chunks"][0]
            chunks.append(chunk["id"])
            row = app.state.relations.create(
                RelationInput(
                    subject=subject,
                    predicate="软件登记连接",
                    object=obj,
                    evidence_id=chunk["id"],
                    quote=chunk["text"],
                    conditions="仅限软件验收，非医学关系",
                )
            )
            app.state.relations.review(row["id"], RelationReview(status="approved", note="核对自建软件测试声明"))
        for j in range(4):
            app.state.documents.add(
                f"干扰-{i}-{j}.txt",
                f"{root}的查询页面说明{j}：软件目录保留检索入口与帮助文本，不包含登记编号及后续连接值。".encode(),
            )
        samples.append(
            {"id": f"lookup-{i}", "category": "direct", "query": f"{root}的登记编号是什么", "expected_ids": chunks[:1]}
        )
        samples.append(
            {
                "id": f"path-{i}",
                "category": "two_hop",
                "query": f"{root}的关联路径最终连接哪个终点",
                "expected_ids": chunks,
            }
        )
    for i, query in enumerate(["火星气象观测", "珊瑚海域洋流", "古建筑壁画年代", "遥感卫星轨道"]):
        samples.append({"id": f"absent-{i}", "category": "absent", "query": query, "expected_ids": []})
    return samples, {
        "kind": "self-authored non-clinical functional test",
        "seed": None,
        "expert_reviewed": False,
        "bias": "Queries and graph share a constructed schema, and relationship queries contain routing rule words. Not an independent policy benchmark.",
    }


def legacy(app):
    path = ROOT / "data/knowledge/knowledge.json"
    records = json.loads(path.read_text(encoding="utf-8"))
    eligible = [
        (i, r["knowledge"].strip())
        for i, r in enumerate(records)
        if isinstance(r, dict) and isinstance(r.get("knowledge"), str) and 40 <= len(r["knowledge"].strip()) <= 700
    ]
    selected = random.Random(20261027).sample(eligible, 500)
    samples = []
    for index, (record_index, text) in enumerate(selected):
        doc = app.state.documents.add(f"legacy-{record_index}.txt", text.encode())
        chunk = app.state.documents.get(doc["id"])["chunks"][0]
        if index < 80:
            samples.append(
                {
                    "id": f"legacy-{record_index}",
                    "category": "weak_prefix_lookup",
                    "query": text[:12],
                    "expected_ids": [chunk["id"]],
                    "record_index": record_index,
                }
            )
    return samples, {
        "kind": "weakly-labelled legacy medical source lookup",
        "seed": 20261027,
        "expert_reviewed": False,
        "corpus_file": "data/knowledge/knowledge.json",
        "corpus_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "record_indices": [i for i, _ in selected],
        "query_rule": "First 12 characters of each of the first 80 sampled records; known positive only, alternative positives not exhaustively labelled.",
        "bias": "Verbatim-prefix lookup favours lexical retrieval. Legacy text may contain errors. Not medical answer accuracy or semantic generalization.",
    }


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def measure(app, samples, mode, repeats, top_k, graph_ready):
    if mode == "vector" and not app.state.retriever.index_status()["ready"]:
        return {"mode": mode, "available": False, "reason": "No real embedding weights/index; not executed."}
    if mode == "graph" and not graph_ready:
        return {"mode": mode, "available": False, "reason": "This corpus has no reviewed graph. Not executed."}
    quality = []
    for sample in samples:
        found = app.state.retriever.search(sample["query"], top_k, mode=mode)
        ids = [r["id"] for r in found["items"]]
        expected = set(sample["expected_ids"])
        hits = expected.intersection(ids)
        ranks = [i for i, eid in enumerate(ids, 1) if eid in expected]
        quality.append(
            {
                "id": sample["id"],
                "category": sample["category"],
                "query": sample["query"],
                "expected_ids": sorted(expected),
                "returned_ids": ids,
                "recall": len(hits) / len(expected) if expected else None,
                "precision_at_k": len(hits) / top_k if expected else None,
                "reciprocal_rank": 1 / min(ranks) if ranks else 0,
                "hit": bool(hits),
                "empty": not ids,
                "effective_mode": found["mode"],
                "routing": found.get("routing"),
                "warnings": found["warnings"],
            }
        )
    timings = []
    for _ in range(repeats):
        for sample in samples:
            start = time.perf_counter()
            app.state.retriever.search(sample["query"], top_k, mode=mode)
            timings.append((time.perf_counter() - start) * 1000)
    positives = [r for r in quality if r["recall"] is not None]
    absent = [r for r in quality if r["category"] == "absent"]
    categories = {}
    for category in sorted({r["category"] for r in positives}):
        group = [r for r in positives if r["category"] == category]
        categories[category] = {
            "queries": len(group),
            "recall_at_k": statistics.mean(r["recall"] for r in group),
            "mrr": statistics.mean(r["reciprocal_rank"] for r in group),
        }
    return {
        "mode": mode,
        "available": True,
        "independent_queries": len(samples),
        "timed_calls": len(timings),
        "recall_at_k": statistics.mean(r["recall"] for r in positives),
        "precision_at_k": statistics.mean(r["precision_at_k"] for r in positives),
        "hit_at_k": statistics.mean(r["hit"] for r in positives),
        "mrr": statistics.mean(r["reciprocal_rank"] for r in positives),
        "absent_empty_rate": statistics.mean(r["empty"] for r in absent) if absent else None,
        "latency_ms": {
            "p50": statistics.median(timings),
            "p95": percentile(timings, 0.95),
            "mean": statistics.mean(timings),
        },
        "categories": categories,
        "results": quality,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["functional", "legacy"], default="functional")
    parser.add_argument("--repeats", type=int, default=5, choices=range(1, 21))
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 11))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--with-vectors",
        action="store_true",
        help="Build a real isolated BGE/FAISS index when local weights are complete",
    )
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(folder)
        samples, dataset = functional(app) if args.suite == "functional" else legacy(app)
        corpus = app.state.db.chunks()
        vector_setup = {"requested": args.with_vectors, "ready": False, "error": ""}
        if args.with_vectors:
            app.state.settings.update(SettingsUpdate(use_vectors=True, device=args.device))
            try:
                app.state.retriever.build()
                vector_setup["ready"] = True
            except (ImportError, OSError, ValueError, RuntimeError):
                vector_setup["error"] = "Real local embedding/index setup failed; vector results not measured."
                app.state.settings.update(SettingsUpdate(device=args.device))
        report = {
            "schema": 1,
            "suite": args.suite,
            "created_at": now(),
            "dataset": dataset,
            "documents": len(app.state.documents.list()),
            "chunks": len(corpus),
            "top_k": args.top_k,
            "repeats": args.repeats,
            "source_revision": revision(corpus),
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "cpu": platform.processor(),
                "device": "cpu",
                "concurrency": 1,
            },
            "code_sha256": {
                name: hashlib.sha256((ROOT / "backend/app" / name).read_bytes()).hexdigest()
                for name in ["routing.py", "retrieval.py", "relations.py"]
            },
            "settings": app.state.settings.get().model_dump(),
            "vector_setup": vector_setup,
            "latency_scope": "In-process warm retrieval including DB, tokenizer, routing, graph; excludes HTTP, indexing, answer generation and review.",
            "answer_accuracy": None,
            "clinical_accuracy": None,
            "methods": [],
        }
        graph_ready = bool(app.state.db.rows("SELECT id FROM relations WHERE status='approved' LIMIT 1"))
        for mode in ["keyword", "vector", "graph", "hybrid", "auto"]:
            result = measure(app, samples, mode, args.repeats, args.top_k, graph_ready)
            if args.suite == "legacy" and result["available"]:
                result["precision_at_k"] = None
                result["relevance_scope"] = (
                    "Known-positive source lookup only; alternative relevant records unlabelled. Precision cannot be estimated."
                )
                for row in result["results"]:
                    row["precision_at_k"] = None
            report["methods"].append(result)
            print(
                json.dumps({k: v for k, v in result.items() if k not in ["results", "categories"]}, ensure_ascii=False),
                flush=True,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
