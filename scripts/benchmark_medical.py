"""Real public medical retrieval + gold-labelled PubMedQA; never treat relevance labels as clinical approval."""

import argparse
from collections import Counter, defaultdict
import csv
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import sys
import time
import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.retrieval import tokens, embed, encoder, model_signature
from backend.app.ranking import LexicalIndex, MentionGraph, reciprocal_fusion
from backend.app.routing import decide
from backend.app.storage import now

CACHE = ROOT / ".runtime/medical-data"
METHODS = ["keyword", "vector", "graph_mentions", "hybrid", "hybrid_rerank", "auto"]


def load_data(name):
    if name == "nfcorpus":
        p = CACHE / "nfcorpus"
        docs = [json.loads(x) for x in (p / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
        queries = {
            q["_id"]: q["text"] for q in map(json.loads, (p / "queries.jsonl").read_text(encoding="utf-8").splitlines())
        }
        qrels = defaultdict(dict)
        with (p / "qrels/test.tsv").open(encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                qrels[row["query-id"]][row["corpus-id"]] = int(row["score"])
        return (
            docs,
            {i: queries[i] for i in sorted(qrels)},
            qrels,
            {
                "source": "https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/",
                "split": "BEIR complete test",
                "language": "en",
                "scope": "Relevant biomedical nutrition publications; labels derived from source links, not clinical accuracy.",
            },
        )
    if name == "medicalretrieval":
        import pyarrow.parquet as pq

        p = CACHE / "medicalretrieval"
        docs = pq.read_table(next((p / "corpus").glob("*.parquet"))).to_pylist()
        queries = {q["_id"]: q["text"] for q in pq.read_table(next((p / "queries").glob("*.parquet"))).to_pylist()}
        qrels = defaultdict(dict)
        for row in pq.read_table(next((p / "data").glob("*.parquet"))).to_pylist():
            qrels[row["query-id"]][row["corpus-id"]] = int(row["score"])
        needed = {cid for row in qrels.values() for cid in row}
        rest = [d for d in docs if d["_id"] not in needed]
        subset = [d for d in docs if d["_id"] in needed] + random.Random(20261027).sample(rest, 5000 - len(needed))
        return (
            subset,
            {i: queries[i] for i in sorted(qrels)},
            qrels,
            {
                "source": "https://huggingface.co/datasets/mteb/MedicalRetrieval",
                "split": "all 1000 dev queries; 5000-document controlled subset of 100999, all labelled positives retained",
                "seed": 20261027,
                "language": "zh",
                "scope": "Passage relevance only. Original passages can contain erroneous advice; never imported into production library or certified as medical truth.",
            },
        )
    raw = json.loads((CACHE / "ori_pqal.json").read_text(encoding="utf-8"))
    docs = [{"_id": i, "title": "", "text": "\n".join(r["CONTEXTS"])} for i, r in raw.items()]
    samples = []
    for label in ["yes", "no", "maybe"]:
        pool = sorted(i for i, r in raw.items() if r["final_decision"] == label)
        samples += random.Random(20261027).sample(pool, 20)
    queries = {i: raw[i]["QUESTION"] for i in sorted(samples)}
    return (
        docs,
        queries,
        {i: {i: 1} for i in queries},
        {
            "source": "https://github.com/pubmedqa/pubmedqa",
            "split": "60 label-stratified expert-labelled PQA-L samples, 20 per class; retrieval pool all 1000 abstracts, titles/conclusions/gold long answers not indexed",
            "language": "en",
            "gold": {i: raw[i]["final_decision"] for i in queries},
            "seed": 20261027,
            "scope": "Biomedical research yes/no/maybe benchmark, not prospective clinical safety validation.",
        },
    )


class Engine:
    def __init__(self, docs, language, dataset):
        import faiss

        self.docs = docs
        self.texts = [(d.get("title", "") + "\n" + d["text"]).strip() for d in docs]
        self.lex = LexicalIndex(self.texts, tokens)
        self.graph = MentionGraph([d.get("title") or d["text"][:100] for d in docs])
        model = "bge-large-zh-v1.5" if language == "zh" else "bge-small-en-v1.5"
        self.model = ROOT / ".runtime/models" / model
        os.environ["MEDIGRAPH_EMBEDDING_PATH"] = str(self.model)
        self.language = language
        self.fingerprint = hashlib.sha256(
            json.dumps([(d["_id"], t) for d, t in zip(docs, self.texts)], ensure_ascii=False).encode()
        ).hexdigest()
        output = CACHE / (dataset + "-vectors.npy")
        started = time.perf_counter()
        # Cached embeddings are keyed by the complete corpus + model identity, never query labels.
        key = self.fingerprint + model + model_signature(self.model)
        if output.exists() and output.with_suffix(".key").exists() and output.with_suffix(".key").read_text() == key:
            vectors = np.load(output)
        else:
            blocks = []
            for i in range(0, len(self.texts), 128):
                blocks.append(embed(self.texts[i : i + 128], "cuda"))
                print("embedding", dataset, i, len(self.texts), flush=True)
            vectors = np.concatenate(blocks)
            np.save(output, vectors)
            output.with_suffix(".key").write_text(key)
        self.index = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)
        self.build_seconds = time.perf_counter() - started
        self.rerank_model = None

    def vector(self, query):
        instruction = (
            "为这个句子生成表示以用于检索相关文章："
            if self.language == "zh"
            else "Represent this sentence for searching relevant passages: "
        )
        distances, positions = self.index.search(embed([instruction + query], "cuda"), 30)
        return [(int(i), float(v)) for i, v in zip(positions[0], distances[0]) if i >= 0]

    def rerank(self, query, ranking):
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        if self.rerank_model is None:
            path = (
                ROOT / ".runtime/models" / ("bge-reranker-base" if self.language == "zh" else "ms-marco-MiniLM-L6-v2")
            )
            self.rerank_tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
            self.rerank_model = (
                AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True).to("cuda").eval()
            )
        values = []
        for i in range(0, min(20, len(ranking)), 4):
            batch = ranking[i : i + 4]
            inputs = self.rerank_tokenizer(
                [[query, self.texts[index]] for index, _ in batch],
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            ).to("cuda")
            with torch.inference_mode():
                scores = self.rerank_model(**inputs).logits.flatten().cpu().tolist()
            values += list(zip([index for index, _ in batch], scores))
        return sorted(values, key=lambda p: (-p[1], p[0]))

    def search(self, query, method):
        if method == "keyword":
            return self.lex.rank(query)
        if method == "vector":
            return self.vector(query)
        if method == "graph_mentions":
            return self.graph.rank(query)
        ranking = reciprocal_fusion(self.lex.rank(query), self.vector(query))
        if method == "hybrid_rerank":
            return self.rerank(query, ranking)
        if method == "hybrid" or (method == "auto" and decide(query)[0] == "deep"):
            ranking = reciprocal_fusion(ranking, self.graph.rank(query))
        return ranking


def score(ids, gold, k):
    relevant = {i for i, v in gold.items() if v > 0}
    got = ids[:k]
    dcg = sum((2 ** gold.get(cid, 0) - 1) / math.log2(rank + 2) for rank, cid in enumerate(got))
    ideal = sum((2**v - 1) / math.log2(rank + 2) for rank, v in enumerate(sorted(gold.values(), reverse=True)[:k]))
    ranks = [i for i, c in enumerate(got, 1) if c in relevant]
    return {
        "recall": len(relevant.intersection(got)) / len(relevant),
        "precision": len(relevant.intersection(got)) / k,
        "mrr": 1 / min(ranks) if ranks else 0,
        "ndcg": dcg / ideal if ideal else 0,
        "hit": int(bool(ranks)),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=["nfcorpus", "medicalretrieval", "pubmedqa"], required=True)
    args = p.parse_args()
    docs, queries, qrels, info = load_data(args.dataset)
    output = ROOT / "benchmarks/results" / (args.dataset + "-real.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at": now(),
        "dataset": args.dataset,
        "info": info,
        "documents": len(docs),
        "queries": len(queries),
        "model_device": "RTX4050 CUDA, single request concurrency",
        "methods": [],
        "latency_scope": "Retrieval core including real query encoding and reranking; excludes HTTP/SQLite document loading and generation. Corpus encoding not part of query latency. One measured pass after explicit warm-up.",
        "source_fingerprint": None,
    }
    engine = Engine(docs, info["language"], args.dataset)
    report["source_fingerprint"] = engine.fingerprint
    report["embedding_model"] = engine.model.name
    report["index_seconds"] = engine.build_seconds
    for method in METHODS:
        engine.search(next(iter(queries.values())), method)
        rows = []
        for number, (qid, query) in enumerate(queries.items()):
            started = time.perf_counter()
            ranking = engine.search(query, method)
            seconds = time.perf_counter() - started
            ids = [docs[i]["_id"] for i, _ in ranking]
            rows.append(
                {
                    "query_id": qid,
                    "returned_ids": ids[:10],
                    "latency_ms": seconds * 1000,
                    "at5": score(ids, qrels[qid], 5),
                    "at10": score(ids, qrels[qid], 10),
                }
            )
            if number % 100 == 0:
                print(args.dataset, method, number, flush=True)
        item = {
            "method": method,
            "queries": len(rows),
            "at5": {metric: statistics.mean(r["at5"][metric] for r in rows) for metric in rows[0]["at5"]},
            "at10": {metric: statistics.mean(r["at10"][metric] for r in rows) for metric in rows[0]["at10"]},
            "p50_ms": statistics.median(r["latency_ms"] for r in rows),
            "p95_ms": sorted(r["latency_ms"] for r in rows)[math.ceil(0.95 * len(rows)) - 1],
            "predictions": rows,
        }
        report["methods"].append(item)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT", args.dataset, {k: v for k, v in item.items() if k != "predictions"}, flush=True)
    # Free CUDA model allocations before the separate Ollama model is loaded.
    del engine
    encoder.cache_clear()
    gc.collect()
    import torch

    torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
