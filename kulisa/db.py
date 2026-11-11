"""Database access layer: connections, schema bootstrap, action logging."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, dsn: str):
        if not dsn:
            raise RuntimeError("KULISA_DATABASE_URL is not set (see .env.example)")
        self.dsn = dsn

    @contextmanager
    def connect(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn:
            with conn.transaction():
                yield conn

    def init_schema(self) -> None:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            sql = fh.read()
        with psycopg.connect(self.dsn) as conn:
            conn.execute(sql)
            conn.commit()

    def log(self, conn, actor: str, action: str, details: dict | None = None) -> None:
        conn.execute(
            "INSERT INTO action_log (actor, action, details) VALUES (%s, %s, %s)",
            (actor, action, json.dumps(details or {}, default=str)),
        )


def log_action(db: Database, actor: str, action: str, details: dict | None = None) -> None:
    """Convenience wrapper: log in its own transaction."""
    with db.connect() as conn:
        db.log(conn, actor, action, details)
