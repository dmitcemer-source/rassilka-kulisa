"""Suppression list: the hard stop that overrides every other decision."""
from __future__ import annotations

from .db import Database


def suppress(db: Database, email: str, reason: str, source: str = "manual") -> None:
    email = email.strip().lower()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO suppression_list (email, reason, source) VALUES (%s, %s, %s) "
            "ON CONFLICT (email) DO UPDATE SET reason = EXCLUDED.reason, source = EXCLUDED.source",
            (email, reason, source),
        )
        db.log(conn, "agent", "suppress", {"email": email, "reason": reason, "source": source})


def is_suppressed(db: Database, email: str) -> bool:
    with db.connect() as conn:
        return conn.execute(
            "SELECT 1 FROM suppression_list WHERE email = %s", (email.strip().lower(),)
        ).fetchone() is not None


def list_suppressed(db: Database, reason: str | None = None) -> list[dict]:
    with db.connect() as conn:
        if reason:
            return conn.execute(
                "SELECT email, reason, source, created_at FROM suppression_list WHERE reason=%s ORDER BY created_at DESC",
                (reason,),
            ).fetchall()
        return conn.execute(
            "SELECT email, reason, source, created_at FROM suppression_list ORDER BY created_at DESC"
        ).fetchall()


def filter_suppressed(db: Database, emails: list[str]) -> tuple[list[str], list[str]]:
    """Split emails into (allowed, blocked)."""
    allowed, blocked = [], []
    with db.connect() as conn:
        for email in emails:
            hit = conn.execute(
                "SELECT reason FROM suppression_list WHERE email = %s", (email.strip().lower(),)
            ).fetchone()
            (blocked if hit else allowed).append(email)
    return allowed, blocked
