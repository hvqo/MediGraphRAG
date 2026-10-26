"""Maintained command-line entry points; no notebook or kernel is required."""
import argparse
import json
from pathlib import Path

from .config import SettingsStore
from .documents import DocumentStore
from .retrieval import Retriever
from .storage import Database


def main(argv=None):
    parser = argparse.ArgumentParser(description='MediGraphRAG Python service and offline tools')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true')
    commands = parser.add_subparsers(dest='command')
    serve = commands.add_parser('serve', help='Start API and the built Vue frontend')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', type=int, default=8000)
    serve.add_argument('--reload', action='store_true')
    ingest = commands.add_parser('import-documents', help='Import PDF, DOCX, TXT or Markdown')
    ingest.add_argument('path', type=Path)
    ingest.add_argument('--recursive', action='store_true')
    ingest.add_argument('--dry-run', action='store_true', help='List matching files without writing data')
    search = commands.add_parser('search', help='Search original evidence without generating an answer')
    search.add_argument('query')
    search.add_argument('--top-k', type=int, choices=range(1, 11), default=5)
    commands.add_parser('build-index', help='Build optional BGE/FAISS vectors for imported evidence')
    commands.add_parser('status', help='Show document counts and index status')
    args = parser.parse_args(argv)
    if args.command in (None, 'serve'):
        import uvicorn
        uvicorn.run('backend.app.main:app', host=args.host, port=args.port, reload=args.reload)
        return 0
    if args.command == 'import-documents' and args.dry_run:
        source = args.path.expanduser().resolve()
        if not source.exists():
            parser.error('Input path does not exist')
        files = [source] if source.is_file() else sorted(source.rglob('*') if args.recursive else source.iterdir())
        result = {'dry_run': True, 'files': [{'path': str(file)} for file in files
                  if file.is_file() and file.suffix.lower() in {'.pdf', '.docx', '.txt', '.md', '.markdown'}]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    try:
        settings = SettingsStore()
        db = Database(settings.directory)
        store = DocumentStore(db)
        retriever = Retriever(db, settings)
        if args.command == 'import-documents':
            source = args.path.expanduser().resolve()
            if not source.exists():
                parser.error('Input path does not exist')
            extensions = {'.pdf', '.docx', '.txt', '.md', '.markdown'}
            files = [source] if source.is_file() else sorted(source.rglob('*') if args.recursive else source.iterdir())
            files = [file for file in files if file.is_file() and file.suffix.lower() in extensions]
            rows = [{'path': str(file)} if args.dry_run else store.add(file.name, file.read_bytes()) for file in files]
            result = {'dry_run': args.dry_run, 'files': rows}
        elif args.command == 'search':
            result = retriever.search(args.query, args.top_k)
        elif args.command == 'build-index':
            result = retriever.build()
        else:
            documents = store.list()
            result = {'documents': len(documents), 'chunks': sum(item['chunk_count'] for item in documents), 'index': retriever.index_status()}
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        parser.exit(1, f'Operation failed: {error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
