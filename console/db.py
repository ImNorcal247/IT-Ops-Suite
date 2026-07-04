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
