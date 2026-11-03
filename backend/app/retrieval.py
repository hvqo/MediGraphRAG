from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import unicodedata
import time
import os

from .config import ROOT, model_paths


def tokens(text):
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", unicodedata.normalize("NFKC", text).lower())
    result = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 1:
            result.extend(word[i : i + size] for size in (2, 3) for i in range(len(word) - size + 1))
        else:
            result.append(word)
    return result


def revision(chunks):
    # IDs can survive a reparse with identical offsets; include actual text and provenance.
    payload = [
        {
            "id": item["id"],
            "text": item["text"],
            "metadata": item.get("source_metadata", {}),
            "parser": item.get("parser", ""),
        }
        for item in sorted(chunks, key=lambda c: c["id"])
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def model_signature(directory):
    files = []
    for pattern in ["*.json", "*.safetensors", "*.bin", "*.model", "vocab.txt"]:
        for path in sorted(directory.glob(pattern)):
            stat = path.stat()
            files.append((path.name, stat.st_size, stat.st_mtime_ns))
    return hashlib.sha256(repr(("normalized_cls_v1", files)).encode()).hexdigest()


@lru_cache(maxsize=1)
def glossary():
    terms = {
        "糖尿病": "疾病",
        "高血压": "疾病",
        "心肌梗死": "疾病",
        "肺炎": "疾病",
        "发热": "症状",
        "咳嗽": "症状",
        "胸痛": "症状",
        "血糖": "检查",
        "CT": "检查",
        "胰岛素": "药物",
        "超声": "检查",
        "血压": "检查",
    }
    path = ROOT / "data/graph/graph.json"
    if path.exists():
        for record in json.loads(path.read_text(encoding="utf-8")):
            for item in record.get("entities", []):
                name = item.get("entity")
                if isinstance(name, str) and 2 <= len(name) <= 24:
                    terms[name] = str(item.get("type", "医学概念"))
    return terms


def entities(text, limit=20):
    matches = sorted((name for name in glossary() if name in text), key=lambda name: (-len(name), name))
    # Prefer complete names to a shorter name contained within them.
    selected = []
    for name in matches:
        if not any(name in other for other in selected):
            selected.append(name)
        if len(selected) >= limit:
            break
    return selected


@lru_cache(maxsize=2)
def encoder(path, device, signature):
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModel.from_pretrained(path, local_files_only=True).to(device).eval()
    return tokenizer, model


@lru_cache(maxsize=1)
def reranker(path, device, signature):
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True).to(device).eval()
    return tokenizer, model


def embed(texts, device, model_path=None):
    import numpy as np
    import torch

    path = Path(model_path) if model_path else model_paths()[0]
    tokenizer, model = encoder(str(path), device, model_signature(path))
    batches = []
    for start in range(0, len(texts), 16):
        inputs = tokenizer(
            texts[start : start + 16], padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to(model.device)
        with torch.inference_mode():
            vectors = model(**inputs).last_hidden_state[:, 0]
            vectors = torch.nn.functional.normalize(vectors, p=2, dim=1)
        batches.append(vectors.cpu().numpy())
    return np.concatenate(batches).astype("float32")


class Retriever:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.index_path = db.directory / "vectors.index"
        self.meta_path = db.directory / "vectors.json"
        self.lock = threading.RLock()
        self.lexical_cache = None

    def embedding_path(self):
        if os.getenv("MEDIGRAPH_EMBEDDING_PATH"):
            return model_paths()[0]
        english = ROOT / ".runtime/models/bge-small-en-v1.5"
        sample = "".join(r["text"][:200] for r in self.db.rows("SELECT text FROM chunks LIMIT 64"))
        if (
            sample
            and len(re.findall(r"[\u4e00-\u9fff]", sample)) / len(sample) < 0.05
            and (english / "model.safetensors").exists()
        ):
            return english
        return model_paths()[0]

    def encode(self, texts):
        path = self.embedding_path()
        return (
            embed(texts, self.settings.get().device)
            if path == model_paths()[0]
            else embed(texts, self.settings.get().device, path)
        )

    def query_text(self, query):
        name = self.embedding_path().name.lower()
        if "bge" not in name:
            return query
        return (
            "为这个句子生成表示以用于检索相关文章："
            if "zh" in name
            else "Represent this sentence for searching relevant passages: "
        ) + query

    def index_status(self):
        if not self.meta_path.exists() or not self.index_path.exists():
            return {"ready": False, "message": "尚未建立向量索引"}
        try:
            metadata = json.loads(self.meta_path.read_text(encoding="utf-8"))
            path = self.embedding_path()
            ready = (
                metadata["revision"] == revision(self.db.chunks())
                and metadata.get("embedding_path") == str(path)
                and metadata.get("model_signature") == model_signature(path)
            )
            return {
                "ready": ready,
                "count": len(metadata["ids"]),
                "message": "索引可用" if ready else "资料或模型路径已变化，请重建索引",
            }
        except (ValueError, KeyError):
            return {"ready": False, "message": "索引元数据无效，请重建"}

    def build(self):
        import faiss

        with self.lock:
            chunks = self.db.chunks()
            if not chunks:
                raise ValueError("请先导入资料")
            vectors = self.encode([item["text"] for item in chunks])
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            temporary = str(self.index_path) + ".tmp"
            faiss.write_index(index, temporary)
            Path(temporary).replace(self.index_path)
            meta = {
                "revision": revision(chunks),
                "ids": [item["id"] for item in chunks],
                "embedding_path": str(self.embedding_path()),
                "model_signature": model_signature(self.embedding_path()),
                "pooling": "normalized_cls_v1",
            }
            temporary_meta = self.meta_path.with_suffix(".tmp")
            temporary_meta.write_text(json.dumps(meta), encoding="utf-8")
            temporary_meta.replace(self.meta_path)
            return {"ready": True, "count": len(chunks)}

    def search(self, query, top_k=None, document_id=None, evidence_ids=None, mode="auto", document_ids=None):
        if document_ids is not None:
            allowed = set(document_ids)
            scoped = [c["id"] for c in self.db.chunks() if c["document_id"] in allowed]
            evidence_ids = list(set(scoped).intersection(evidence_ids)) if evidence_ids else scoped
            if not evidence_ids:
                return {
                    "items": [],
                    "mode": "keyword",
                    "paths": [],
                    "warnings": ["指定资料中尚无可检索内容"],
                    "requested_mode": mode,
                    "elapsed_ms": 0,
                }
        started = time.perf_counter()
        if mode != "auto":
            result = self._search(query, top_k, document_id, evidence_ids, mode)
        else:
            from .routing import POLICY_VERSION, decide

            selected, code, reason = decide(query)
            result, attempted, graph_used, fallback, fast_ms = None, False, False, "", None

            def deepen():
                if not self.db.rows("SELECT id FROM relations WHERE status='approved' LIMIT 1"):
                    return None, False, "尚无已审核关系，保留快速检索结果"
                found = self._search(query, top_k, document_id, evidence_ids, "hybrid", approved_only=True)
                return (
                    (found, True, "")
                    if found["paths"]
                    else (None, True, "未命中当前范围内的有效审核路径，保留快速检索结果")
                )

            # Clear relationship intent routes first, avoiding a second lexical/vector pass.
            if selected == "deep":
                result, attempted, fallback = deepen()
                graph_used = result is not None
            if result is None:
                fast_start = time.perf_counter()
                result = self._search(query, top_k, document_id, evidence_ids, "fast")
                fast_ms = (time.perf_counter() - fast_start) * 1000
                if selected == "fast" and not result["items"]:
                    _, code, reason = decide(query, [])
                    deep, attempted, fallback = deepen()
                    if deep is not None:
                        result, graph_used = deep, True
            result["requested_mode"] = "auto"
            result["routing"] = {
                "policy": POLICY_VERSION,
                "selected": "deep" if graph_used else "fast",
                "reason_code": code,
                "reason": reason,
                "deep_attempted": attempted,
                "graph_used": graph_used,
                "fallback": fallback,
                "fast_ms": round(fast_ms, 3) if fast_ms is not None else None,
                "max_hops": 2,
                "max_paths": 30,
            }
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def build_step(self, batch_size=16):
        """Persist one vector batch, yielding to newly queued foreground work between steps."""
        import numpy as np
        import faiss

        with self.lock:
            chunks = self.db.chunks()
            if not chunks:
                raise ValueError("没有可索引资料")
            fingerprint = revision(chunks)
            model_path = self.embedding_path()
            signature = model_signature(model_path)
            build_key = hashlib.sha256(
                (fingerprint + str(model_path) + signature + str(batch_size)).encode()
            ).hexdigest()
            root = self.db.directory / "vector-building" / build_key
            root.mkdir(parents=True, exist_ok=True)
            cursor = 0
            blocks = []
            for start in range(0, len(chunks), batch_size):
                path = root / f"{start}.npy"
                if not path.exists():
                    break
                blocks.append(path)
                cursor = start + len(chunks[start : start + batch_size])
            if cursor < len(chunks):
                path = root / f"{cursor}.npy"
                values = self.encode([c["text"] for c in chunks[cursor : cursor + batch_size]])
                with path.with_suffix(".tmp").open("wb") as stream:
                    np.save(stream, values)
                path.with_suffix(".tmp").replace(path)
                blocks.append(path)
                cursor += len(values)
            if cursor < len(chunks):
                return {"ready": False, "processed": cursor, "total": len(chunks)}
            if revision(self.db.chunks()) != fingerprint:
                return {"ready": False, "processed": 0, "total": len(chunks), "changed": True}
            vectors = np.concatenate([np.load(p) for p in blocks]).astype("float32")
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            temporary = str(self.index_path) + ".tmp"
            faiss.write_index(index, temporary)
            Path(temporary).replace(self.index_path)
            meta = {
                "revision": fingerprint,
                "ids": [c["id"] for c in chunks],
                "embedding_path": str(model_path),
                "model_signature": signature,
                "pooling": "normalized_cls_v1",
            }
            temp = self.meta_path.with_suffix(".tmp")
            temp.write_text(json.dumps(meta), encoding="utf-8")
            temp.replace(self.meta_path)
            return {"ready": True, "processed": cursor, "total": len(chunks)}

    def _search(self, query, top_k=None, document_id=None, evidence_ids=None, mode="hybrid", approved_only=False):
        chunks = self.db.chunks()
        if document_id:
            chunks = [item for item in chunks if item["document_id"] == document_id]
        if evidence_ids:
            chunks = [item for item in chunks if item["id"] in evidence_ids]
        config = self.settings.get()
        top_k = top_k or config.top_k
        if not chunks:
            return {
                "items": [],
                "mode": "reviewed_relations" if mode == "graph" else "unavailable" if mode == "vector" else "keyword",
                "requested_mode": mode,
                "paths": [],
                "warnings": ["当前范围没有可检索的原文，请导入资料或调整范围"],
            }
        from .ranking import LexicalIndex

        fingerprint = revision(chunks)
        with self.lock:
            if not self.lexical_cache or self.lexical_cache[0] != fingerprint:
                self.lexical_cache = (fingerprint, LexicalIndex([item["text"] for item in chunks], tokens))
            lexical = self.lexical_cache[1].rank(query, 30)
        ranks = (
            {index: 1 / (60 + rank) for rank, (index, _) in enumerate(lexical, 1)}
            if mode in ("keyword", "hybrid", "fast")
            else {}
        )
        modes, warnings = (
            (
                ["keyword"]
                if mode in ("keyword", "hybrid", "fast")
                else ["reviewed_relations"]
                if mode == "graph"
                else []
            ),
            [],
        )
        seeds = entities(query, 5) if mode == "hybrid" and not approved_only else []
        if seeds and mode == "hybrid":
            neighbors = Counter(
                name for index, _ in lexical[:3] for name in entities(chunks[index]["text"]) if name not in seeds
            )
            graph_scores = []
            for index, chunk in enumerate(chunks):
                matches = sum(name in chunk["text"] for name, _ in neighbors.most_common(6))
                if matches >= 2 or any(name in chunk["text"] for name in seeds):
                    graph_scores.append((index, matches + 2 * sum(name in chunk["text"] for name in seeds)))
            for rank, (index, _) in enumerate(sorted(graph_scores, key=lambda item: item[1], reverse=True)[:20], 1):
                ranks[index] = ranks.get(index, 0) + 0.3 / (60 + rank)
            if graph_scores:
                modes.append("cooccurrence")
        from .relations import RelationStore

        paths = (
            RelationStore(self.db).paths(query, include_mentions=not approved_only)
            if mode in ("graph", "hybrid")
            else []
        )
        allowed = {c["id"] for c in chunks}
        paths = [path for path in paths if all(edge["evidence_id"] in allowed for edge in path)]
        if paths:
            supported_ids = {edge["evidence_id"] for path in paths for edge in path}
            for number, chunk in enumerate(chunks):
                if chunk["id"] in supported_ids:
                    ranks[number] = ranks.get(number, 0) + 1 / 61
            if "reviewed_relations" not in modes:
                modes.append("reviewed_relations")
        if mode == "vector" or (config.use_vectors and mode in ("hybrid", "fast")):
            if not self.index_status()["ready"]:
                warnings.append(
                    self.index_status()["message"]
                    + ("；本次使用关键词检索" if mode in ("hybrid", "fast") else "；未运行向量检索")
                )
            else:
                try:
                    import faiss

                    with self.lock:
                        metadata = json.loads(self.meta_path.read_text(encoding="utf-8"))
                        if metadata["revision"] != revision(self.db.chunks()):
                            raise ValueError("Index changed during search")
                        index = faiss.read_index(str(self.index_path))
                        distances, positions = index.search(
                            self.encode([self.query_text(query)]),
                            index.ntotal if document_id or evidence_ids else min(30, index.ntotal),
                        )
                    lookup = {item["id"]: number for number, item in enumerate(chunks)}
                    # Fast auto routing uses dense ranking; preserve lexical scores only on vector failure.
                    dense_ranks = {}
                    for rank, (position, distance) in enumerate(zip(positions[0], distances[0]), 1):
                        if (
                            0 <= position < len(metadata["ids"])
                            and distance > 0.25
                            and metadata["ids"][position] in lookup
                        ):
                            number = lookup[metadata["ids"][position]]
                            dense_ranks[number] = 1 / (60 + len(dense_ranks) + 1)
                            if mode != "fast":
                                ranks[number] = ranks.get(number, 0) + 1 / (60 + rank)
                    if (mode == "fast" or approved_only) and dense_ranks:
                        ranks = dense_ranks
                        modes = ["vector"]
                        if approved_only and paths:
                            for number, chunk in enumerate(chunks):
                                if chunk["id"] in supported_ids:
                                    ranks[number] = ranks.get(number, 0) + 1 / 61
                            modes.append("reviewed_relations")
                    else:
                        modes.append("vector")
                except (ImportError, OSError, RuntimeError, ValueError):
                    warnings.append("向量检索不可用" + ("；本次使用关键词检索" if mode in ("hybrid", "fast") else ""))
        selected = sorted(ranks, key=lambda number: ranks[number], reverse=True)[:20]
        if config.use_reranker and selected and mode == "hybrid":
            try:
                import torch

                _, path = model_paths()
                english_reranker = ROOT / ".runtime/models/ms-marco-MiniLM-L6-v2"
                if (
                    not os.getenv("MEDIGRAPH_RERANKER_PATH")
                    and "small-en" in self.embedding_path().name
                    and (english_reranker / "model.safetensors").exists()
                ):
                    path = english_reranker
                with self.lock:
                    tokenizer, model = reranker(str(path), config.device, model_signature(path))
                    inputs = tokenizer(
                        [[query, chunks[number]["text"]] for number in selected],
                        padding=True,
                        truncation=True,
                        max_length=512,
                        return_tensors="pt",
                    ).to(model.device)
                    with torch.inference_mode():
                        values = model(**inputs).logits.reshape(-1).cpu().tolist()
                selected = [
                    number for number, _ in sorted(zip(selected, values), key=lambda item: item[1], reverse=True)
                ]
                modes.append("reranker")
            except (ImportError, OSError, RuntimeError, ValueError):
                warnings.append("重排模型不可用；保留融合检索顺序")
        return {
            "items": [{**chunks[number], "score": round(ranks[number], 6)} for number in selected[:top_k]],
            "mode": "+".join(modes) or "unavailable",
            "requested_mode": mode,
            "paths": paths,
            "warnings": warnings,
        }

    def graph(self, query):
        chunks = self.search(query, 8)["items"] if query else self.db.chunks()[:20]
        nodes, edges = {}, {}
        for chunk in chunks:
            names = entities(chunk["text"], 10)
            for name in names:
                nodes[name] = {"id": name, "name": name, "category": glossary()[name]}
            for offset, left in enumerate(names):
                for right in names[offset + 1 :]:
                    pair = tuple(sorted([left, right]))
                    edge = edges.setdefault(
                        pair,
                        {
                            "source": pair[0],
                            "target": pair[1],
                            "label": "原文共现",
                            "kind": "cooccurrence",
                            "evidence_ids": [],
                        },
                    )
                    edge["evidence_ids"].append(chunk["id"])
        return {
            "nodes": list(nodes.values()),
            "links": list(edges.values()),
            "evidence": chunks,
            "message": "共现表示概念出现在同一原文片段，不表示因果、治疗或诊断关系",
        }
