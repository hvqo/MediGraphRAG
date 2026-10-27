"""Measure the dense-first fallback on public sets without overwriting baseline measurements."""

import json
import math
import statistics
import time
import gc
import torch
import httpx
from benchmark_medical import ROOT, Engine, load_data, score, encoder
from backend.app.routing import decide


def main():
    httpx.post(
        "http://127.0.0.1:11434/api/generate", json={"model": "qwen2.5", "keep_alive": 0}, timeout=60, trust_env=False
    ).raise_for_status()
    for name in ["nfcorpus", "medicalretrieval", "pubmedqa"]:
        docs, queries, qrels, info = load_data(name)
        engine = Engine(docs, info["language"], name)
        engine.vector(next(iter(queries.values())))
        rows = []
        for qid, query in queries.items():
            start = time.perf_counter()
            decide(query)
            # These datasets have no reviewed relation labels. The production policy falls back to dense.
            ranking = engine.vector(query)
            ms = (time.perf_counter() - start) * 1000
            ids = [docs[i]["_id"] for i, _ in ranking]
            rows.append(
                {
                    "query_id": qid,
                    "returned_ids": ids[:10],
                    "latency_ms": ms,
                    "at5": score(ids, qrels[qid], 5),
                    "at10": score(ids, qrels[qid], 10),
                }
            )
        path = ROOT / "benchmarks/results" / f"{name}-real.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        for item in report["methods"]:
            if item["method"] == "auto":
                item["method"] = "auto_v1"
        report["methods"] = [r for r in report["methods"] if r["method"] != "auto_v2"]
        result = {
            "method": "auto_v2",
            "queries": len(rows),
            "scope": "Dense-first fallback only; no manually reviewed clinical graph in these public sets. Post-hoc development policy, not held-out validation.",
            "at5": {k: statistics.mean(r["at5"][k] for r in rows) for k in rows[0]["at5"]},
            "at10": {k: statistics.mean(r["at10"][k] for r in rows) for k in rows[0]["at10"]},
            "p50_ms": statistics.median(r["latency_ms"] for r in rows),
            "p95_ms": sorted(r["latency_ms"] for r in rows)[math.ceil(0.95 * len(rows)) - 1],
            "predictions": rows,
        }
        report["methods"].append(result)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(name, {k: v for k, v in result.items() if k != "predictions"}, flush=True)
        del engine
        encoder.cache_clear()
        gc.collect()
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
