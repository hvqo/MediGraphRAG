"""Versioned, additive SQLite migrations; existing documents and questions are preserved."""
from .storage import now


MIGRATIONS = [
    (1, 'document provenance and versions', '''
      CREATE TABLE IF NOT EXISTS document_meta(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
        metadata TEXT NOT NULL DEFAULT '{}',series_id TEXT NOT NULL,predecessor TEXT,parser TEXT NOT NULL DEFAULT 'native-v1',active INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS chunk_meta(chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        heading TEXT NOT NULL DEFAULT '',bbox TEXT NOT NULL DEFAULT '[]',kind TEXT NOT NULL DEFAULT 'text');
    '''),
    (2, 'reviewed evidence relations', '''
      CREATE TABLE IF NOT EXISTS relations(id TEXT PRIMARY KEY,subject TEXT NOT NULL,predicate TEXT NOT NULL,object TEXT NOT NULL,
        evidence_id TEXT NOT NULL,quote TEXT NOT NULL,conditions TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'pending_review',
        note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS relation_evidence ON relations(evidence_id);
    '''),
    (3, 'teaching blueprints and cases', '''
      CREATE TABLE IF NOT EXISTS blueprints(id TEXT PRIMARY KEY,title TEXT NOT NULL,rows_json TEXT NOT NULL,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,title TEXT NOT NULL,narrative TEXT NOT NULL,citations TEXT NOT NULL,
        status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS question_meta(question_id TEXT PRIMARY KEY,metadata TEXT NOT NULL DEFAULT '{}',review TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE IF NOT EXISTS rejected_candidates(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,content TEXT NOT NULL,
        reason TEXT NOT NULL,created_at TEXT NOT NULL);
    '''),
    (4, 'learning and reproducible evaluations', '''
      CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,learner_id TEXT NOT NULL,question_id TEXT NOT NULL,
        answers TEXT NOT NULL,correct INTEGER NOT NULL,seconds INTEGER NOT NULL,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY,role TEXT NOT NULL,provider TEXT NOT NULL,model TEXT NOT NULL,
        template TEXT NOT NULL,status TEXT NOT NULL,duration REAL NOT NULL,input_tokens INTEGER,output_tokens INTEGER,
        input TEXT NOT NULL,output TEXT,error TEXT,created_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY,name TEXT NOT NULL,samples TEXT NOT NULL,
        created_at TEXT NOT NULL,reviewed INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS evaluation_runs(id TEXT PRIMARY KEY,suite_id TEXT NOT NULL,mode TEXT NOT NULL,
        report TEXT NOT NULL,created_at TEXT NOT NULL);
    '''),
]


def migrate(db):
    with db.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL)')
        for version, name, script in MIGRATIONS:
            if connection.execute('SELECT 1 FROM schema_migrations WHERE version=?', (version,)).fetchone():
                continue
            # Each statement is transactional; no executescript implicit commit.
            for statement in script.split(';'):
                if statement.strip():
                    connection.execute(statement)
            connection.execute('INSERT INTO schema_migrations VALUES (?,?,?)', (version, name, now()))
            connection.execute(f'PRAGMA user_version={version}')
