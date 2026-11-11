"""KULISA agent command line interface.

Usage examples:
  python -m kulisa.cli init-db
  python -m kulisa.cli import recipients.csv
  python -m kulisa.cli validate
  python -m kulisa.cli segment --name "DE theatres" --country Germany --org-type theatre
  python -m kulisa.cli draft --campaign "Spring 2025 intro" --segment 1 --pitch "..."
  python -m kulisa.cli approve --campaign 1 --by "Owner"
  python -m kulisa.cli start --campaign 1
  python -m kulisa.cli monitor --campaign 1
  python -m kulisa.cli report
  python -m kulisa.cli dashboard [--port 8080]
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx

from . import campaigns, importer, monitor, reports, segmentation
from .config import load_settings
from .dashboard import app
from .db import Database
from .importer import revalidate_all
from .listmonk_client import ApprovalError, ListmonkClient, ListmonkError


def get_db() -> Database:
    return Database(load_settings().database_url)


def get_lm() -> ListmonkClient:
    return ListmonkClient(load_settings())


def cmd_init_db(args):
    get_db().init_schema()
    print("Database schema initialized.")


def cmd_import(args):
    stats = importer.import_recipients(get_db(), args.file, source=args.source)
    print(json.dumps(stats, indent=2))


def cmd_validate(args):
    print(json.dumps(revalidate_all(get_db()), indent=2))


def cmd_segment(args):
    db = get_db()
    seg_id = segmentation.create_segment(
        db, args.name, country=args.country, language=args.language, org_type=args.org_type
    )
    members = segmentation.segment_contacts(db, seg_id)
    print(f"Segment '{args.name}' (id={seg_id}) -> {len(members)} eligible contacts")


def cmd_draft(args):
    db, settings, lm = get_db(), load_settings(), get_lm()
    brief = {"pitch": args.pitch, "sender_name": settings.sender_name,
             "sender_email": settings.sender_email, "cta": args.cta}
    result = campaigns.create_draft(db, settings, lm, args.campaign, args.segment, brief,
                                    personalize=not args.no_personalize, limit=args.limit)
    print(json.dumps(result, indent=2))
    print("Status: pending_approval. Nothing will be sent until `approve` + `start`.")


def cmd_approve(args):
    campaigns.approve(get_db(), args.campaign, args.by)
    print(f"Campaign {args.campaign} approved by {args.by} (recorded in audit log).")


def cmd_start(args):
    db, settings, lm = get_db(), load_settings(), get_lm()
    result = campaigns.start(db, settings, lm, args.campaign, actor=args.by)
    print(f"Campaign {result['campaign_id']} started via Listmonk (status: sending).")


def cmd_status(args):
    with get_db().connect() as conn:
        rows = conn.execute(
            "SELECT id, name, status, approved_by, started_at::date AS started FROM campaigns ORDER BY id"
        ).fetchall()
    for r in rows:
        print(f"#{r['id']:<3} {r['name']:<40} {r['status']:<18} by={r['approved_by'] or '-':<12} {r['started'] or ''}")


def cmd_monitor(args):
    db, lm = get_db(), get_lm()
    stats = monitor.sync_campaign_stats(db, lm, args.campaign)
    bounces = monitor.sync_bounces(db, lm, args.campaign)
    unsubs = monitor.sync_unsubscribes(db, lm)
    print(json.dumps({"stats": stats, "bounces": bounces, "new_unsubscribes": unsubs}, indent=2))


def cmd_report(args):
    db = get_db()
    content = reports.build_report(db)
    reports.save_report(db, content)
    print(content)


def cmd_dashboard(args):
    print(f"Dashboard on http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kulisa", description="KULISA email campaign agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db").set_defaults(func=cmd_init_db)
    p = sub.add_parser("import"); p.add_argument("file"); p.add_argument("--source", default="upload"); p.set_defaults(func=cmd_import)
    sub.add_parser("validate").set_defaults(func=cmd_validate)
    p = sub.add_parser("segment")
    p.add_argument("--name", required=True); p.add_argument("--country"); p.add_argument("--language"); p.add_argument("--org-type", dest="org_type")
    p.set_defaults(func=cmd_segment)
    p = sub.add_parser("draft")
    p.add_argument("--campaign", required=True); p.add_argument("--segment", type=int, required=True)
    p.add_argument("--pitch", required=True); p.add_argument("--cta", default="a short intro call")
    p.add_argument("--limit", type=int); p.add_argument("--no-personalize", action="store_true")
    p.set_defaults(func=cmd_draft)
    p = sub.add_parser("approve"); p.add_argument("--campaign", type=int, required=True); p.add_argument("--by", required=True); p.set_defaults(func=cmd_approve)
    p = sub.add_parser("start"); p.add_argument("--campaign", type=int, required=True); p.add_argument("--by", default="owner"); p.set_defaults(func=cmd_start)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p = sub.add_parser("monitor"); p.add_argument("--campaign", type=int, required=True); p.set_defaults(func=cmd_monitor)
    sub.add_parser("report").set_defaults(func=cmd_report)
    p = sub.add_parser("dashboard"); p.add_argument("--port", type=int, default=8080); p.set_defaults(func=cmd_dashboard)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ApprovalError, ListmonkError, ValueError, httpx.HTTPError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
