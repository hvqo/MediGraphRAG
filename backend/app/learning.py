"""Single-machine learner profiles and revision-aware formative practice."""
import hashlib
import json
import math
import uuid
from collections import Counter, defaultdict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from .storage import now


def question_revision(row):
    return hashlib.sha256(json.dumps({'content': row['content'], 'case': row['metadata'].get('case_narrative', '')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Attempt(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64)
    question_id: str
    revision: str
    answers: list[str] = Field(min_length=1, max_length=4)
    seconds: int = Field(default=0, ge=0, le=86400)

    @field_validator('answers')
    @classmethod
    def choices(cls, value):
        if len(value) != len(set(value)) or not set(value) <= set('ABCD'):
            raise ValueError('作答必须是不同的有效选项')
        return value


def attempts(db, learner_id=None):
    rows = db.rows('SELECT * FROM attempts WHERE learner_id=? ORDER BY created_at', (learner_id,)) if learner_id else db.rows('SELECT * FROM attempts ORDER BY created_at')
    return [{**r, 'answers': json.loads(r['answers'])} for r in rows]


def routes(store):
    router, db = APIRouter(), store.db

    @router.get('/study/questions')
    def questions(knowledge_point: str = ''):
        result = []
        for row in store.list(limit=None):
            if row['status'] != 'approved' or not row['sources_valid']:
                continue
            metadata, question = row['metadata'], row['content']
            if knowledge_point and metadata.get('knowledge_point') != knowledge_point:
                continue
            result.append({'id': row['id'], 'revision': question_revision(row), 'topic': question['topic'],
                           'options': question['options'], 'question_type': question['question_type'],
                           'knowledge_point': metadata.get('knowledge_point', '未标注考点'), 'case_narrative': metadata.get('case_narrative', '')})
        return result[:100]

    @router.post('/study/attempts')
    def submit(value: Attempt):
        try:
            row = store.get(value.question_id)
        except KeyError:
            raise HTTPException(404, '题目不存在')
        if row['status'] != 'approved' or not row['sources_valid'] or value.revision != question_revision(row):
            raise HTTPException(409, '题目或依据已变化，请刷新练习')
        correct = set(value.answers) == set(row['content']['answer'])
        identifier = uuid.uuid4().hex
        snapshot = {'selected': value.answers, 'revision': value.revision, 'question': row['content'],
                    'knowledge_point': row['metadata'].get('knowledge_point', '未标注考点'), 'case_narrative': row['metadata'].get('case_narrative', '')}
        with db.connect() as connection:
            connection.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?)',
                               (identifier, value.learner_id, value.question_id, json.dumps(snapshot, ensure_ascii=False), int(correct), value.seconds, now()))
        return {'id': identifier, 'correct': correct, 'answer': row['content']['answer'], 'analysis': row['content']['analysis'],
                'citations': row['content']['citations'], 'evidence': row['evidence']}

    @router.get('/study/history')
    def history(learner_id: str):
        rows = attempts(db, learner_id)
        wrong = defaultdict(lambda: {'attempts': 0, 'wrong': 0, 'question_ids': set()})
        for row in rows:
            point = row['answers']['knowledge_point']
            wrong[point]['attempts'] += 1
            wrong[point]['wrong'] += int(not row['correct'])
            if not row['correct']:
                wrong[point]['question_ids'].add(row['question_id'])
        available = {q['id']: q for q in store.list(limit=None) if q['status'] == 'approved' and q['sources_valid']}
        points = []
        for point, data in wrong.items():
            evidence = {e['id']: e for qid in data['question_ids'] if qid in available for e in available[qid]['evidence']}
            recommendations = [q['id'] for q in available.values() if q['metadata'].get('knowledge_point', '未标注考点') == point and q['id'] not in data['question_ids']][:5]
            points.append({'knowledge_point': point, 'attempts': data['attempts'], 'wrong': data['wrong'],
                           'evidence': list(evidence.values()), 'recommended_question_ids': recommendations})
        return {'attempts': list(reversed(rows))[:200], 'knowledge': sorted(points, key=lambda p: p['wrong'], reverse=True)}

    @router.get('/study/statistics')
    def statistics():
        # First attempt per learner and current question revision avoids repeated-practice inflation.
        current = {q['id']: q for q in store.list(limit=None)}
        first = {}
        for attempt in attempts(db):
            q = current.get(attempt['question_id'])
            if q and attempt['answers'].get('revision') == question_revision(q):
                first.setdefault((attempt['learner_id'], q['id']), attempt)
        totals = defaultdict(list)
        for (learner, _), attempt in first.items():
            totals[learner].append(attempt['correct'])
        eligible = sorted((learner for learner, values in totals.items() if len(values) >= 10), key=lambda p: sum(totals[p]) / len(totals[p]))
        group_size = math.ceil(len(eligible) * .27)
        lower, upper = set(eligible[:group_size]), set(eligible[-group_size:])
        result = []
        for qid, q in current.items():
            rows = [a for (_, question), a in first.items() if question == qid]
            counts = Counter(key for a in rows for key in a['answers']['selected'])
            n = len(rows)
            low = [a['correct'] for a in rows if a['learner_id'] in lower]
            high = [a['correct'] for a in rows if a['learner_id'] in upper]
            discrimination = round(sum(high) / len(high) - sum(low) / len(low), 3) if len(eligible) >= 30 and len(high) >= 5 and len(low) >= 5 else None
            result.append({'question_id': qid, 'topic': q['content']['topic'], 'intended_difficulty': q['content']['difficulty'],
                           'first_attempts': n, 'observed_error_rate': round(1 - sum(a['correct'] for a in rows) / n, 3) if n >= 20 else None,
                           'option_rates': {key: round(counts[key] / n, 3) for key in 'ABCD'} if n >= 20 else None,
                           'discrimination': discrimination})
        return {'items': result, 'method': '当前题目版本、每个本机学习档案的首次作答。错误率与选项率至少20人；探索性区分度需30名各完成10题的学习者，取总正确率上下27%且本题每组至少5人。非标准化考试校准。'}

    return router
