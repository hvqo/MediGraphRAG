from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "knowledge.sqlite3"
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    kind TEXT NOT NULL, created_at TEXT NOT NULL, pages INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL, warnings TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, page INTEGER, location TEXT NOT NULL,
                    start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, text TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
            """)
        from .migrations import migrate

        migrate(self)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def rows(self, sql, parameters=()):
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, parameters)]

    def chunks(self):
        rows = self.rows("""SELECT c.*,d.title,d.filename,coalesce(cm.heading,'') AS heading,
                            coalesce(dm.metadata,'{}') AS source_metadata,coalesce(dm.parser,'native-v1') AS parser,
                            coalesce(cm.bbox,'[]') AS bbox,coalesce(cm.kind,'text') AS kind
                            FROM chunks c JOIN documents d ON d.id=c.document_id
                            LEFT JOIN document_meta dm ON dm.document_id=d.id
                            LEFT JOIN chunk_meta cm ON cm.chunk_id=c.id
                            WHERE coalesce(dm.active,1)=1 ORDER BY c.document_id,c.ordinal""")
        return [{**r, "source_metadata": json.loads(r["source_metadata"]), "bbox": json.loads(r["bbox"])} for r in rows]
