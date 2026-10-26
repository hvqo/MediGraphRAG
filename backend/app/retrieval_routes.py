import os
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from .evidence import answer_question


class Query(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=10)
    document_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    mode: Literal["keyword", "vector", "graph", "hybrid"] = "hybrid"


class GraphQuery(BaseModel):
    keyword: str = Field(default="", max_length=200)


def routes(retriever, model):
    router = APIRouter()

    @router.post("/search")
    def search(value: Query):
        return retriever.search(value.query, value.top_k, value.document_id, value.evidence_ids, value.mode)

    @router.post("/ask")
    async def ask(value: Query):
        result = await run_in_threadpool(
            retriever.search, value.query, value.top_k, value.document_id, value.evidence_ids, value.mode
        )
        answer = await answer_question(model, value.query, result)
        if answer["status"] == "draft":
            cited = {citation["evidence_id"] for block in answer["blocks"] for citation in block["citations"]}
            current = {row["id"] for row in retriever.db.chunks()}
            if not cited <= current:
                raise HTTPException(409, "回答生成期间原文资料已变化，请重新提问")
        return answer

    @router.get("/indexes/status")
    def index_status():
        return retriever.index_status()

    @router.post("/indexes/build")
    async def build_index():
        try:
            return await run_in_threadpool(retriever.build)
        except (ImportError, ValueError, OSError, RuntimeError):
            raise HTTPException(422, "索引构建失败：请先导入资料，并确认 BGE 权重和分词器完整、设备可用") from None

    @router.post("/graph/search")
    def graph(value: GraphQuery):
        return retriever.graph(value.keyword)

    @router.post("/graph/neo4j")
    def neo4j_graph(value: GraphQuery):
        if not os.getenv("MEDIGRAPH_NEO4J_PASSWORD"):
            raise HTTPException(503, "Neo4j 尚未配置；请在本地 .env 填写连接信息")
        from neo4j import GraphDatabase

        try:
            with GraphDatabase.driver(
                os.getenv("MEDIGRAPH_NEO4J_URI", "bolt://localhost:7687"),
                auth=(os.getenv("MEDIGRAPH_NEO4J_USER", "neo4j"), os.environ["MEDIGRAPH_NEO4J_PASSWORD"]),
                connection_timeout=5,
            ) as driver:
                with driver.session() as session:
                    records = session.run(
                        """MATCH (a)-[r]->(b) WHERE a.name CONTAINS $keyword OR b.name CONTAINS $keyword
                        RETURN elementId(a) AS source, a.name AS source_name, labels(a) AS source_labels,
                        elementId(b) AS target, b.name AS target_name, labels(b) AS target_labels,
                        coalesce(r.relation,type(r)) AS label LIMIT 100""",
                        keyword=value.keyword,
                    )
                    nodes, links = {}, []
                    for row in records:
                        for side in ["source", "target"]:
                            nodes[row[side]] = {
                                "id": row[side],
                                "name": row[side + "_name"],
                                "category": ",".join(row[side + "_labels"]),
                            }
                        links.append(
                            {
                                "source": row["source"],
                                "target": row["target"],
                                "label": row["label"],
                                "kind": "legacy",
                                "evidence_ids": [],
                            }
                        )
                    return {
                        "nodes": list(nodes.values()),
                        "links": links,
                        "evidence": [],
                        "message": "历史 Neo4j 图谱；缺少文献来源的关系不用于生成答案依据",
                    }
        except Exception:
            raise HTTPException(503, "Neo4j 连接或查询失败，请检查服务及连接配置") from None

    return router
