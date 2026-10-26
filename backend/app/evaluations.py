"""Retrieval comparisons, explicit human ratings and configuration-frozen replay."""

import json
import time
import uuid
from types import SimpleNamespace
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .config import Settings
from .llm import ModelClient
from .retrieval import revision
from .storage import now


class Sample(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    expected_evidence_ids: list[str] = Field(min_length=1, max_length=10)
    reference_answer: str = Field(default="", max_length=4000)


class Suite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    samples: list[Sample] = Field(min_length=1, max_length=100)


class HumanReview(BaseModel):
    reviewed: bool


class Run(BaseModel):
    modes: list[Literal["keyword", "vector", "graph", "hybrid"]] = Field(
        default_factory=lambda: ["keyword", "graph", "hybrid"], min_length=1, max_length=4
    )
    top_k: int = Field(default=5, ge=1, le=10)


class Rating(BaseModel):
    sample_index: int = Field(ge=0)
    mode: str
    evidence_support: bool | None = None
    answer_correct: bool | None = None
    note: str = Field(default="", max_length=2000)


def routes(db, retriever, model):
    router = APIRouter()

    def suite(identifier):
        rows = db.rows("SELECT * FROM evaluations WHERE id=?", (identifier,))
        if not rows:
            raise HTTPException(404, "评测集不存在")
        return {**rows[0], "samples": json.loads(rows[0]["samples"])}

    @router.get("/evaluations")
    def listing():
        return [suite(r["id"]) for r in db.rows("SELECT id FROM evaluations ORDER BY created_at DESC")]

    @router.post("/evaluations")
    def create(value: Suite):
        existing = {c["id"] for c in db.chunks()}
        if any(not set(s.expected_evidence_ids) <= existing for s in value.samples):
            raise HTTPException(422, "预期证据包含不存在或已退役的片段")
        identifier = uuid.uuid4().hex
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO evaluations VALUES (?,?,?,?,?)",
                (
                    identifier,
                    value.name,
                    json.dumps([s.model_dump() for s in value.samples], ensure_ascii=False),
                    now(),
                    0,
                ),
            )
        return suite(identifier)

    @router.post("/evaluations/{identifier}/review")
    def review(identifier: str, value: HumanReview):
        suite(identifier)
        with db.connect() as connection:
            connection.execute("UPDATE evaluations SET reviewed=? WHERE id=?", (int(value.reviewed), identifier))
        return suite(identifier)

    @router.post("/evaluations/{identifier}/run")
    def run(identifier: str, value: Run):
        selected = suite(identifier)
        chunks = db.chunks()
        existing = {c["id"] for c in chunks}
        if any(not set(s["expected_evidence_ids"]) <= existing for s in selected["samples"]):
            raise HTTPException(409, "评测资料已变化，旧预期证据失效；请创建新版评测集")
        results = []
        for index, sample in enumerate(selected["samples"]):
            for mode in dict.fromkeys(value.modes):
                start = time.perf_counter()
                found = retriever.search(sample["query"], value.top_k, mode=mode)
                ids = [c["id"] for c in found["items"]]
                expected = set(sample["expected_evidence_ids"])
                ranks = [rank for rank, cid in enumerate(ids, 1) if cid in expected]
                unavailable = found["mode"] == "unavailable"
                results.append(
                    {
                        "sample_index": index,
                        "query": sample["query"],
                        "mode": mode,
                        "effective_mode": found["mode"],
                        "available": not unavailable,
                        "recall": len(expected & set(ids)) / len(expected) if not unavailable else None,
                        "reciprocal_rank": (1 / min(ranks) if ranks else 0) if not unavailable else None,
                        "seconds": round(time.perf_counter() - start, 4),
                        "evidence": found["items"],
                        "warnings": found["warnings"],
                        "human_rating": None,
                    }
                )
        if revision(db.chunks()) != revision(chunks):
            raise HTTPException(409, "评测期间资料发生变化，请重新运行")
        report = {
            "top_k": value.top_k,
            "source_revision": revision(chunks),
            "settings": retriever.settings.get().model_dump(),
            "index": retriever.index_status(),
            "suite_reviewed": bool(selected["reviewed"]),
            "results": results,
            "message": "仅自动计算检索召回与排名，不生成答案，也不自动评判医学正确性。人工答案判断需另附实际答案及说明。",
        }
        report["metrics"] = []
        for mode in dict.fromkeys(value.modes):
            available = [r for r in results if r["mode"] == mode and r["available"]]
            report["metrics"].append(
                {
                    "mode": mode,
                    "available_samples": len(available),
                    "total_samples": len(selected["samples"]),
                    "mean_recall": sum(r["recall"] for r in available) / len(available) if available else None,
                    "mrr": sum(r["reciprocal_rank"] for r in available) / len(available) if available else None,
                    "mean_seconds": sum(r["seconds"] for r in available) / len(available) if available else None,
                }
            )
        rid = uuid.uuid4().hex
        with db.connect() as connection:
            connection.execute(
                "INSERT INTO evaluation_runs VALUES (?,?,?,?,?)",
                (rid, identifier, ",".join(value.modes), json.dumps(report, ensure_ascii=False), now()),
            )
        return {"id": rid, "report": report}

    @router.get("/evaluation-runs")
    def runs():
        return [
            {**r, "report": json.loads(r["report"])}
            for r in db.rows("SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT 50")
        ]

    @router.post("/evaluation-runs/{identifier}/rate")
    def rate(identifier: str, value: Rating):
        if value.answer_correct is not None and len(value.note.strip()) < 8:
            raise HTTPException(422, "评价答案正确性时，请在说明中附实际答案与判定依据")
        rows = db.rows("SELECT * FROM evaluation_runs WHERE id=?", (identifier,))
        if not rows:
            raise HTTPException(404, "评测记录不存在")
        report = json.loads(rows[0]["report"])
        item = next(
            (r for r in report["results"] if r["sample_index"] == value.sample_index and r["mode"] == value.mode), None
        )
        if not item:
            raise HTTPException(422, "样本或模式不存在")
        item["human_rating"] = {**value.model_dump(), "rated_at": now()}
        with db.connect() as connection:
            connection.execute(
                "UPDATE evaluation_runs SET report=? WHERE id=?", (json.dumps(report, ensure_ascii=False), identifier)
            )
        return {"id": identifier, "report": report}

    @router.get("/traces")
    def traces():
        return db.rows(
            "SELECT id,role,provider,model,template,status,duration,input_tokens,output_tokens,error,created_at FROM traces ORDER BY created_at DESC LIMIT 200"
        )

    @router.get("/traces/{identifier}")
    def trace(identifier: str):
        rows = db.rows("SELECT * FROM traces WHERE id=?", (identifier,))
        if not rows:
            raise HTTPException(404, "运行记录不存在")
        row = rows[0]
        payload = json.loads(row["input"])
        return {
            **row,
            "input": payload,
            "output": json.loads(row["output"]) if row["output"] else None,
            "sources_current": payload.get("source_revision") == revision(db.chunks()),
        }

    @router.post("/traces/{identifier}/replay")
    async def replay(identifier: str):
        row = trace(identifier)
        payload = row["input"]
        if payload.get("source_revision") != await run_in_threadpool(lambda: revision(db.chunks())):
            raise HTTPException(409, "原文集合已变化，不能冒充原资料版本回放")
        settings = Settings.model_validate(payload["settings"])
        frozen = ModelClient(
            SimpleNamespace(get=lambda: settings, key=model.store.key), db, row["role"], row["template"]
        )
        return {
            "output": await frozen.json(payload["system"], payload["prompt"]),
            "message": "已用原模型配置与提示词重新调用；模型服务端权重和随机性可能变化，结果不保证相同。回放不会写入正式题库。",
        }

    return router
