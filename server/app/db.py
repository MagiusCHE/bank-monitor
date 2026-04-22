from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import seed as _seed

_DB_PATH = Path(os.environ.get(
    "BANK_MONITOR_DB",
    str(Path(__file__).resolve().parent.parent / "data" / "bank.db"),
))
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
  id                   INTEGER PRIMARY KEY,
  account_number       TEXT NOT NULL UNIQUE,
  holder_name          TEXT NOT NULL,
  initial_balance      REAL,
  initial_balance_date TEXT,
  created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
  id               INTEGER PRIMARY KEY,
  account_id       INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  op_date          TEXT,
  value_date       TEXT NOT NULL,
  amount           REAL NOT NULL,
  description      TEXT NOT NULL,
  full_description TEXT,
  status           TEXT NOT NULL,
  seq              INTEGER NOT NULL,
  dedup_hash       TEXT NOT NULL UNIQUE,
  created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_account_date   ON transactions(account_id, value_date);
CREATE INDEX IF NOT EXISTS idx_tx_account_status ON transactions(account_id, status);

CREATE TABLE IF NOT EXISTS tag_rules (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  pattern    TEXT NOT NULL,
  tag        TEXT NOT NULL,
  priority   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tag_rules_priority ON tag_rules(priority);

CREATE TABLE IF NOT EXISTS groups (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'any')),
  priority   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_groups_priority ON groups(priority);

CREATE TABLE IF NOT EXISTS group_tags (
  group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  tag      TEXT NOT NULL,
  PRIMARY KEY (group_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_group_tags_tag ON group_tags(tag);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_conn = _connect()


def init_db() -> None:
    with _lock:
        _conn.executescript(SCHEMA)
        # Se il DB è nuovo (nessuna tag_rule), inserisco la seed iniziale.
        has_rules = _conn.execute("SELECT COUNT(*) AS n FROM tag_rules").fetchone()["n"] > 0
        has_groups = _conn.execute("SELECT COUNT(*) AS n FROM groups").fetchone()["n"] > 0
        if not has_rules and not has_groups:
            _seed.apply_seed(_conn)


def reset_to_seed() -> None:
    """Wipe tag_rules + groups + group_tags e re-inserisce la seed iniziale."""
    with _lock, _conn:
        _seed.apply_seed(_conn)


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        try:
            _conn.execute("BEGIN")
            yield _conn
            _conn.execute("COMMIT")
        except Exception:
            _conn.execute("ROLLBACK")
            raise


def conn() -> sqlite3.Connection:
    return _conn
