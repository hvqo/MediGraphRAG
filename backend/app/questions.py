import asyncio
import json
import logging
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from .evidence import Citation, SYSTEM, compact, context, validate_citations
from .llm import ModelError, for_task
from .teaching import AutomaticReview, approved_case
from .storage import now

logger = logging.getLogger(__name__)


class GenerationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    question_type: Literal['single_choice', 'multiple_choice', 'case'] = 'single_choice'
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'
    count: int = Field(default=1, ge=1, le=10)
    document_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    chapter: str = Field(default='', max_length=300)
    knowledge_point: str = Field(default='', max_length=200)
    cognition: Literal['remember', 'understand', 'apply', 'analyze'] = 'understand'
    case_id: str | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: str = Field(min_length=8, max_length=3000, description='不少于8个字的完整具体题干，包含明确的问题，不是资料标题或占位符')
    options: dict[str, str]
    answer: list[str] = Field(min_length=1, max_length=4)
    analysis: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(min_length=1, max_length=8)
    question_type: Literal['single_choice', 'multiple_choice', 'case'] = 'single_choice'
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'

    @model_validator(mode='after')
    def consistent(self):
        placeholders = {'题干', '题目', '问题', '示例题干', '请填写题干', '答案和各选项解析', '答案解析', '解析'}
        if compact(self.topic) in placeholders or compact(self.analysis) in placeholders:
            raise ValueError('题干和解析必须是实际内容，不能是格式占位文字')
        if set(self.options) != set('ABCD') or any(not value.strip() for value in self.options.values()):
            raise ValueError('选项必须为非空的 A、B、C、D')
        if len({compact(value).casefold() for value in self.options.values()}) != 4:
            raise ValueError('选项不能重复')
        if len(set(self.answer)) != len(self.answer) or not set(self.answer) <= set(self.options):
            raise ValueError('答案必须对应选项且不能重复')
        if (self.question_type == 'multiple_choice' and len(self.answer) < 2) or (self.question_type != 'multiple_choice' and len(self.answer) != 1):
            raise ValueError('答案数量与题型不符')
        return self


class ReviewRequest(BaseModel):
    status: Literal['approved', 'rejected']
    note: str = Field(default='', max_length=1000)


class QuestionStore:
    def __init__(self, db):
        self.db = db
        with db.connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, progress INTEGER NOT NULL,
                    stage TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL,
                    error TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, job_id TEXT, content TEXT NOT NULL,
                    status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS question_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, question_id TEXT NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL
                );
            ''')

    def job(self, identifier):
        rows = self.db.rows('SELECT * FROM jobs WHERE id=?', (identifier,))
        if not rows:
            raise KeyError(identifier)
        row = rows[0]
        return {**row, 'request': json.loads(row['request']), 'result': json.loads(row['result'])}

    def update_job(self, identifier, **values):
        values['updated_at'] = now()
        with self.db.connect() as connection:
            connection.execute('UPDATE jobs SET ' + ','.join(key + '=?' for key in values) + ' WHERE id=?', (*values.values(), identifier))

    def list_jobs(self):
        return [self.job(row['id']) for row in self.db.rows('SELECT id FROM jobs ORDER BY created_at DESC LIMIT 30')]

    def list(self, limit=500):
        query = 'SELECT id FROM questions ORDER BY created_at DESC'
        rows = self.db.rows(query + ' LIMIT ?', (limit,)) if limit else self.db.rows(query)
        return [self.get(row['id']) for row in rows]

    def evidence(self, question):
        ids = list({item.evidence_id for item in question.citations})
        placeholders = ','.join('?' for _ in ids)
        return self.db.rows(f'''SELECT c.*,d.title,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                               LEFT JOIN document_meta dm ON dm.document_id=d.id
                               WHERE c.id IN ({placeholders}) AND coalesce(dm.active,1)=1''', ids)

    def valid_sources(self, question):
        try:
            validate_citations(question.citations, self.evidence(question))
            return True
        except ValueError:
            return False

    def get(self, identifier):
        rows = self.db.rows('SELECT * FROM questions WHERE id=?', (identifier,))
        if not rows:
            raise KeyError(identifier)
        row = rows[0]
        content = Question.model_validate_json(row['content'])
        extras = self.db.rows('SELECT * FROM question_meta WHERE question_id=?', (identifier,))
        metadata = json.loads(extras[0]['metadata']) if extras else {}
        valid = self.valid_sources(content)
        if metadata.get('case_id'):
            try:
                approved_case(self.db, metadata['case_id'])
                validate_citations([Citation.model_validate(c) for c in metadata.get('case_citations', [])], self.db.chunks())
            except ValueError:
                valid = False
        return {**row, 'content': content.model_dump(), 'sources_valid': valid, 'evidence': self.evidence(content),
                'metadata': metadata, 'automatic_review': json.loads(extras[0]['review']) if extras else {}}

    def save(self, question, job_id=None, metadata=None, review=None):
        if not self.valid_sources(question):
            raise ValueError('资料已变化或引用无效，题目未保存')
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.db.connect() as connection:
            connection.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?)',
                               (identifier, job_id, question.model_dump_json(), 'pending_review', '', timestamp, timestamp))
            connection.execute('INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)',
                               (identifier, 'generated', '通过自动检查，等待人工审核', timestamp))
            connection.execute('INSERT INTO question_meta VALUES (?,?,?)', (identifier, json.dumps(metadata or {}, ensure_ascii=False), json.dumps(review or {}, ensure_ascii=False)))
        return identifier

    def edit(self, identifier, question):
        self.get(identifier)
        if not self.valid_sources(question):
            raise ValueError('引用无效，无法保存编辑')
        with self.db.connect() as connection:
            connection.execute('UPDATE questions SET content=?,status=?,note=?,updated_at=? WHERE id=?',
                               (question.model_dump_json(), 'pending_review', '编辑后需要重新审核', now(), identifier))
            connection.execute('INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)',
                               (identifier, 'edited', '人工编辑，审核状态已重置', now()))
            connection.execute("UPDATE question_meta SET review='{}' WHERE question_id=?", (identifier,))
        return self.get(identifier)

    def review(self, identifier, value):
        row = self.get(identifier)
        if value.status == 'approved' and not row['sources_valid']:
            raise ValueError('原文资料已删除或引用失效，不能审核通过')
        with self.db.connect() as connection:
            connection.execute('UPDATE questions SET status=?,note=?,updated_at=? WHERE id=?', (value.status, value.note, now(), identifier))
            connection.execute('INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)',
                               (identifier, value.status, value.note, now()))
        return self.get(identifier)


class GenerationJobs:
    def __init__(self, store, retriever, model):
        self.store, self.retriever, self.model = store, retriever, model
        self.tasks = set()
        self.semaphore = asyncio.Semaphore(1)

    def recover(self):
        with self.store.db.connect() as connection:
            connection.execute("UPDATE jobs SET status='interrupted',stage='服务重启，任务已中断',error='请重新发起生成',updated_at=? WHERE status IN ('queued','running')", (now(),))

    def start(self, request, metadata=None):
        if request.case_id:
            approved_case(self.store.db, request.case_id)
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.store.db.connect() as connection:
            connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                               (identifier, 'queued', 0, '等待生成', request.model_dump_json(), '{}', '', timestamp, timestamp))
        task = asyncio.create_task(self.run(identifier, request, metadata))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.store.job(identifier)

    async def shutdown(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def run(self, identifier, request, metadata=None):
        async with self.semaphore:
            await self._run(identifier, request, metadata)

    async def _run(self, identifier, request, metadata=None):
        saved = []
        attempts = []
        model = for_task(self.model, 'generation', 'question-v2')
        reviewer = for_task(self.model, 'review', 'option-review-v2')
        try:
            self.store.update_job(identifier, status='running', stage='检索原文依据', progress=5)
            result = await run_in_threadpool(self.retriever.search, request.query, None, request.document_id, request.evidence_ids)
            evidence = result['items']
            case = approved_case(self.store.db, request.case_id) if request.case_id else None
            if case:
                case_ids = {c['evidence_id'] for c in case['citations']}
                evidence = list({c['id']: c for c in evidence + [c for c in self.store.db.chunks() if c['id'] in case_ids]}.values())
            if not evidence:
                raise ModelError('没有找到可用原文，请先导入资料或调整考点')
            for number in range(request.count):
                last_error = None
                for attempt in range(2):
                    raw = None
                    self.store.update_job(identifier, stage=f'生成并核验第 {number + 1}/{request.count} 题（尝试 {attempt + 1}）', progress=10 + int(80 * number / request.count))
                    try:
                        raw = await model.json(SYSTEM, f'共享病例材料（不得改动病例事实）：{case["narrative"] if case else "无"}\n认知层次：{request.cognition}；章节：{request.chapter}。\n上次未通过的原因：{last_error or "无"}。如有错误，请严格修正。\n考点：{request.query}\n题型：{request.question_type}；难度：{request.difficulty}。'
                            f'请生成一道不同于已生成题目的医学练习题。必须写出完整具体的问题；不能把格式示例中的“题干”“选项”“答案和各选项解析”当成实际内容。已生成题干：{[self.store.get(q)["content"]["topic"] for q in saved]}\n'
                            f'资料：{context(evidence)}\n只输出一个实际题目对象。topic 必须是完整具体的问题，不能是资料名称。'
                            'options 为四个实际选项；answer 是正确选项字母数组；analysis 说明答案及各干扰项。'
                            'citations 引用提供的片段 ID 并逐字复制支持答案的原文短句。'
                            f'question_type 必须为 {request.question_type}，difficulty 必须为 {request.difficulty}。'
                            f'输出结构遵循：{json.dumps(Question.model_json_schema(), ensure_ascii=False)}。'
                            'single_choice 和 case 只有一个正确答案，multiple_choice 至少两个。case 使用病例情境；病例中的虚构细节不能引入无依据的医学结论。')
                        question = Question.model_validate(raw)
                        if question.question_type != request.question_type or question.difficulty != request.difficulty:
                            raise ValueError('题型或难度与请求不一致')
                        validate_citations(question.citations, evidence)
                        if any(compact(self.store.get(q)['content']['topic']) == compact(question.topic) for q in saved):
                            raise ValueError('生成了重复题干')
                        review = await reviewer.json(SYSTEM, '你是独立审题环节。逐项检查选项、答案和解析是否由资料支持、答案集合是否正确，'
                            '单选或病例题是否存在多个正确答案、干扰项是否含糊、题干是否直接泄漏答案。'
                            f'资料不足或不相关时拒绝。输出结构：{json.dumps(AutomaticReview.model_json_schema(), ensure_ascii=False)}。options 必须包含 ABCD，每项 correct 指是否为正确答案，reason 说明依据与歧义，citations 提供逐字引文。leaks_answer 表示题干直接泄漏答案。\n'
                            f'共享病例：{case["narrative"] if case else "无"}\n资料：{context(evidence)}\n题目：{question.model_dump_json()}')
                        checked = AutomaticReview.model_validate(review)
                        checked.check(question, evidence)
                        from .retrieval import revision
                        provenance = {**(metadata or {}), 'chapter': request.chapter, 'knowledge_point': request.knowledge_point or request.query,
                                      'cognition': request.cognition, 'case_id': request.case_id, 'case_narrative': case['narrative'] if case else '',
                                      'case_citations': case['citations'] if case else [],
                                      'template': 'question-v2', 'review_template': 'option-review-v2', 'source_revision': revision(evidence),
                                      'review_uses_same_model': getattr(model, 'store', None) is None or
                                        (model.store.get().provider, model.store.get().ollama_model, model.store.get().cloud_model) ==
                                        (reviewer.store.get().provider, reviewer.store.get().ollama_model, reviewer.store.get().cloud_model)}
                        saved.append(self.store.save(question, identifier, provenance, checked.model_dump()))
                        attempts.append({'question': number + 1, 'attempt': attempt + 1, 'outcome': 'passed'})
                        self.store.update_job(identifier, result=json.dumps({'question_ids': saved, 'requested': request.count, 'attempts': attempts}))
                        last_error = None
                        break
                    except (ValueError, ModelError) as error:
                        if isinstance(error, ValidationError):
                            fields = {'topic': '题干', 'options': '选项', 'answer': '答案', 'analysis': '解析',
                                      'citations': '原文引用', 'question_type': '题型', 'difficulty': '难度'}
                            reasons = {'missing': '缺少必要内容', 'string_too_short': '内容过短或不完整',
                                       'too_short': '数量不足', 'literal_error': '不符合指定要求',
                                       'list_type': '应为列表格式', 'extra_forbidden': '包含未定义字段'}
                            last_error = '；'.join(fields.get(str(item['loc'][0]) if item['loc'] else '', '题目') + '：' +
                                reasons.get(item['type'], '格式或内容不符合要求') for item in error.errors(include_input=False))[:800]
                        else:
                            last_error = str(error)[:800]
                        attempts.append({'question': number + 1, 'attempt': attempt + 1, 'outcome': 'rejected', 'reason': last_error})
                        with self.store.db.connect() as connection:
                            connection.execute('INSERT INTO rejected_candidates VALUES (?,?,?,?,?)', (uuid.uuid4().hex, identifier, json.dumps(raw, ensure_ascii=False), last_error, now()))
                        self.store.update_job(identifier, result=json.dumps({'question_ids': saved, 'requested': request.count, 'attempts': attempts}))
                if last_error:
                    raise ModelError(last_error)
            self.store.update_job(identifier, status='completed', stage='生成完成，等待人工审题', progress=100)
        except asyncio.CancelledError:
            self.store.update_job(identifier, status='interrupted', stage='任务中断', error='服务已停止，请重新发起生成')
            raise
        except Exception as error:
            message = str(error) if isinstance(error, ModelError) else '生成失败，请检查资料和模型配置'
            logger.warning('Question job failed: %s', identifier)
            self.store.update_job(identifier, status='failed', stage='生成失败', error=f'{message}；已保存 {len(saved)}/{request.count} 道待审题',
                                  result=json.dumps({'question_ids': saved, 'requested': request.count, 'attempts': attempts}))
