import difflib
import json
import re
from pydantic import BaseModel, Field
from .storage import now


class DocumentMetadata(BaseModel):
    source: str = Field(default="", max_length=1000)
    edition: str = Field(default="", max_length=100)
    year: int | None = Field(default=None, ge=1800, le=2200)
    scope: str = Field(default="", max_length=1000)
    chapter: str = Field(default="", max_length=300)


class VersionLink(BaseModel):
    predecessor: str


class Chunking(BaseModel):
    size: int = Field(default=800, ge=200, le=2000)
    overlap: int = Field(default=100, ge=0, le=150)


def metadata(db, identifier):
    rows = db.rows("SELECT * FROM document_meta WHERE document_id=?", (identifier,))
    if not rows:
        return {"metadata": {}, "series_id": identifier, "predecessor": None, "parser": "native-v1", "active": 1}
    row = rows[0]
    return {**row, "metadata": json.loads(row["metadata"])}


def annotate(db, identifier, chunks, parser="native-v1"):
    with db.connect() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO document_meta(document_id,series_id,parser) VALUES (?,?,?)",
            (identifier, identifier, parser),
        )
        for chunk in chunks:
            heading = next(
                (
                    line.strip("# ").strip()
                    for line in chunk["text"].splitlines()
                    if re.match(r"^(#{1,6}\s|第.+[章节]|\d+(\.\d+)*\s)", line)
                ),
                "",
            )
            connection.execute(
                "INSERT OR REPLACE INTO chunk_meta(chunk_id,heading) VALUES (?,?)", (chunk["id"], heading)
            )


def update_metadata(store, identifier, value):
    store.get(identifier)
    with store.db.connect() as connection:
        connection.execute(
            "INSERT INTO document_meta(document_id,series_id,metadata) VALUES (?,?,?) "
            "ON CONFLICT(document_id) DO UPDATE SET metadata=excluded.metadata",
            (identifier, identifier, value.model_dump_json()),
        )
    return store.get(identifier)


def version_impact(store, old_id, new_id):
    old, new = store.get(old_id), store.get(new_id)
    ids = {item["id"] for item in old["chunks"]}
    affected = []
    extras = {r["question_id"]: json.loads(r["metadata"]) for r in store.db.rows("SELECT * FROM question_meta")}
    if store.db.rows("SELECT name FROM sqlite_master WHERE name='questions'"):
        for row in store.db.rows("SELECT id,content,status FROM questions"):
            if any(
                c.get("evidence_id") in ids
                for c in json.loads(row["content"]).get("citations", [])
                + extras.get(row["id"], {}).get("case_citations", [])
            ):
                affected.append({"id": row["id"], "status": row["status"]})
    relations = store.db.rows("SELECT id,evidence_id FROM relations")
    traces = store.db.rows("SELECT id,template,input FROM traces")
    differences = list(
        difflib.unified_diff(
            "\n".join(c["text"] for c in old["chunks"]).splitlines(),
            "\n".join(c["text"] for c in new["chunks"]).splitlines(),
            fromfile=old["title"],
            tofile=new["title"],
            lineterm="",
        )
    )
    return {
        "questions": affected,
        "relation_ids": [r["id"] for r in relations if r["evidence_id"] in ids],
        "answer_trace_ids": [
            r["id"] for r in traces if r["template"] == "answer-v2" and any(cid in r["input"] for cid in ids)
        ],
        "diff": differences[:1000],
        "diff_truncated": len(differences) > 1000,
        "message": "这里只比较资料文字变化，不自动判定医学观点对错",
    }


def link_version(store, new_id, previous_id):
    if new_id == previous_id:
        raise ValueError("新旧版本不能是同一份资料")
    new, old = store.get(new_id), store.get(previous_id)
    if new["series_id"] == old["series_id"]:
        raise ValueError("资料已属于同一版本链，不能重复关联")
    impact = version_impact(store, previous_id, new_id)
    with store.db.connect() as connection:
        # Never silently discard an already versioned successor branch.
        if (
            connection.execute("SELECT count(*) FROM document_meta WHERE series_id=?", (new["series_id"],)).fetchone()[
                0
            ]
            > 1
        ):
            raise ValueError("新资料已有版本链，请选择未关联的资料")
        connection.execute(
            "INSERT OR IGNORE INTO document_meta(document_id,series_id) VALUES (?,?)", (previous_id, old["series_id"])
        )
        connection.execute(
            "INSERT OR IGNORE INTO document_meta(document_id,series_id) VALUES (?,?)", (new_id, new["series_id"])
        )
        connection.execute("UPDATE document_meta SET active=0 WHERE series_id=?", (old["series_id"],))
        connection.execute(
            "UPDATE document_meta SET series_id=?,predecessor=?,active=1 WHERE document_id=?",
            (old["series_id"], previous_id, new_id),
        )
        for item in impact["questions"]:
            connection.execute(
                "UPDATE questions SET status='pending_review',note='原文已有新版本，需重新核对依据' WHERE id=?",
                (item["id"],),
            )
            connection.execute(
                "INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)",
                (item["id"], "source_changed", "原文已有新版本，退回待审", now()),
            )
        for identifier in impact["relation_ids"]:
            connection.execute("UPDATE relations SET status='outdated',note='原文已有新版本' WHERE id=?", (identifier,))
    return {"document": store.get(new_id), "impact": impact}


def invalidate(db, evidence_ids, reason):
    """Keep an audit trail when source deletion/reparsing retires cited chunks."""
    if not evidence_ids:
        return
    ids = set(evidence_ids)
    has_questions = db.rows("SELECT name FROM sqlite_master WHERE name='questions'")
    questions = db.rows("SELECT id,content FROM questions") if has_questions else []
    extras = {r["question_id"]: json.loads(r["metadata"]) for r in db.rows("SELECT * FROM question_meta")}
    with db.connect() as connection:
        for row in questions:
            citations = json.loads(row["content"]).get("citations", []) + extras.get(row["id"], {}).get(
                "case_citations", []
            )
            if any(c["evidence_id"] in ids for c in citations):
                connection.execute(
                    "UPDATE questions SET status='pending_review',note=?,updated_at=? WHERE id=?",
                    (reason, now(), row["id"]),
                )
                connection.execute(
                    "INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)",
                    (row["id"], "source_changed", reason, now()),
                )
        for relation in db.rows("SELECT id,evidence_id FROM relations"):
            if relation["evidence_id"] in ids:
                connection.execute(
                    "UPDATE relations SET status='outdated',note=?,updated_at=? WHERE id=?",
                    (reason, now(), relation["id"]),
                )
        for case in db.rows("SELECT id,citations FROM cases"):
            if any(c["evidence_id"] in ids for c in json.loads(case["citations"])):
                connection.execute(
                    "UPDATE cases SET status='pending_review',updated_at=? WHERE id=?", (now(), case["id"])
                )
