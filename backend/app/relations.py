"""Evidence-bearing relation candidates, manual approval and bounded path retrieval."""

import hashlib
import json
import os
import uuid
from collections import deque
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .evidence import Citation, SYSTEM, context, validate_citations
from .storage import now
from .llm import for_task


class RelationInput(BaseModel):
    subject: str = Field(min_length=1, max_length=100)
    predicate: str = Field(min_length=1, max_length=100)
    object: str = Field(min_length=1, max_length=100)
    evidence_id: str
    quote: str = Field(min_length=4, max_length=800)
    conditions: str = Field(default="", max_length=1000)


class RelationReview(BaseModel):
    status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=1000)


class Extraction(BaseModel):
    evidence_id: str


class PathQuery(BaseModel):
    query: str = Field(min_length=1, max_length=1000)


class RelationStore:
    def __init__(self, db):
        self.db = db

    def list(self):
        evidence = {c["id"]: c for c in self.db.chunks()}
        result = []
        for row in self.db.rows("SELECT * FROM relations ORDER BY created_at DESC"):
            source = evidence.get(row["evidence_id"])
            valid = bool(source)
            if valid:
                try:
                    validate_citations([Citation(evidence_id=row["evidence_id"], quote=row["quote"])], [source])
                except ValueError:
                    valid = False
            result.append(
                {
                    **row,
                    "sources_valid": valid,
                    "evidence": source,
                    "effective_status": row["status"] if valid else "outdated",
                }
            )
        return result

    def create(self, value):
        validate_citations([Citation(evidence_id=value.evidence_id, quote=value.quote)], self.db.chunks())
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    value.subject.strip(),
                    value.predicate.strip(),
                    value.object.strip(),
                    value.evidence_id,
                    value.quote,
                    value.conditions,
                    "pending_review",
                    "",
                    timestamp,
                    timestamp,
                ),
            )
        return next(r for r in self.list() if r["id"] == identifier)

    def review(self, identifier, value):
        row = next((r for r in self.list() if r["id"] == identifier), None)
        if not row:
            raise KeyError(identifier)
        if value.status == "approved" and not row["sources_valid"]:
            raise ValueError("原文已删除、更新或引文失效，不能通过")
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE relations SET status=?,note=?,updated_at=? WHERE id=?",
                (value.status, value.note, now(), identifier),
            )
        return next(r for r in self.list() if r["id"] == identifier)

    def paths(self, query, depth=2, include_mentions=True):
        rows = [
            r
            for r in self.list()
            if r["effective_status"] in (["approved", "literal_verified"] if include_mentions else ["approved"])
        ]
        seeds = {name for r in rows for name in (r["subject"], r["object"]) if name.casefold() in query.casefold()}
        queue = deque((name, [], {name}) for name in sorted(seeds))
        result, seen = [], set()
        while queue and len(result) < 30:
            node, path, visited = queue.popleft()
            if len(path) >= depth:
                continue
            for row in rows:
                if node not in (row["subject"], row["object"]):
                    continue
                neighbor = row["object"] if node == row["subject"] else row["subject"]
                if neighbor in visited:
                    continue
                extension = path + [row]
                signature = tuple(r["id"] for r in extension)
                if signature not in seen:
                    result.append(extension)
                    seen.add(signature)
                queue.append((neighbor, extension, visited | {neighbor}))
        return result

    def sync(self):
        if not os.getenv("MEDIGRAPH_NEO4J_PASSWORD"):
            raise ValueError("请先配置并启动 Neo4j")
        from neo4j import GraphDatabase

        namespace = hashlib.sha256(str(self.db.directory).encode()).hexdigest()[:20]
        rows = [
            {k: r[k] for k in ("id", "subject", "predicate", "object", "evidence_id", "quote", "conditions")}
            for r in self.list()
            if r["effective_status"] == "approved"
        ]

        def replace(tx):
            # Only this workspace's owned relationships are replaced; historical graphs are untouched.
            tx.run(
                "MATCH ()-[r:MEDIGRAPH_ASSERTION {workspace:$workspace}]->() DELETE r", workspace=namespace
            ).consume()
            tx.run(
                """UNWIND $rows AS row
                MERGE (a:MediGraphEntity {workspace:$workspace,name:row.subject})
                MERGE (b:MediGraphEntity {workspace:$workspace,name:row.object})
                MERGE (a)-[r:MEDIGRAPH_ASSERTION {workspace:$workspace,id:row.id}]->(b)
                SET r.predicate=row.predicate,r.evidence_id=row.evidence_id,r.quote=row.quote,r.conditions=row.conditions""",
                workspace=namespace,
                rows=rows,
            ).consume()

        with GraphDatabase.driver(
            os.getenv("MEDIGRAPH_NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.getenv("MEDIGRAPH_NEO4J_USER", "neo4j"), os.environ["MEDIGRAPH_NEO4J_PASSWORD"]),
            connection_timeout=5,
        ) as driver:
            with driver.session() as session:
                session.execute_write(replace)
        return {"synced": len(rows), "workspace": namespace}


def routes(store, model):
    router = APIRouter()

    @router.get("/relations")
    def listing():
        return store.list()

    @router.post("/relations")
    def create(value: RelationInput):
        try:
            return store.create(value)
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.post("/relations/extract")
    async def extract(value: Extraction):
        evidence = [c for c in store.db.chunks() if c["id"] == value.evidence_id]
        if not evidence:
            raise HTTPException(422, "请选择有效的当前原文片段")
        raw = await for_task(model, "extraction", "relations-v1").json(
            SYSTEM,
            f"抽取资料中明确陈述的关系，不能把同段出现当成关系。保留否定、条件和适用范围。\n资料：{context(evidence)}\n"
            '输出 {"relations":[{"subject":"主体","predicate":"关系","object":"客体","evidence_id":"片段ID","quote":"逐字原句","conditions":"适用条件"}]}，没有就返回空列表。最多10条。',
        )
        candidates = raw.get("relations")
        if not isinstance(candidates, list) or len(candidates) > 10:
            raise HTTPException(422, "抽取结果格式无效，未保存")
        # Validate the entire batch and enforce the requested source before any write.
        try:
            values = [RelationInput.model_validate(c) for c in candidates]
            for item in values:
                validate_citations([Citation(evidence_id=item.evidence_id, quote=item.quote)], evidence)
        except ValueError:
            raise HTTPException(422, "候选关系未通过出处校验，未保存") from None
        return {"items": [store.create(item) for item in values], "message": "候选关系需人工核对原句与条件后审核"}

    @router.post("/relations/paths")
    def paths(value: PathQuery):
        return {"paths": store.paths(value.query), "message": "路径展示已审核的原文陈述；多条边不自动构成新的医学结论"}

    @router.post("/relations/sync")
    def sync():
        try:
            return store.sync()
        except Exception:
            raise HTTPException(503, "Neo4j 同步失败，请检查服务和配置；本地审核记录仍已保留") from None

    @router.post("/relations/{identifier}/review")
    def review(identifier: str, value: RelationReview):
        try:
            return store.review(identifier, value)
        except KeyError:
            raise HTTPException(404, "关系不存在")
        except ValueError as error:
            raise HTTPException(422, str(error))

    return router
