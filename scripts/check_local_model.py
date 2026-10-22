"""Real Ollama smoke check using non-clinical fixture data, isolated from the user's library."""
import asyncio
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from medigraph.config import SettingsStore
from medigraph.documents import DocumentStore
from medigraph.evidence import answer_question
from medigraph.llm import ModelClient
from medigraph.questions import GenerationJobs, GenerationRequest, QuestionStore
from medigraph.retrieval import Retriever
from medigraph.storage import Database


class RecordingModel(ModelClient):
    def __init__(self, store):
        super().__init__(store)
        self.responses = []
    def snapshot(self):
        return self
    async def json(self, system, prompt):
        result = await super().json(system, prompt)
        self.responses.append(result)
        return result


async def main():
    with tempfile.TemporaryDirectory() as directory:
        settings = SettingsStore(directory)
        model = RecordingModel(settings)
        connection = await model.check()
        print('Ollama connection:', connection['ok'], flush=True)
        if not connection['ok']:
            raise RuntimeError(connection['message'])
        db = Database(directory)
        DocumentStore(db).add('软件验收说明.txt',
            '本资料仅用于医学教育软件的功能验收，不提供诊疗知识。资料标签中，糖尿病的测试编号为 T-001，高血压的测试编号为 T-002，肺炎的测试编号为 T-003。'.encode('utf-8'))
        retriever = Retriever(db, settings)
        query = '根据资料，糖尿病标签的测试编号是什么？'
        result = await answer_question(model, query, retriever.search(query))
        print('Real answer status:', result['status'], flush=True)
        store = QuestionStore(db)
        jobs = GenerationJobs(store, retriever, model)
        request = GenerationRequest(query='根据资料中的标签编号，考察糖尿病、高血压与肺炎的测试编号对应关系。只考察软件测试标签，不考察诊疗知识。', difficulty='easy')
        job = jobs.start(request)
        await asyncio.gather(*jobs.tasks)
        outcome = store.job(job['id'])
        print('Real generation status:', outcome['status'], flush=True)
        report = {'fixture': 'Non-clinical software acceptance labels; no medical accuracy claim',
                  'model': settings.get().ollama_model, 'answer': result, 'job': outcome, 'responses': model.responses}
        output = Path('.runtime/local-model-check.json')
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if result['status'] != 'draft' or outcome['status'] != 'completed':
            raise RuntimeError('Real model output did not pass acceptance checks; see local report')


if __name__ == '__main__':
    asyncio.run(main())
