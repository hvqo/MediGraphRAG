"""Teaching blueprints, shared case material and transparent automatic review."""
import json
import uuid
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from .evidence import Citation, validate_citations
from .storage import now


class OptionReview(BaseModel):
    correct: bool
    reason: str = Field(min_length=4, max_length=1000)
    citations: list[Citation] = Field(min_length=1, max_length=5)


class AutomaticReview(BaseModel):
    supported: bool
    answer_valid: bool
    ambiguous: bool
    leaks_answer: bool
    reason: str = Field(min_length=1, max_length=1000)
    options: dict[str, OptionReview]

    def check(self, question, evidence):
        if not self.supported or not self.answer_valid or self.ambiguous or self.leaks_answer:
            raise ValueError('模型复核未通过：' + self.reason)
        if set(self.options) != set('ABCD'):
            raise ValueError('审题必须分别检查 A、B、C、D')
        for key, item in self.options.items():
            if item.correct != (key in question.answer):
                raise ValueError('逐项审查与答案集合不一致')
            validate_citations(item.citations, evidence)


class BlueprintRow(BaseModel):
    chapter: str = Field(default='', max_length=300)
    knowledge_point: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=1000)
    cognition: Literal['remember', 'understand', 'apply', 'analyze'] = 'understand'
    question_type: Literal['single_choice', 'multiple_choice', 'case'] = 'single_choice'
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'
    count: int = Field(default=1, ge=1, le=10)
    case_id: str | None = None


class Blueprint(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    rows: list[BlueprintRow] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def bounded(self):
        if sum(row.count for row in self.rows) > 100:
            raise ValueError('每份蓝图最多100题')
        return self


class CaseInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    narrative: str = Field(min_length=8, max_length=4000)
    citations: list[Citation] = Field(min_length=1, max_length=10)


class CaseReview(BaseModel):
    status: Literal['approved', 'rejected']


def cases(db):
    result = []
    for row in db.rows('SELECT * FROM cases ORDER BY created_at DESC'):
        citations = [Citation.model_validate(c) for c in json.loads(row['citations'])]
        try:
            validate_citations(citations, db.chunks())
            valid = True
        except ValueError:
            valid = False
        result.append({**row, 'citations': [c.model_dump() for c in citations], 'sources_valid': valid})
    return result


def approved_case(db, identifier):
    row = next((c for c in cases(db) if c['id'] == identifier), None)
    if not row or row['status'] != 'approved' or not row['sources_valid']:
        raise ValueError('病例材料需要人工审核通过，且出处必须有效')
    return row


def routes(store, jobs):
    router, db = APIRouter(), store.db

    @router.get('/blueprints')
    def listing():
        result = []
        for blueprint in db.rows('SELECT * FROM blueprints ORDER BY created_at DESC'):
            rows = json.loads(blueprint['rows_json'])
            for index, row in enumerate(rows):
                matches = [q for q in store.list(limit=None) if q['metadata'].get('blueprint_id') == blueprint['id'] and q['metadata'].get('row_index') == index]
                row.update(generated=len(matches), approved=sum(q['status'] == 'approved' and q['sources_valid'] for q in matches),
                           duplicate_stems=len(matches) - len({q['content']['topic'] for q in matches}))
                row['missing'] = max(0, row['count'] - row['approved'])
            result.append({**blueprint, 'rows': rows})
        return result

    @router.post('/blueprints')
    def create(value: Blueprint):
        identifier = uuid.uuid4().hex
        with db.connect() as connection:
            connection.execute('INSERT INTO blueprints VALUES (?,?,?,?)', (identifier, value.title, json.dumps([r.model_dump() for r in value.rows], ensure_ascii=False), now()))
        return next(b for b in listing() if b['id'] == identifier)

    @router.post('/blueprints/{identifier}/generate')
    async def generate(identifier: str):
        from .questions import GenerationRequest
        blueprint = next((b for b in listing() if b['id'] == identifier), None)
        if not blueprint:
            raise HTTPException(404, '蓝图不存在')
        # Preflight the entire blueprint before launching any jobs.
        try:
            values = [GenerationRequest.model_validate(r) for r in blueprint['rows']]
            for value in values:
                if value.case_id:
                    approved_case(db, value.case_id)
        except ValueError as error:
            raise HTTPException(422, str(error))
        return {'jobs': [jobs.start(value, {'blueprint_id': identifier, 'row_index': i}) for i, value in enumerate(values)]}

    @router.get('/cases')
    def case_list():
        return cases(db)

    @router.post('/cases')
    def create_case(value: CaseInput):
        try:
            validate_citations(value.citations, db.chunks())
        except ValueError as error:
            raise HTTPException(422, str(error))
        identifier, timestamp = uuid.uuid4().hex, now()
        with db.connect() as connection:
            connection.execute('INSERT INTO cases VALUES (?,?,?,?,?,?,?)', (identifier, value.title, value.narrative,
                json.dumps([c.model_dump() for c in value.citations], ensure_ascii=False), 'pending_review', timestamp, timestamp))
        return next(c for c in cases(db) if c['id'] == identifier)

    @router.post('/cases/{identifier}/review')
    def review_case(identifier: str, value: CaseReview):
        row = next((c for c in cases(db) if c['id'] == identifier), None)
        if not row:
            raise HTTPException(404, '病例不存在')
        if value.status == 'approved' and not row['sources_valid']:
            raise HTTPException(422, '病例出处失效，无法通过')
        with db.connect() as connection:
            connection.execute('UPDATE cases SET status=?,updated_at=? WHERE id=?', (value.status, now(), identifier))
        return next(c for c in cases(db) if c['id'] == identifier)

    @router.get('/rejected-candidates')
    def rejected():
        return [{**r, 'content': json.loads(r['content'])} for r in db.rows('SELECT * FROM rejected_candidates ORDER BY created_at DESC LIMIT 100')]

    return router
