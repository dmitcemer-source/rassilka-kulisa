"""Delivery monitoring: stats, bounces, complaints, replies, unsubscribe sync."""
from __future__ import annotations

from .db import Database
from .suppression import suppress


def sync_campaign_stats(db: Database, lm, campaign_id: int) -> dict:
    """Pull live stats for a campaign (by our internal campaign id)."""
    with db.connect() as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=%s", (campaign_id,)).fetchone()
        if not campaign or campaign["listmonk_campaign_id"] is None:
            raise ValueError(f"campaign {campaign_id} not found or not mirrored to Listmonk")
        data = lm.get_campaign(campaign["listmonk_campaign_id"])
        stats = {
            "sent": data.get("sent", 0) or 0,
            "delivered": (data.get("sent", 0) or 0) - (data.get("bounces", 0) or 0),
            "bounced": data.get("bounces", 0) or 0,
            "complained": data.get("complained", 0) or 0,
        }
        conn.execute(
            """INSERT INTO campaign_stats (campaign_id, sent, delivered, bounced, complained)
               VALUES (%s, %s, %s, %s, %s)""",
            (campaign_id, stats["sent"], stats["delivered"], stats["bounced"], stats["complained"]),
        )
        db.log(conn, "agent", "sync_stats", {"campaign_id": campaign_id, **stats})
    return stats


def sync_bounces(db: Database, lm, campaign_id: int) -> list[dict]:
    """Record bounces and suppress hard-bounced addresses permanently."""
    with db.connect() as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=%s", (campaign_id,)).fetchone()
        if not campaign or campaign["listmonk_campaign_id"] is None:
            raise ValueError(f"campaign {campaign_id} not found or not mirrored")
    recorded = []
    for bounce in lm.get_bounces(campaign["listmonk_campaign_id"]):
        email = (bounce.get("subscriber") or {}).get("email") or bounce.get("email") or ""
        btype = bounce.get("type", "hard")
        if email:
            suppress(db, email, f"bounce:{btype}", source="listmonk")
            recorded.append({"email": email, "type": btype})
    return recorded


def sync_unsubscribes(db: Database, lm) -> list[str]:
    """Mirror Listmonk unsubscribes into our suppression list. Never bypassed."""
    synced = []
    for sub in lm.get_unsubscribed():
        email = sub.get("email", "")
        if email:
            suppress(db, email, "unsubscribe", source="listmonk")
            synced.append(email)
    return synced


def record_reply(db: Database, campaign_id: int, from_email: str, subject: str, body: str) -> int:
    with db.connect() as conn:
        contact = conn.execute("SELECT id FROM contacts WHERE email=%s", (from_email.lower(),)).fetchone()
        row = conn.execute(
            """INSERT INTO replies (campaign_id, contact_id, from_email, subject, body_excerpt)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (campaign_id, contact["id"] if contact else None, from_email.lower(),
             subject, body[:1000]),
        ).fetchone()
        db.log(conn, "agent", "record_reply", {"campaign_id": campaign_id, "from": from_email})
    return row["id"]


def check_reply_mailbox(db: Database, campaign_id: int) -> int:
    """Optional IMAP reply polling (stdlib only). Disabled unless IMAP env vars are set."""
    import email as email_lib
    import imaplib
    from email.header import decode_header

    from .config import load_settings

    s = load_settings()
    if not (s.imap_host and s.imap_user and s.imap_password):
        return 0
    count = 0
    imap = imaplib.IMAP4_SSL(s.imap_host)
    try:
        imap.login(s.imap_user, s.imap_password)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject = "".join(
                part.decode(c or "utf-8", errors="replace") if isinstance(part, bytes) else part
                for part, c in decode_header(msg.get("Subject", ""))
            )
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="replace")
            record_reply(db, campaign_id, msg.get("From", ""), subject, body)
            count += 1
    finally:
        imap.logout()
    return count
