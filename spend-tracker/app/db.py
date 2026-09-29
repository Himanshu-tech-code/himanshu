import os
import sqlite3
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY,
    institution TEXT NOT NULL,
    access_token_enc TEXT NOT NULL,
    cursor TEXT,
    last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(item_id) ON DELETE CASCADE,
    name TEXT, mask TEXT, type TEXT, subtype TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    name TEXT NOT NULL,
    merchant TEXT,
    amount_cents INTEGER NOT NULL,      -- positive = money out (Plaid convention)
    currency TEXT,
    pending INTEGER NOT NULL DEFAULT 0,
    plaid_primary TEXT,
    plaid_detailed TEXT,
    category TEXT NOT NULL,
    category_source TEXT NOT NULL       -- 'rule' | 'plaid' | 'manual' | 'default'
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,              -- case-insensitive substring of merchant/name
    category TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new = not path.exists()
    conn = sqlite3.connect(path, timeout=30)
    if new:
        os.chmod(path, 0o600)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
