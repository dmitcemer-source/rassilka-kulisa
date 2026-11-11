"""Campaign lifecycle: draft -> pending_approval -> approved -> sending -> sent.

The approval step is the only path to 'approved' and always requires an
explicit human actor name; it is recorded with a timestamp in the audit log.
"""
from __future__ import annotations

from .db import Database, utcnow
from .generator import EmailGenerator
from .listmonk_client import ApprovalError, ListmonkClient
from .segmentation import segment_contacts

DEFAULT_TEMPLATE = """<h2>{{ .Campaign.Subject }}</h2>
{{ .Campaign.Content }}
<p style="color:#888;font-size:12px">You are receiving this professional B2B message from KULISA Talent Network.
<a href="{{ UnsubscribeURL }}">Unsubscribe</a> at any time.</p>"""


def _fallback_content(contact: dict, brief: dict) -> dict:
    from .generator import _fallback

    return _fallback(contact, brief)


def create_draft(db: Database, settings, lm: ListmonkClient, name: str, segment_id: int,
                 brief: dict, personalize: bool = True, limit: int | None = None) -> dict:
    """Build a campaign draft: generate content, mirror it into Listmonk as a draft."""
    with db.connect() as conn:
        seg = conn.execute("SELECT * FROM segments WHERE id=%s", (segment_id,)).fetchone()
        if not seg:
            raise ValueError(f"segment {segment_id} not found")
        if conn.execute("SELECT 1 FROM campaigns WHERE name=%s", (name,)).fetchone():
            raise ValueError(f"campaign '{name}' already exists")

        contacts = segment_contacts(db, segment_id)
        if limit:
            contacts = contacts[:limit]
        if not contacts:
            raise ValueError("segment has no eligible contacts")

        generator = EmailGenerator(settings)
        if personalize:
            sample = generator.generate_batch(contacts, brief, limit=1)[0]
            subject, body = sample["subject"], sample["body"]
        else:
            sample = _fallback_content(contacts[0], brief)
            subject, body = sample["subject"], sample["body"]

        campaign_id = conn.execute(
            """INSERT INTO campaigns (name, subject, body, language, segment_id, status, test_mode)
               VALUES (%s, %s, %s, %s, %s, 'draft', %s) RETURNING id""",
            (name, subject, body, seg["language"] or "en", segment_id, settings.test_mode),
        ).fetchone()["id"]

        list_name = f"KULISA: {seg['name']}"
        list_id = lm.ensure_list(list_name)
        template_id = lm.ensure_template("KULISA base template", DEFAULT_TEMPLATE)
        for contact in contacts:
            attribs = {
                "first_name": contact["first_name"] or "",
                "last_name": contact["last_name"] or "",
                "organization": contact["organization"] or "",
                "country": contact["country"] or "",
                "language": contact["language"] or "en",
            }
            sub_id = lm.upsert_subscriber(
                contact["email"],
                " ".join(filter(None, [contact["first_name"], contact["last_name"]]))
                or contact["organization"] or contact["email"],
                attribs, [list_id],
            )
            conn.execute(
                "UPDATE contacts SET listmonk_subscriber_id=%s, updated_at=%s WHERE id=%s",
                (sub_id, utcnow(), contact["id"]),
            )

        from_email = f"{settings.sender_name} <{settings.sender_email}>"
        listmonk_campaign_id = lm.create_campaign(
            name=name, subject=subject, body=body, list_ids=[list_id],
            from_email=from_email, content_type="markdown",
            tags=["kulisa", f"segment-{segment_id}"],
        )
        lm.update_campaign(listmonk_campaign_id, template_id=template_id)

        conn.execute(
            """UPDATE campaigns SET listmonk_campaign_id=%s, listmonk_list_id=%s,
               status='pending_approval', updated_at=%s WHERE id=%s""",
            (listmonk_campaign_id, list_id, utcnow(), campaign_id),
        )
        db.log(conn, "agent", "create_draft", {
            "campaign_id": campaign_id, "name": name, "segment": seg["name"],
            "recipients": len(contacts), "listmonk_campaign_id": listmonk_campaign_id,
        })
    return {"campaign_id": campaign_id, "listmonk_campaign_id": listmonk_campaign_id,
            "recipients": len(contacts), "subject": subject}


def approve(db: Database, campaign_id: int, approved_by: str) -> None:
    if not approved_by or not approved_by.strip():
        raise ValueError("approval requires the name of the approving human (--by)")
    approved_by = approved_by.strip()
    with db.connect() as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=%s", (campaign_id,)).fetchone()
        if not campaign:
            raise ValueError(f"campaign {campaign_id} not found")
        if campaign["status"] not in ("draft", "pending_approval"):
            raise ValueError(f"campaign {campaign_id} is '{campaign['status']}', cannot approve")
        conn.execute(
            "UPDATE campaigns SET status='approved', approved_by=%s, approved_at=%s, updated_at=%s WHERE id=%s",
            (approved_by, utcnow(), utcnow(), campaign_id),
        )
        db.log(conn, approved_by, "approve_campaign", {"campaign_id": campaign_id})


def start(db: Database, settings, lm: ListmonkClient, campaign_id: int, actor: str = "owner") -> dict:
    """Start an approved campaign through Listmonk. Hard-fails without approval."""
    with db.connect() as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=%s", (campaign_id,)).fetchone()
        if not campaign:
            raise ValueError(f"campaign {campaign_id} not found")
        if campaign["status"] != "approved":
            raise ApprovalError(
                f"Campaign {campaign_id} status is '{campaign['status']}'. "
                "It must be approved by a human before it can start."
            )
        if campaign["listmonk_campaign_id"] is None:
            raise ValueError(f"campaign {campaign_id} has no Listmonk mirror")

        lm.start_campaign(
            campaign["listmonk_campaign_id"],
            approved=True,
            sending_enabled=settings.sending_enabled,
        )
        conn.execute(
            "UPDATE campaigns SET status='sending', started_at=%s, updated_at=%s WHERE id=%s",
            (utcnow(), utcnow(), campaign_id),
        )
        db.log(conn, actor, "start_campaign", {
            "campaign_id": campaign_id,
            "listmonk_campaign_id": campaign["listmonk_campaign_id"],
            "test_mode": campaign["test_mode"],
        })
    return {"campaign_id": campaign_id, "status": "sending"}


def mark_sent(db: Database, campaign_id: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE campaigns SET status='sent', updated_at=%s WHERE id=%s", (utcnow(), campaign_id)
        )
        db.log(conn, "agent", "campaign_sent", {"campaign_id": campaign_id})
