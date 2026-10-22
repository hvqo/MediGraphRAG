import asyncio
import json
import logging
from typing import Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from .evidence import Citation, SYSTEM, compact, context, validate_citations
from .llm import ModelError
from .storage import now

logger = logging.getLogger(__name__)


class GenerationRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    question_type: Literal['single_choice', 'multiple_choice', 'case'] = 'single_choice'
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'
    count: int = Field(default=1, ge=1, le=10)


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic: str = Field(min_length=1, max_length=3000)
    options: dict[str, str]
    answer: list[str] = Field(min_length=1, max_length=4)
    analysis: str = Field(min_length=1, max_length=4000)
    citations: list[Citation] = Field(min_length=1, max_length=8)
    question_type: Literal['single_choice', 'multiple_choice', 'case'] = 'single_choice'
    difficulty: Literal['easy', 'medium', 'hard'] = 'medium'

    @model_validator(mode='after')
    def consistent(self):
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

    def list(self):
        return [self.get(row['id']) for row in self.db.rows('SELECT id FROM questions ORDER BY created_at DESC LIMIT 500')]

    def evidence(self, question):
        ids = list({item.evidence_id for item in question.citations})
        placeholders = ','.join('?' for _ in ids)
        return self.db.rows(f'''SELECT c.*,d.title,d.filename FROM chunks c JOIN documents d ON d.id=c.document_id
                               WHERE c.id IN ({placeholders})''', ids)

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
        return {**row, 'content': content.model_dump(), 'sources_valid': self.valid_sources(content), 'evidence': self.evidence(content)}

    def save(self, question, job_id=None):
        if not self.valid_sources(question):
            raise ValueError('资料已变化或引用无效，题目未保存')
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.db.connect() as connection:
            connection.execute('INSERT INTO questions VALUES (?,?,?,?,?,?,?)',
                               (identifier, job_id, question.model_dump_json(), 'pending_review', '', timestamp, timestamp))
            connection.execute('INSERT INTO question_events(question_id,action,detail,created_at) VALUES (?,?,?,?)',
                               (identifier, 'generated', '通过自动检查，等待人工审核', timestamp))
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

    def recover(self):
        with self.store.db.connect() as connection:
            connection.execute("UPDATE jobs SET status='interrupted',stage='服务重启，任务已中断',error='请重新发起生成',updated_at=? WHERE status IN ('queued','running')", (now(),))

    def start(self, request):
        identifier, timestamp = uuid.uuid4().hex, now()
        with self.store.db.connect() as connection:
            connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                               (identifier, 'queued', 0, '等待生成', request.model_dump_json(), '{}', '', timestamp, timestamp))
        task = asyncio.create_task(self.run(identifier, request))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.store.job(identifier)

    async def shutdown(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def run(self, identifier, request):
        saved = []
        model = self.model.snapshot() if hasattr(self.model, 'snapshot') else self.model
        try:
            self.store.update_job(identifier, status='running', stage='检索原文依据', progress=5)
            result = await run_in_threadpool(self.retriever.search, request.query)
            evidence = result['items']
            if not evidence:
                raise ModelError('没有找到可用原文，请先导入资料或调整考点')
            for number in range(request.count):
                last_error = None
                for attempt in range(2):
                    self.store.update_job(identifier, stage=f'生成并核验第 {number + 1}/{request.count} 题（尝试 {attempt + 1}）', progress=10 + int(80 * number / request.count))
                    try:
                        raw = await model.json(SYSTEM, f'考点：{request.query}\n题型：{request.question_type}；难度：{request.difficulty}。'
                            f'请生成一道不同于已生成题目的医学练习题。已生成题干：{[self.store.get(q)["content"]["topic"] for q in saved]}\n'
                            f'资料：{context(evidence)}\n只输出一个对象：'
                            '{"topic":"题干","options":{"A":"选项","B":"选项","C":"选项","D":"选项"},'
                            '"answer":["A"],"analysis":"答案和各选项解析","citations":[{"evidence_id":"ID","quote":"原文短句"}],'
                            f'"question_type":"{request.question_type}","difficulty":"{request.difficulty}"}}。'
                            'single_choice 和 case 只有一个正确答案，multiple_choice 至少两个。case 使用病例情境；病例中的虚构细节不能引入无依据的医学结论。')
                        question = Question.model_validate(raw)
                        if question.question_type != request.question_type or question.difficulty != request.difficulty:
                            raise ValueError('题型或难度与请求不一致')
                        validate_citations(question.citations, evidence)
                        if any(compact(self.store.get(q)['content']['topic']) == compact(question.topic) for q in saved):
                            raise ValueError('生成了重复题干')
                        review = await model.json(SYSTEM, '你是独立审题环节。检查答案和解析是否由资料支持、答案集合是否正确，'
                            '单选或病例题是否存在多个正确答案、干扰项是否含糊、题干是否直接泄漏答案。'
                            '资料不足或不相关时拒绝。输出 {"supported":true或false,"answer_valid":true或false,"ambiguous":true或false,"reason":"原因"}。\n'
                            f'资料：{context(evidence)}\n题目：{question.model_dump_json()}')
                        if review.get('supported') is not True or review.get('answer_valid') is not True or review.get('ambiguous') is not False:
                            raise ValueError('模型复核未通过')
                        saved.append(self.store.save(question, identifier))
                        self.store.update_job(identifier, result=json.dumps({'question_ids': saved, 'requested': request.count}))
                        last_error = None
                        break
                    except (ValueError, ModelError) as error:
                        last_error = str(error) if isinstance(error, ModelError) else '题目未通过结构、引用或答案复核'
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
                                  result=json.dumps({'question_ids': saved, 'requested': request.count}))
