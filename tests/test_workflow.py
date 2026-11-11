"""End-to-end workflow tests. Fully offline: embedded PostgreSQL + mock Listmonk."""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time

import httpx
import pytest
import uvicorn

from kulisa import campaigns, importer, monitor, reports, segmentation, suppression
from kulisa.config import Settings
from kulisa.db import Database
from kulisa.listmonk_client import ApprovalError, ListmonkClient
from kulisa.importer import revalidate_all
from kulisa.validator import validate
from tests.mock_listmonk import create_mock_app, reset_state

BRIEF = {"pitch": "KULISA connects performing-arts organizations with tour-ready talent."}


@pytest.fixture(scope="session")
def db() -> Database:
    import pgserver

    pgdata = tempfile.mkdtemp(prefix="kulisa_test_pg_")
    server = pgserver.get_server(pgdata)
    database = Database(server.get_uri())
    database.init_schema()
    yield database
    server.cleanup()


@pytest.fixture(scope="session")
def lm() -> ListmonkClient:
    reset_state()
    app = create_mock_app()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield ListmonkClient(Settings(listmonk_url=f"http://127.0.0.1:{port}"))
    server.should_exit = True


@pytest.fixture()
def settings(db, lm) -> Settings:
    return Settings(
        database_url=db.dsn,
        listmonk_url=lm.base_url,
        test_mode=True,
        sending_enabled=True,
        sender_name="KULISA Talent Network",
        sender_email="campaigns@kulisa.example",
    )


def test_validator():
    assert validate("Good@Example.COM ").email == "good@example.com"
    assert validate("good@example.com").status == "valid"
    assert validate("bad-email").status == "invalid"
    assert validate("x@mailinator.com").status == "invalid"
    assert validate("info@example.org").status == "risky"


def test_full_workflow(db, lm, settings):
    csv_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample_recipients.csv")

    suppression.suppress(db, "unsubscribe@example.org", "unsubscribe", source="seed")
    stats = importer.import_recipients(db, csv_path)
    assert stats["total"] == 10
    assert stats["valid"] == 7            # test1..test6 + 1 role-based (risky)
    assert stats["invalid"] == 2          # syntax + disposable
    assert stats["duplicate"] == 1        # TEST1@example.com
    assert stats["suppressed"] == 0       # unsubscribe@example.org not in file

    revalidate_all(db)
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM contacts WHERE email='test1@example.com'").fetchone()["n"] == 1
        assert conn.execute("SELECT status FROM contacts WHERE email='info@theatre-example.org'").fetchone()["status"] == "risky"
        assert conn.execute("SELECT COUNT(*) AS n FROM contacts WHERE email='unsubscribe@example.org'").fetchone()["n"] == 0

    seg_id = segmentation.create_segment(db, "DACH theatres", country="Germany",
                                         language="de", org_type="theatre")
    members = segmentation.segment_contacts(db, seg_id)
    emails = {m["email"] for m in members}
    assert emails == {"test1@example.com", "someone@mailinator.com"} or emails == {"test1@example.com"}
    assert "info@theatre-example.org" not in emails   # different country

    result = campaigns.create_draft(db, settings, lm, "Test campaign DACH", seg_id, BRIEF)
    assert result["recipients"] >= 1
    assert result["subject"]

    with db.connect() as conn:
        assert conn.execute("SELECT status FROM campaigns WHERE id=%s",
                            (result["campaign_id"],)).fetchone()["status"] == "pending_approval"

    with pytest.raises(ApprovalError):
        campaigns.start(db, settings, lm, result["campaign_id"])

    locked = Settings(**{**settings.__dict__, "sending_enabled": False})
    campaigns.approve(db, result["campaign_id"], "Owner")
    with pytest.raises(ApprovalError):
        campaigns.start(db, locked, lm, result["campaign_id"])

    campaigns.start(db, settings, lm, result["campaign_id"], actor="Owner")
    campaigns.mark_sent(db, result["campaign_id"])

    stats = monitor.sync_campaign_stats(db, lm, result["campaign_id"])
    assert stats["sent"] >= 1
    assert stats["bounced"] == 1

    bounces = monitor.sync_bounces(db, lm, result["campaign_id"])
    assert len(bounces) == 1
    assert suppression.is_suppressed(db, bounces[0]["email"])

    unsubs = monitor.sync_unsubscribes(db, lm)
    assert len(unsubs) == 1
    assert suppression.is_suppressed(db, unsubs[0])

    monitor.record_reply(db, result["campaign_id"], "test1@example.com", "Re: hi", "Interested.")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM replies").fetchone()["n"] == 1

    content = reports.build_report(db)
    assert "KULISA daily campaign report" in content
    assert "Emails sent" in content
    reports.save_report(db, content)

    from kulisa.dashboard import compute_stats

    s = compute_stats(db, settings)
    assert s["contacts"]["total"] >= 6
    assert s["campaigns"]["sent"] >= 1
    assert s["safety"]["sending_enabled"] is True
