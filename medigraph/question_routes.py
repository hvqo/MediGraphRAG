import csv
import io
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from .questions import GenerationRequest, Question, ReviewRequest


def routes(store, jobs):
    router = APIRouter()

    @router.post('/questions/generate', status_code=202)
    async def generate(value: GenerationRequest):
        return jobs.start(value)

    @router.get('/jobs')
    def list_jobs():
        return store.list_jobs()

    @router.get('/jobs/{identifier}')
    def job(identifier: str):
        try:
            return store.job(identifier)
        except KeyError:
            raise HTTPException(404, '任务不存在')

    @router.get('/questions')
    def questions():
        return store.list()

    @router.get('/questions/export')
    def export(format: str = 'json', approved_only: bool = True):
        if format not in ['json', 'csv']:
            raise HTTPException(422, '导出格式支持 json 或 csv')
        rows = [row for row in store.list() if row['sources_valid'] and (not approved_only or row['status'] == 'approved')]
        if format == 'json':
            content = json.dumps([{'id': row['id'], 'status': row['status'], 'question': row['content'],
                                   'sources': [{'id': e['id'], 'document_id': e['document_id'], 'title': e['title'], 'location': e['location']} for e in row['evidence']]}
                                  for row in rows], ensure_ascii=False, indent=2)
            return Response(content, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="medical-questions.json"'})
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['题干', 'A', 'B', 'C', 'D', '答案', '解析', '审核状态', '来源'])
        def safe(value):
            value = str(value)
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for row in rows:
            q = row['content']
            values = [q['topic'], *[q['options'][key] for key in 'ABCD'], ','.join(q['answer']), q['analysis'], row['status'],
                      '; '.join(e['title'] + ' ' + e['location'] for e in row['evidence'])]
            writer.writerow([safe(value) for value in values])
        return Response('\ufeff' + stream.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="medical-questions.csv"'})

    @router.get('/questions/{identifier}/events')
    def events(identifier: str):
        try:
            store.get(identifier)
            return store.db.rows('SELECT action,detail,created_at FROM question_events WHERE question_id=? ORDER BY id', (identifier,))
        except KeyError:
            raise HTTPException(404, '题目不存在')

    @router.put('/questions/{identifier}')
    def edit(identifier: str, value: Question):
        try:
            return store.edit(identifier, value)
        except KeyError:
            raise HTTPException(404, '题目不存在')
        except ValueError as error:
            raise HTTPException(422, str(error))

    @router.post('/questions/{identifier}/review')
    def review(identifier: str, value: ReviewRequest):
        try:
            return store.review(identifier, value)
        except KeyError:
            raise HTTPException(404, '题目不存在')
        except ValueError as error:
            raise HTTPException(422, str(error))

    return router
