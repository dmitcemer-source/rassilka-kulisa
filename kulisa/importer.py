"""CSV / Excel recipient import with validation, dedupe and suppression enforcement."""
from __future__ import annotations

import csv
from pathlib import Path

from .db import Database, utcnow
from .validator import infer_language, infer_org_type, normalize, validate

COLUMN_ALIASES = {
    "email": {"email", "e-mail", "email address", "mail", "address"},
    "first_name": {"first name", "firstname", "given name", "vorname"},
    "last_name": {"last name", "lastname", "surname", "family name", "nachname"},
    "organization": {"organization", "organisation", "company", "org", "theatre", "theater", "employer"},
    "org_type": {"org type", "organization type", "organisation type", "type", "category"},
    "country": {"country", "land", "pays"},
    "language": {"language", "lang", "sprache"},
}


def _read_rows(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
        return [dict(zip(headers, r)) for r in rows[1:] if any(v is not None for v in r)]
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader]


def _pick(row: dict, field: str):
    for alias in COLUMN_ALIASES[field]:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    return None


def import_recipients(db: Database, path: str, source: str = "upload") -> dict:
    """Import a recipient file. Never inserts suppressed or invalid addresses."""
    p = Path(path)
    rows = _read_rows(p)
    stats = {"total": len(rows), "valid": 0, "invalid": 0, "duplicate": 0, "suppressed": 0}

    with db.connect() as conn:
        batch_id = conn.execute(
            "INSERT INTO import_batches (filename, total_rows) VALUES (%s, %s) RETURNING id",
            (p.name, len(rows)),
        ).fetchone()["id"]

        for row in rows:
            raw_email = _pick(row, "email")
            result = validate(str(raw_email or ""))
            email = result.email
            if result.status == "invalid":
                stats["invalid"] += 1
                if email:
                    conn.execute(
                        "INSERT INTO suppression_list (email, reason, source) VALUES (%s, 'invalid', %s) "
                        "ON CONFLICT (email) DO NOTHING",
                        (email, p.name),
                    )
                continue

            hit = conn.execute(
                "SELECT id, reason FROM suppression_list WHERE email = %s", (email,)
            ).fetchone()
            if hit:
                stats["suppressed"] += 1
                continue

            existing = conn.execute(
                "SELECT id FROM contacts WHERE email = %s", (email,)
            ).fetchone()
            if existing:
                stats["duplicate"] += 1
                continue

            country = (_pick(row, "country") or "").strip() or None
            language = (_pick(row, "language") or "").strip() or infer_language(country)
            conn.execute(
                """INSERT INTO contacts
                   (email, first_name, last_name, organization, org_type, country, language,
                    status, status_reason, source)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    email,
                    _pick(row, "first_name"),
                    _pick(row, "last_name"),
                    _pick(row, "organization"),
                    infer_org_type(_pick(row, "org_type")),
                    country,
                    language.lower()[:2],
                    result.status,
                    result.reason,
                    source,
                ),
            )
            stats["valid"] += 1

        conn.execute(
            """UPDATE import_batches SET valid_count=%s, invalid_count=%s,
               duplicate_count=%s, suppressed_count=%s WHERE id=%s""",
            (stats["valid"], stats["invalid"], stats["duplicate"], stats["suppressed"], batch_id),
        )
        db.log(conn, "agent", "import_recipients", {"file": p.name, **stats})
    return {"batch_id": batch_id, **stats}


def revalidate_all(db: Database) -> dict:
    """Re-run validation over stored contacts; demote any that became invalid."""
    counts = {"valid": 0, "invalid": 0, "risky": 0}
    with db.connect() as conn:
        for contact in conn.execute("SELECT id, email FROM contacts").fetchall():
            result = validate(contact["email"])
            counts[result.status] = counts.get(result.status, 0) + 1
            conn.execute(
                "UPDATE contacts SET status=%s, status_reason=%s, updated_at=%s WHERE id=%s",
                (result.status, result.reason, utcnow(), contact["id"]),
            )
            if result.status == "invalid":
                conn.execute(
                    "INSERT INTO suppression_list (email, reason, source) VALUES (%s, 'invalid', 'revalidation') "
                    "ON CONFLICT (email) DO NOTHING",
                    (contact["email"],),
                )
        db.log(conn, "agent", "revalidate_all", counts)
    return counts
