"""Segmentation by country, language and organization type.

Segments always re-resolve membership from live contact data and never include
suppressed or invalid addresses.
"""
from __future__ import annotations

from .db import Database

BASE_FILTER = "c.status IN ('valid', 'risky') AND NOT EXISTS (SELECT 1 FROM suppression_list s WHERE s.email = c.email)"


def create_segment(db: Database, name: str, country: str | None = None,
                   language: str | None = None, org_type: str | None = None) -> int:
    with db.connect() as conn:
        row = conn.execute(
            """INSERT INTO segments (name, country, language, org_type) VALUES (%s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET country=EXCLUDED.country, language=EXCLUDED.language,
               org_type=EXCLUDED.org_type RETURNING id""",
            (name, country, language, org_type),
        ).fetchone()
        segment_id = row["id"]
        count = refresh_segment(db, segment_id, conn=conn)
        db.log(conn, "agent", "create_segment", {"segment": name, "members": count})
    return segment_id


def refresh_segment(db: Database, segment_id: int, conn=None) -> int:
    def _run(c) -> int:
        seg = c.execute("SELECT * FROM segments WHERE id=%s", (segment_id,)).fetchone()
        if not seg:
            raise ValueError(f"segment {segment_id} not found")
        clauses, params = [BASE_FILTER], []
        for field in ("country", "language", "org_type"):
            if seg[field]:
                clauses.append(f"LOWER(c.{field}) = LOWER(%s)")
                params.append(seg[field])
        sql = f"SELECT c.id FROM contacts c WHERE {' AND '.join(clauses)}"
        ids = [r["id"] for r in c.execute(sql, params).fetchall()]
        c.execute("DELETE FROM segment_members WHERE segment_id=%s", (segment_id,))
        for cid in ids:
            c.execute(
                "INSERT INTO segment_members (segment_id, contact_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (segment_id, cid),
            )
        return len(ids)

    if conn is not None:
        return _run(conn)
    with db.connect() as c:
        return _run(c)


def segment_contacts(db: Database, segment_id: int) -> list[dict]:
    with db.connect() as conn:
        return conn.execute(
            """SELECT c.* FROM contacts c
               JOIN segment_members m ON m.contact_id = c.id
               WHERE m.segment_id = %s ORDER BY c.id""",
            (segment_id,),
        ).fetchall()


def segment_summary(db: Database) -> list[dict]:
    with db.connect() as conn:
        return conn.execute(
            """SELECT s.id, s.name, s.country, s.language, s.org_type,
                      COUNT(m.contact_id) AS members
               FROM segments s LEFT JOIN segment_members m ON m.segment_id = s.id
               GROUP BY s.id ORDER BY s.id"""
        ).fetchall()
