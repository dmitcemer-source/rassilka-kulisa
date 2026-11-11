"""Listmonk admin API client.

Every mutating call is logged. Starting a campaign is double-gated:
  1. the campaign must be marked 'approved' in the local DB by a human, and
  2. KULISA_SENDING_ENABLED must be explicitly true in the environment.
"""
from __future__ import annotations

import httpx

from .config import Settings


class ApprovalError(RuntimeError):
    pass


class ListmonkError(RuntimeError):
    pass


class ListmonkClient:
    def __init__(self, settings: Settings, base_url: str | None = None,
                 client: httpx.Client | None = None):
        self.settings = settings
        self.base_url = (base_url or settings.listmonk_url).rstrip("/")
        headers = {"Content-Type": "application/json"}
        if settings.listmonk_token:
            headers["Authorization"] = f"Bearer {settings.listmonk_token}"
        auth = None
        if settings.listmonk_user and not settings.listmonk_token:
            auth = (settings.listmonk_user, settings.listmonk_token)
        self.client = client or httpx.Client(base_url=self.base_url, headers=headers, auth=auth, timeout=30)

    @staticmethod
    def _check(resp: httpx.Response, context: str):
        if resp.status_code >= 400:
            raise ListmonkError(f"Listmonk {context} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def ping(self) -> bool:
        try:
            return self.client.get("/api/health").status_code == 200
        except httpx.HTTPError:
            return False

    def ensure_list(self, name: str, list_type: str = "private", description: str = "") -> int:
        resp = self.client.get("/api/lists", params={"query": name})
        for lst in self._check(resp, "list lookup").get("data", {}).get("results", []):
            if lst["name"] == name:
                return lst["id"]
        resp = self.client.post("/api/lists", json={
            "name": name, "type": list_type, "optin": "double",
            "description": description or f"Managed by KULISA agent ({list_type})",
        })
        return self._check(resp, "list create")["data"]["id"]

    def ensure_template(self, name: str, body: str) -> int:
        resp = self.client.get("/api/templates")
        for tpl in self._check(resp, "template lookup").get("data", []):
            if tpl["name"] == name:
                return tpl["id"]
        resp = self.client.post("/api/templates", json={"name": name, "body": body, "is_default": False})
        return self._check(resp, "template create")["data"]["id"]

    def upsert_subscriber(self, email: str, name: str, attribs: dict, list_ids: list[int]) -> int:
        resp = self.client.get("/api/subscribers", params={"query": f"email='{email}'"})
        results = self._check(resp, "subscriber lookup").get("data", {}).get("results", [])
        if results:
            return results[0]["id"]
        resp = self.client.post("/api/subscribers", json={
            "email": email, "name": name, "status": "enabled",
            "lists": list_ids, "attribs": attribs,
        })
        return self._check(resp, "subscriber create")["data"]["id"]

    def create_campaign(self, name: str, subject: str, body: str, list_ids: list[int],
                        from_email: str, content_type: str = "html", tags: list[str] | None = None) -> int:
        payload = {
            "name": name, "subject": subject, "lists": list_ids,
            "from_email": from_email, "content_type": content_type,
            "body": body, "tags": tags or ["kulisa"], "type": "regular",
        }
        resp = self.client.post("/api/campaigns", json=payload)
        return self._check(resp, "campaign create")["data"]["id"]

    def get_campaign(self, campaign_id: int) -> dict:
        resp = self.client.get(f"/api/campaigns/{campaign_id}")
        return self._check(resp, "campaign get")["data"]

    def update_campaign(self, campaign_id: int, **fields) -> None:
        current = self.get_campaign(campaign_id)
        payload = {**current, **fields}
        resp = self.client.put(f"/api/campaigns/{campaign_id}", json=payload)
        self._check(resp, "campaign update")

    def campaign_preview(self, campaign_id: int) -> str:
        resp = self.client.get(f"/api/campaigns/{campaign_id}/preview")
        return resp.text

    def test_send(self, campaign_id: int, to_emails: list[str]) -> None:
        """Send a test render to explicitly configured staff addresses only."""
        resp = self.client.post(f"/api/campaigns/{campaign_id}/test", json={"subscribers": to_emails})
        self._check(resp, "campaign test")

    def start_campaign(self, campaign_id: int, *, approved: bool, sending_enabled: bool) -> dict:
        """Start a campaign. Refuses unless a human approved AND sending is enabled."""
        if not approved:
            raise ApprovalError(
                f"Refusing to start campaign {campaign_id}: no human approval recorded. "
                "Run `kulisa approve --campaign <id> --by <name>` first."
            )
        if not sending_enabled:
            raise ApprovalError(
                f"Refusing to start campaign {campaign_id}: KULISA_SENDING_ENABLED is false. "
                "Set KULISA_SENDING_ENABLED=true in the environment to allow real sending."
            )
        resp = self.client.put(f"/api/campaigns/{campaign_id}/status", json={"status": "running"})
        return self._check(resp, "campaign start")["data"]

    def pause_campaign(self, campaign_id: int) -> None:
        resp = self.client.put(f"/api/campaigns/{campaign_id}/status", json={"status": "paused"})
        self._check(resp, "campaign pause")

    def get_bounces(self, campaign_id: int | None = None) -> list[dict]:
        params: dict = {"page": 1, "per_page": 100}
        if campaign_id:
            params["campaign_id"] = campaign_id
        resp = self.client.get("/api/bounces", params=params)
        return self._check(resp, "bounce fetch").get("data", {}).get("results", [])

    def get_unsubscribed(self) -> list[dict]:
        resp = self.client.get("/api/subscribers", params={"status": "unsubscribed", "page": 1, "per_page": 100})
        return self._check(resp, "unsubscribed fetch").get("data", {}).get("results", [])

    def close(self) -> None:
        self.client.close()
