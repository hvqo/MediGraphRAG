"""Recover historical notebook sources as import-safe Python archives.

Default mode verifies the committed migration. --write regenerates the archives
from the recorded Git revision. Notebook outputs and kernel metadata are omitted.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'cf06dbd8c34844ca0c552c3addaeb78b06e632c5'
SOURCES = {
    'docx/process/data/dataProcess.ipynb': 'data_pipeline',
    'docx/process/data/dataProcess_tex.ipynb': 'textbook_pipeline',
    'docx/process/rag/ragProcess.ipynb': 'rag_pipeline',
}
STAR_REPLACEMENT = ('from legacy.prototypes.rag.Embedding import (LoadModel, encode_text, '
                    'warnings, os, pd, tqdm, KeyedVectors, AutoModel, AutoTokenizer, torch, nn)')


def sha(content):
    return hashlib.sha256(content).hexdigest()


def artifacts():
    files, manifest = {}, {'source_revision': REVISION, 'notebooks': []}
    for source_path, name in SOURCES.items():
        original = subprocess.check_output(['git', 'show', REVISION + ':' + source_path], cwd=ROOT)
        notebook = json.loads(original)
        target = f'legacy/experiments/{name}.py'
        record = {'original_path': source_path, 'original_sha256': sha(original), 'python_path': target, 'cells': []}
        code = ['"""Historical experiment recovered from ' + source_path + '.\n\n'
                'Source preserved for reference, not the supported application pipeline.\n'
                'Imports are safe: no model calls or data writes occur on import.\n'
                'Use python -m backend.app.cli for maintained offline operations.\n"""\n\n',
                'def historical_pipeline():\n']
        markdown = [f'# Historical notes: {name}\n\nOriginal: `{source_path}` at `{REVISION}`.\n\n']
        for number, cell in enumerate(notebook.get('cells', []), 1):
            source = ''.join(cell.get('source', []))
            if cell['cell_type'] == 'code':
                converted = source.replace('from Embedding import *', STAR_REPLACEMENT).strip('\n')
                ast.parse(converted)
                code += [f'    # source-cell:{number}\n', textwrap.indent(converted, '    ') + '\n\n']
                record['cells'].append({'number': number, 'original_source_sha256': sha(source.encode()),
                                        'exported_source_sha256': sha(converted.encode()),
                                        'rewritten_star_import': source != source.replace('from Embedding import *', STAR_REPLACEMENT)})
            elif cell['cell_type'] == 'markdown' and source.strip():
                markdown.append(f'<!-- source-cell:{number} -->\n\n{source}\n\n')
        code.append('\nif __name__ == "__main__":\n'
                    '    print("Historical source archive. Use python -m backend.app.cli --help for supported commands.")\n')
        python = ''.join(code)
        compile(python, target, 'exec')
        files[target] = python
        files[f'docs/legacy/{name}_notes.md'] = ''.join(markdown).rstrip() + '\n'
        record['export_sha256'] = sha(python.encode())
        manifest['notebooks'].append(record)
    files['docs/legacy/notebook_migration.json'] = json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'
    return files, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Write archives from the recorded Git revision')
    options = parser.parse_args()
    files, manifest = artifacts()
    for relative, content in files.items():
        path = ROOT / relative
        if options.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        elif not path.exists() or path.read_text(encoding='utf-8') != content:
            raise SystemExit(f'Migration verification failed: {relative}')
    count = sum(len(item['cells']) for item in manifest['notebooks'])
    print(f'Verified {len(manifest["notebooks"])} notebook migrations and {count} source cells; no notebook execution.')


if __name__ == '__main__':
    main()
