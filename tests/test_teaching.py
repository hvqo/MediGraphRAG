import tempfile
import unittest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from backend.app.questions import Question
from backend.app.teaching import AutomaticReview
from test_questions import FakeModel, wait_job


def fixture(client):
    doc = client.post('/documents/text', json={'title': '教学软件验收', 'text': '软件验收中，标签甲与标签乙关联。此为非临床软件测试资料。'}).json()
    evidence = client.get('/documents/' + doc['id']).json()['chunks'][0]
    citation = {'evidence_id': evidence['id'], 'quote': evidence['text']}
    question = Question(topic='软件验收中哪个标签与标签乙关联？', options=dict(zip('ABCD', ['标签甲', '标签丙', '标签丁', '标签戊'])), answer=['A'], analysis='依据软件测试声明确定标签。', citations=[citation])
    review = {'supported': True, 'answer_valid': True, 'ambiguous': False, 'leaks_answer': False, 'reason': '软件测试审核',
              'options': {key: {'correct': key == 'A', 'reason': '软件测试逐项理由', 'citations': [citation]} for key in 'ABCD'}}
    return doc, evidence, question, review


class TeachingTests(unittest.TestCase):
    def test_option_reviews_reject_multiple_correct_and_missing_quote(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            _, evidence, q, review = fixture(client)
            checked = AutomaticReview.model_validate(review)
            checked.check(q, [evidence])
            checked.options['B'].correct = True
            with self.assertRaises(ValueError):
                checked.check(q, [evidence])
            checked.options['B'].correct = False
            checked.options['B'].citations[0].quote = '不存在的软件测试引文'
            with self.assertRaises(ValueError):
                checked.check(q, [evidence])

    def test_blueprint_preflight_shared_case_and_coverage(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            doc, _, q, review = fixture(client)
            case = client.post('/cases', json={'title': '软件测试病例材料', 'narrative': '虚构教学情境：此处的甲乙都是软件标签。', 'citations': [c.model_dump() for c in q.citations]}).json()
            row = {'knowledge_point': '标签关联', 'query': '软件验收标签', 'count': 1, 'case_id': case['id']}
            blueprint = client.post('/blueprints', json={'title': '测试出题蓝图', 'rows': [row]}).json()
            self.assertEqual(client.post('/blueprints/' + blueprint['id'] + '/generate').status_code, 422)
            self.assertEqual(client.get('/jobs').json(), [])
            client.post('/cases/' + case['id'] + '/review', json={'status': 'approved'})
            client.app.state.jobs.model = FakeModel([q.model_dump(), review])
            result = client.post('/blueprints/' + blueprint['id'] + '/generate').json()
            job = wait_job(client, result['jobs'][0]['id'])
            self.assertEqual(job['status'], 'completed')
            qid = job['result']['question_ids'][0]
            question = client.get('/questions/' + qid).json()
            self.assertEqual(question['metadata']['case_narrative'], case['narrative'])
            self.assertIn('B', question['automatic_review']['options'])
            client.post('/questions/' + qid + '/review', json={'status': 'approved'})
            self.assertEqual(client.get('/blueprints').json()[0]['rows'][0]['approved'], 1)
            client.delete('/documents/' + doc['id'])
            self.assertEqual(client.get('/blueprints').json()[0]['rows'][0]['missing'], 1)

    def test_learning_hides_answers_then_tracks_revision_and_wrong_point(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            doc, _, q, _ = fixture(client)
            qid = client.app.state.questions.save(q, metadata={'knowledge_point': '标签关联'})
            self.assertEqual(client.get('/study/questions').json(), [])
            client.post('/questions/' + qid + '/review', json={'status': 'approved'})
            public = client.get('/study/questions').json()[0]
            self.assertNotIn('answer', public)
            payload = {'learner_id': '测试学习者', 'question_id': qid, 'revision': public['revision'], 'answers': ['B']}
            result = client.post('/study/attempts', json=payload).json()
            self.assertFalse(result['correct'])
            self.assertEqual(result['answer'], ['A'])
            history = client.get('/study/history', params={'learner_id': '测试学习者'}).json()
            self.assertEqual(history['knowledge'][0]['wrong'], 1)
            self.assertIsNone(client.get('/study/statistics').json()['items'][0]['observed_error_rate'])
            q.topic += '（修订后）'
            client.put('/questions/' + qid, json=q.model_dump())
            client.post('/questions/' + qid + '/review', json={'status': 'approved'})
            self.assertEqual(client.post('/study/attempts', json=payload).status_code, 409)
            self.assertEqual(client.get('/study/statistics').json()['items'][0]['first_attempts'], 0)
            client.delete('/documents/' + doc['id'])
            self.assertEqual(client.get('/study/questions').json(), [])

    def test_evaluation_reports_real_modes_and_stale_source(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            doc, evidence, _, _ = fixture(client)
            suite = client.post('/evaluations', json={'name': '软件检索验收集', 'samples': [{'query': '标签甲', 'expected_evidence_ids': [evidence['id']]}]}).json()
            result = client.post('/evaluations/' + suite['id'] + '/run', json={'modes': ['keyword', 'vector']}).json()['report']
            self.assertFalse(result['suite_reviewed'])
            self.assertEqual(result['results'][0]['recall'], 1)
            self.assertFalse(result['results'][1]['available'])
            self.assertIsNone(result['results'][1]['recall'])
            self.assertIsNone(result['results'][0]['human_rating'])
            client.delete('/documents/' + doc['id'])
            self.assertEqual(client.post('/evaluations/' + suite['id'] + '/run', json={}).status_code, 409)
