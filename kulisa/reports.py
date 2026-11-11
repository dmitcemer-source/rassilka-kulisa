"""Daily performance reports (markdown), persisted and printable."""
from __future__ import annotations

from datetime import date

from .db import Database


def build_report(db: Database, report_date: date | None = None) -> str:
    report_date = report_date or date.today()
    with db.connect() as conn:
        def one(sql: str, params: tuple = ()) -> int:
            return conn.execute(sql, params).fetchone()["n"]

        total = one("SELECT COUNT(*) AS n FROM contacts")
        valid = one("SELECT COUNT(*) AS n FROM contacts WHERE status='valid'")
        risky = one("SELECT COUNT(*) AS n FROM contacts WHERE status='risky'")
        invalid = one("SELECT COUNT(*) AS n FROM contacts WHERE status='invalid'")
        suppressed = one("SELECT COUNT(*) AS n FROM suppression_list")
        unsubscribed = one("SELECT COUNT(*) AS n FROM suppression_list WHERE reason='unsubscribe'")
        drafts = one("SELECT COUNT(*) AS n FROM campaigns WHERE status IN ('draft','pending_approval')")
        approved = one("SELECT COUNT(*) AS n FROM campaigns WHERE status='approved'")
        sent = one("SELECT COALESCE(SUM(sent),0) AS n FROM campaign_stats")
        bounced = one("SELECT COALESCE(SUM(bounced),0) AS n FROM campaign_stats")
        complained = one("SELECT COALESCE(SUM(complained),0) AS n FROM campaign_stats")
        replies = one("SELECT COUNT(*) AS n FROM replies")
        campaigns = conn.execute(
            "SELECT id, name, status, approved_by, started_at FROM campaigns ORDER BY id"
        ).fetchall()
        recent_actions = conn.execute(
            "SELECT ts, actor, action, details FROM action_log ORDER BY id DESC LIMIT 15"
        ).fetchall()

    lines = [
        f"# KULISA daily campaign report - {report_date.isoformat()}",
        "",
        "## Contacts",
        f"- Total contacts: {total}",
        f"- Valid: {valid} | Risky: {risky} | Invalid: {invalid}",
        f"- Suppressed (never emailed): {suppressed} (of which unsubscribed: {unsubscribed})",
        "",
        "## Campaigns",
        f"- Drafts / awaiting approval: {drafts}",
        f"- Approved (not started): {approved}",
        f"- Emails sent: {sent}",
        f"- Delivery failures (bounces): {bounced}",
        f"- Complaints: {complained}",
        f"- Replies: {replies}",
        "",
        "## Campaign detail",
    ]
    for c in campaigns:
        approver = c["approved_by"] or "-"
        started = c["started_at"].date().isoformat() if c["started_at"] else "not started"
        lines.append(f"- #{c['id']} {c['name']} [{c['status']}] approved by: {approver}, started: {started}")
    lines += ["", "## Recent actions (audit log)"]
    for a in recent_actions:
        lines.append(f"- {a['ts']:%Y-%m-%d %H:%M} {a['actor']}: {a['action']} `{a['details']}`")
    return "\n".join(lines)


def save_report(db: Database, content: str, report_date: date | None = None) -> int:
    report_date = report_date or date.today()
    with db.connect() as conn:
        row = conn.execute(
            """INSERT INTO daily_reports (report_date, content) VALUES (%s, %s)
               ON CONFLICT (report_date) DO UPDATE SET content=EXCLUDED.content RETURNING id""",
            (report_date, content),
        ).fetchone()
        db.log(conn, "agent", "daily_report", {"date": report_date.isoformat()})
    return row["id"]
