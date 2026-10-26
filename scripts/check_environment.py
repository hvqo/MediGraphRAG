"""Check package imports and GPU execution without models or database writes."""
import importlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import traceback

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
report = {'python': sys.version.split()[0], 'executable': sys.executable, 'checks': {}}


def check(name, operation):
    try:
        result = operation()
        report['checks'][name] = {'ok': True, 'detail': result}
        print(f'PASS {name}: {result}', flush=True)
    except Exception as exc:
        report['checks'][name] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}
        print(f'FAIL {name}: {type(exc).__name__}: {exc}', flush=True)
        traceback.print_exc()


def gpu():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable')
    a = torch.arange(16, device='cuda', dtype=torch.float32).reshape(4, 4)
    result = a @ a.T
    torch.cuda.synchronize()
    assert result.shape == (4, 4) and result[0, 0].item() == 14.0
    return {'torch': torch.__version__, 'cuda': torch.version.cuda, 'gpu': torch.cuda.get_device_name(0)}


def vector_search():
    import faiss
    import numpy as np
    vectors = np.array([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
    index = faiss.IndexFlatL2(2)
    index.add(vectors)
    distances, positions = index.search(vectors[:1], 1)
    assert positions[0, 0] == 0 and distances[0, 0] == 0
    return f'FAISS {faiss.__version__}; NumPy {np.__version__}; search passed'


check('gpu', gpu)
check('vector_search', vector_search)
for module in ['transformers', 'gensim', 'fastapi', 'uvicorn', 'neo4j', 'yaml',
               'langchain', 'langchain_community', 'langchain_core', 'lancedb',
               'metagpt.team', 'metagpt.actions', 'metagpt.roles',
               'legacy.utils.generate', 'legacy.agent.knowCleaner', 'legacy.agent.questionGenerator']:
    check(module, lambda name=module: str(importlib.import_module(name).__file__))

report['metagpt_distribution'] = version('metagpt')
report['application_prerequisites'] = {
    'faiss_index_exists': (root / 'data/faiss_index/faiss_index.index').exists(),
    'faiss_metadata_exists': (root / 'data/faiss_index/matedata.npy').exists(),
    'embedding_weights_exist': any((root / 'model/bge-large-zh-v1.5' / name).exists()
                                  for name in ['pytorch_model.bin', 'model.safetensors']),
    'reranker_weights_exist': (root / 'model/bge-reranker-v2-m3/model.safetensors').exists(),
}
destination = root / 'environment-check.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Report: {destination}')
sys.exit(0 if all(item['ok'] for item in report['checks'].values()) else 1)
