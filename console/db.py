"""
console/db.py

SQLite connection helper for the FastAPI console. Shares the same
it_tickets.db file the Streamlit app and setup_sample_data.py use, and adds
a `users` table for the console's real login (the original Streamlit app
has no auth at all, so this table is new).
"""

import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).parent.parent / "it_tickets.db"

USERS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'IT Operations',
    created_at TEXT NOT NULL
)
"""

# Dashboard data-source connections (ServiceNow/ClickUp/Zendesk/uploads that
# feed the tickets table). Deliberately persisted here rather than kept
# session-only like the Orchestrator's SinkConfig — you'd otherwise have to
# re-paste credentials every time you want to pull fresh data.
IMPORT_SOURCES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS import_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    instance TEXT NOT NULL DEFAULT '',
    username TEXT NOT NULL DEFAULT '',
    token TEXT NOT NULL DEFAULT '',
    list_or_view_id TEXT NOT NULL DEFAULT '',
    sync_interval_minutes INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT,
    last_sync_count INTEGER,
    created_at TEXT NOT NULL
)
"""

# Lets a sync re-run safely: re-importing the same external ticket updates
# the existing row (status/priority/resolution changes reflected) instead of
# inserting a duplicate.
TICKETS_UNIQUE_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_sys_id_entity
ON tickets(sys_id, source_entity)
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_users_table():
    conn = get_connection()
    try:
        conn.execute(USERS_TABLE_DDL)
        conn.commit()
    finally:
        conn.close()


def ensure_import_sources_table():
    conn = get_connection()
    try:
        conn.execute(IMPORT_SOURCES_TABLE_DDL)
        # Table may already exist from before sync_interval_minutes was
        # added — CREATE TABLE IF NOT EXISTS won't backfill a new column on
        # an existing table, so check for it explicitly.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(import_sources)")}
        if "sync_interval_minutes" not in columns:
            conn.execute("ALTER TABLE import_sources ADD COLUMN sync_interval_minutes INTEGER NOT NULL DEFAULT 0")
        # The tickets table only exists once setup_sample_data.py has run;
        # skip the index silently if it's not there yet rather than crashing
        # server startup.
        has_tickets_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'"
        ).fetchone()
        if has_tickets_table:
            conn.execute(TICKETS_UNIQUE_INDEX_DDL)
        conn.commit()
    finally:
        conn.close()
