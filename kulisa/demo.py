"""End-to-end demonstration of the complete KULISA workflow in a safe test environment.

Runs entirely inside this machine:
  - embedded PostgreSQL (pgserver, throwaway data directory)
  - mock Listmonk API (in-process, no network beyond loopback)
  - test recipients only (example.com / example.org addresses)

Nothing is ever sent to a real mailbox. Run:  python -m kulisa.demo
"""
from __future__ import annotations

import os
import tempfile
import threading
import time

import httpx
import psycopg
import uvicorn

from . import campaigns, importer, monitor, reports, segmentation, suppression
from .config import Settings
from .db import Database
from .importer import revalidate_all
from .listmonk_client import ApprovalError, ListmonkClient

MOCK_PORT = 9100
BRIEF = {
    "pitch": ("KULISA Talent Network connects performing-arts organizations with verified, "
              "tour-ready professional talent - from soloists to full ensembles - with casting "
              "support in 12 languages."),
    "cta": "a short intro call",
}


def start_mock_listmonk() -> ListmonkClient:
    from tests.mock_listmonk import create_mock_app, reset_state

    reset_state()
    app = create_mock_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=MOCK_PORT, log_level="error")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{MOCK_PORT}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    return ListmonkClient(Settings(listmonk_url=f"http://127.0.0.1:{MOCK_PORT}"))


def start_postgres() -> tuple[Database, str]:
    import pgserver

    pgdata = os.path.join(tempfile.gettempdir(), "kulisa_demo_pgdata")
    server = pgserver.get_server(pgdata)
    dsn = server.get_uri()
    db = Database(dsn)
    with psycopg.connect(dsn) as conn:  # reset for repeatable demos
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
    db.init_schema()
    return db, dsn


def banner(step: str) -> None:
    print(f"\n{'=' * 72}\n{step}\n{'=' * 72}")


def run() -> None:
    print("KULISA Email Campaign Manager - SAFE TEST DEMO")
    print("Embedded PostgreSQL + mock Listmonk. Test recipients only. No real email is sent.")

    banner("STEP 0: test environment (embedded PostgreSQL + mock Listmonk API)")
    db, dsn = start_postgres()
    lm = start_mock_listmonk()
    print(f"PostgreSQL: {dsn.split('@')[-1]}")
    print(f"Listmonk API: http://127.0.0.1:{MOCK_PORT} (health: {lm.ping()})")
    settings = Settings(
        database_url=dsn,
        listmonk_url=f"http://127.0.0.1:{MOCK_PORT}",
        test_mode=True,
        sending_enabled=True,   # only relevant because the target is the mock API
        sender_name="KULISA Talent Network",
        sender_email="campaigns@kulisa.example",
    )

    banner("STEP 1: pre-seed suppression list (prior unsubscribe request)")
    suppression.suppress(db, "unsubscribe@example.org", "unsubscribe", source="seed")
    print("Suppressed: unsubscribe@example.org (reason=unsubscribe)")

    banner("STEP 2: import recipients from CSV")
    csv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "sample_recipients.csv"))
    stats = importer.import_recipients(db, csv_path)
    print(f"Import: {stats}")

    banner("STEP 3: re-validate all contacts")
    print(f"Validation: {revalidate_all(db)}")

    banner("STEP 4: segmentation (all eligible performing-arts contacts)")
    seg_id = segmentation.create_segment(db, "Demo: all performing-arts contacts")
    members = segmentation.segment_contacts(db, seg_id)
    for m in members:
        print(f"  - {m['email']} ({m['organization']}, {m['country']}, {m['language']}, status={m['status']})")
    dach_id = segmentation.create_segment(
        db, "Demo: DACH theatres", country="Germany", language="de", org_type="theatre")
    print(f"Narrow segment 'Demo: DACH theatres' (id={dach_id}): "
          f"{len(segmentation.segment_contacts(db, dach_id))} contact(s)")

    banner("STEP 5: generate personalized email draft (Mistral or offline fallback)")
    result = campaigns.create_draft(db, settings, lm, "Demo: performing-arts intro", seg_id, BRIEF)
    print(f"Draft created: {result}")

    banner("STEP 6: approval gate - attempt to start WITHOUT approval (must be blocked)")
    try:
        campaigns.start(db, settings, lm, result["campaign_id"])
        print("ERROR: this should never happen")
    except ApprovalError as exc:
        print(f"BLOCKED as designed: {exc}")

    banner("STEP 6b: approval gate - simulate KULISA_SENDING_ENABLED=false")
    locked = Settings(**{**settings.__dict__, "sending_enabled": False})
    campaigns.approve(db, result["campaign_id"], "KULISA Owner (demo)")
    try:
        campaigns.start(db, locked, lm, result["campaign_id"])
        print("ERROR: this should never happen")
    except ApprovalError as exc:
        print(f"BLOCKED as designed: {exc}")

    banner("STEP 7: start approved campaign against the MOCK Listmonk (test recipients only)")
    campaigns.start(db, settings, lm, result["campaign_id"], actor="KULISA Owner (demo)")
    campaigns.mark_sent(db, result["campaign_id"])
    print("Mock Listmonk simulated delivery to test recipients.")

    banner("STEP 8: monitor delivery, bounces, unsubscribes")
    stats = monitor.sync_campaign_stats(db, lm, result["campaign_id"])
    print(f"Stats: {stats}")
    bounces = monitor.sync_bounces(db, lm, result["campaign_id"])
    print(f"Bounces suppressed: {bounces}")
    unsubs = monitor.sync_unsubscribes(db, lm)
    print(f"Unsubscribes suppressed: {unsubs}")
    monitor.record_reply(db, result["campaign_id"], members[0]["email"],
                         "Re: intro", "Interested - please send more details.")
    print(f"Reply recorded from {members[0]['email']}")

    banner("STEP 9: daily performance report")
    content = reports.build_report(db)
    reports.save_report(db, content)
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports", "demo_report.md"))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(content)

    banner("STEP 10: dashboard stats (also available via `python -m kulisa.cli dashboard`)")
    from .dashboard import compute_stats

    s = compute_stats(db, settings)
    print("Dashboard summary:")
    print(f"  contacts: {s['contacts']}")
    print(f"  campaigns: { {k: v for k, v in s['campaigns'].items() if k != 'list'} }")
    print(f"  safety: {s['safety']}")

    print("\nDEMO COMPLETE - no real email was sent; all recipients were test addresses.")


if __name__ == "__main__":
    run()
