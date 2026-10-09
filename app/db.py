import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def initialize(path):
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    with connect(path) as db:
        if db.execute("PRAGMA user_version").fetchone()[0] > 8:
            raise RuntimeError("Database schema is newer than this application")
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript('''
        CREATE TABLE IF NOT EXISTS staff (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS enquiries (
          id TEXT PRIMARY KEY, reference TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, service TEXT NOT NULL,
          requirements TEXT NOT NULL, organization TEXT NOT NULL, phone TEXT NOT NULL,
          timeline TEXT NOT NULL, site_type TEXT NOT NULL, existing_system TEXT NOT NULL,
          coverage_areas TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
          consent_at TEXT NOT NULL, privacy_version TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS enquiry_created ON enquiries(created_at DESC);
        CREATE TABLE IF NOT EXISTS submission_keys (
          key_hash TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
          enquiry_id TEXT NOT NULL REFERENCES enquiries(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY, enquiry_id TEXT NOT NULL REFERENCES enquiries(id) ON DELETE CASCADE,
          staff_id INTEGER NOT NULL REFERENCES staff(id), text TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (
          enquiry_id TEXT PRIMARY KEY REFERENCES enquiries(id) ON DELETE CASCADE,
          state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt INTEGER NOT NULL DEFAULT 0, lease_at INTEGER NOT NULL DEFAULT 0,
          last_error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY, staff_id INTEGER REFERENCES staff(id), action TEXT NOT NULL,
          target TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rate_limits (
          key TEXT PRIMARY KEY, window INTEGER NOT NULL, count INTEGER NOT NULL, expires INTEGER NOT NULL);

        ''')

        from .crm import SCHEMA
        db.executescript(SCHEMA)
        from .documents import SCHEMA as DOCUMENT_SCHEMA
        db.executescript(DOCUMENT_SCHEMA)
        if 'can_issue_docs' not in {x[1] for x in db.execute('PRAGMA table_info(staff)')}:
            db.execute('ALTER TABLE staff ADD COLUMN can_issue_docs INTEGER NOT NULL DEFAULT 0')
        from .pdf_documents import SCHEMA as PDF_SCHEMA
        db.executescript(PDF_SCHEMA)
        if 'service_context' not in {x[1] for x in db.execute('PRAGMA table_info(enquiries)')}:
            db.execute("ALTER TABLE enquiries ADD COLUMN service_context TEXT NOT NULL DEFAULT ''")
        from .experience import SCHEMA as EXPERIENCE_SCHEMA
        db.executescript(EXPERIENCE_SCHEMA)
        additions={'staff':{'role':"TEXT NOT NULL DEFAULT 'admin'",'mfa_secret':"TEXT NOT NULL DEFAULT ''",'mfa_pending':"TEXT NOT NULL DEFAULT ''",'mfa_last_counter':'INTEGER NOT NULL DEFAULT -1'},'clients':{'reminder_enabled':'INTEGER NOT NULL DEFAULT 0'},'quotes':{'pricing_json':"TEXT NOT NULL DEFAULT ''"},'invoices':{'pricing_json':"TEXT NOT NULL DEFAULT ''"}}
        for table,columns in additions.items():
            existing={x[1] for x in db.execute(f'PRAGMA table_info({table})')}
            for column,definition in columns.items():
                if column not in existing:db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        from .operations import SCHEMA as OPS_SCHEMA
        db.executescript(OPS_SCHEMA)
        from .service_records import SCHEMA as SERVICE_SCHEMA
        db.executescript(SERVICE_SCHEMA)
        from .education import SCHEMA as EDUCATION_SCHEMA
        db.executescript(EDUCATION_SCHEMA)
        db.execute("PRAGMA user_version=8")

def audit(db, staff_id, action, target):
    db.execute("INSERT INTO audit(staff_id,action,target,created_at) VALUES(?,?,?,?)",
               (staff_id, action, target, now()))
