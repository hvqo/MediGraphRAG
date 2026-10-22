import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from medigraph.storage import now
from medigraph.questions import Question
from web.api.main import create_app


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
    async def json(self, *args):
        return next(self.replies)


def wait_job(client, identifier):
    for _ in range(100):
        row = client.get('/jobs/' + identifier).json()
        if row['status'] not in ['queued', 'running']:
            return row
        time.sleep(.01)
    raise AssertionError('Job did not finish')


class QuestionTests(unittest.TestCase):
    def test_placeholder_stem_is_rejected(self):
        with self.assertRaises(ValueError):
            Question(topic='题干', options=dict(zip('ABCD', ['甲', '乙', '丙', '丁'])), answer=['A'], analysis='测试解析内容',
                     citations=[{'evidence_id': 'test', 'quote': '测试原文内容'}])

    def test_generation_review_edit_and_deleted_source(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            document = client.post('/documents/text', json={'title': '软件测试资料', 'text': '糖尿病与血糖用于检索测试，本段并非医学知识依据。'}).json()
            source = client.get('/documents/' + document['id']).json()['chunks'][0]
            question = {'topic': '=1+1 软件测试题', 'options': dict(zip('ABCD', ['选项甲', '选项乙', '选项丙', '选项丁'])),
                        'answer': ['A'], 'analysis': '这是一条软件测试解析。',
                        'citations': [{'evidence_id': source['id'], 'quote': source['text']}],
                        'question_type': 'single_choice', 'difficulty': 'medium'}
            client.app.state.jobs.model = FakeModel([question, {'supported': True, 'answer_valid': True, 'ambiguous': False}])
            response = client.post('/questions/generate', json={'query': '糖尿病'})
            self.assertEqual(response.status_code, 202)
            job = wait_job(client, response.json()['id'])
            self.assertEqual(job['status'], 'completed')
            identifier = job['result']['question_ids'][0]
            self.assertEqual(client.get('/questions').json()[0]['status'], 'pending_review')
            self.assertEqual(client.get('/questions/export').json(), [])
            self.assertEqual(client.post(f'/questions/{identifier}/review', json={'status': 'approved'}).status_code, 200)
            self.assertEqual(len(client.get('/questions/export').json()), 1)
            self.assertIn("'=1+1", client.get('/questions/export?format=csv').text)
            self.assertEqual(client.put('/questions/' + identifier, json=question).json()['status'], 'pending_review')
            client.delete('/documents/' + document['id'])
            self.assertEqual(client.post(f'/questions/{identifier}/review', json={'status': 'approved'}).status_code, 422)
            self.assertFalse(client.get('/questions').json()[0]['sources_valid'])
            actions = [item['action'] for item in client.get(f'/questions/{identifier}/events').json()]
            self.assertEqual(actions, ['generated', 'approved', 'edited'])

    def test_invalid_question_never_saved(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            client.post('/documents/text', json={'title': '检索测试', 'text': '高血压软件测试资料。'})
            client.app.state.jobs.model = FakeModel([{'topic': '缺少答案'}, {'topic': '仍缺少答案'}])
            job = client.post('/questions/generate', json={'query': '高血压'}).json()
            self.assertEqual(wait_job(client, job['id'])['status'], 'failed')
            self.assertEqual(len(wait_job(client, job['id'])['result']['attempts']), 2)
            self.assertEqual(client.get('/questions').json(), [])

    def test_restart_marks_unfinished_job_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(directory)
            timestamp = now()
            with app.state.db.connect() as connection:
                connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)', ('test', 'running', 20, '正在生成', '{}', '{}', '', timestamp, timestamp))
            with TestClient(create_app(directory)) as client:
                self.assertEqual(client.get('/jobs/test').json()['status'], 'interrupted')
