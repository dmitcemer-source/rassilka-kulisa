"""In-memory mock of the Listmonk admin API for the offline test environment.

Implements only the endpoints the KULISA agent uses. "Sending" simulates
delivery with a small number of bounces and unsubscribes so the monitoring
and reporting path can be demonstrated end to end.
"""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

STATE = {
    "lists": {},
    "templates": {},
    "subscribers": {},
    "campaigns": {},
    "bounces": [],
    "seq": 0,
}
LOCK = threading.Lock()


def _next_id() -> int:
    with LOCK:
        STATE["seq"] += 1
        return STATE["seq"]


def reset_state() -> None:
    with LOCK:
        for key in ("lists", "templates", "subscribers", "campaigns"):
            STATE[key] = {}
        STATE["bounces"] = []
        STATE["seq"] = 0


def create_mock_app() -> FastAPI:
    app = FastAPI(title="Mock Listmonk")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/lists")
    def lists(request: Request):
        query = request.query_params.get("query", "")
        results = [l for l in STATE["lists"].values() if query.lower() in l["name"].lower()] \
            if query else list(STATE["lists"].values())
        return {"data": {"results": results, "total": len(results)}}

    @app.post("/api/lists")
    async def create_list(request: Request):
        payload = await request.json()
        list_id = _next_id()
        record = {"id": list_id, **payload, "subscriber_count": 0}
        STATE["lists"][list_id] = record
        return {"data": record}

    @app.get("/api/templates")
    def templates():
        return {"data": list(STATE["templates"].values())}

    @app.post("/api/templates")
    async def create_template(request: Request):
        payload = await request.json()
        tpl_id = _next_id()
        record = {"id": tpl_id, **payload}
        STATE["templates"][tpl_id] = record
        return {"data": record}

    @app.get("/api/subscribers")
    def subscribers(request: Request):
        status = request.query_params.get("status")
        query = request.query_params.get("query", "")
        results = list(STATE["subscribers"].values())
        if status:
            results = [s for s in results if s["status"] == status]
        if query:
            email = query.split("=")[-1].strip("'")
            results = [s for s in results if s["email"] == email]
        return {"data": {"results": results, "total": len(results)}}

    @app.post("/api/subscribers")
    async def create_subscriber(request: Request):
        payload = await request.json()
        sub_id = _next_id()
        record = {"id": sub_id, "status": "enabled", **payload}
        STATE["subscribers"][sub_id] = record
        for list_id in payload.get("lists", []):
            if list_id in STATE["lists"]:
                STATE["lists"][list_id]["subscriber_count"] += 1
        return {"data": record}

    @app.post("/api/campaigns")
    async def create_campaign(request: Request):
        payload = await request.json()
        campaign_id = _next_id()
        record = {"id": campaign_id, "status": "draft", "sent": 0, "bounces": 0,
                  "complained": 0, **payload}
        STATE["campaigns"][campaign_id] = record
        return {"data": record}

    @app.get("/api/campaigns/{campaign_id}")
    def get_campaign(campaign_id: int):
        return {"data": STATE["campaigns"][campaign_id]}

    @app.put("/api/campaigns/{campaign_id}")
    async def update_campaign(campaign_id: int, request: Request):
        payload = await request.json()
        STATE["campaigns"][campaign_id].update(payload)
        return {"data": STATE["campaigns"][campaign_id]}

    @app.get("/api/campaigns/{campaign_id}/preview")
    def preview(campaign_id: int):
        c = STATE["campaigns"][campaign_id]
        return PlainTextResponse(f"Subject: {c['subject']}\n\n{c['body']}")

    @app.post("/api/campaigns/{campaign_id}/test")
    async def test_send(campaign_id: int, request: Request):
        payload = await request.json()
        return {"data": {"sent_to": payload.get("subscribers", [])}}

    @app.put("/api/campaigns/{campaign_id}/status")
    async def campaign_status(campaign_id: int, request: Request):
        payload = await request.json()
        c = STATE["campaigns"][campaign_id]
        if payload.get("status") != "running":
            c["status"] = payload["status"]
            return {"data": c}
        if c["status"] == "running":
            return {"data": c}
        c["status"] = "running"
        subs = [s for s in STATE["subscribers"].values()
                if s["status"] == "enabled" and any(l in c["lists"] for l in s.get("lists", []))]
        c["sent"] = len(subs)
        emails = [s["email"] for s in subs]
        if emails:
            STATE["bounces"].append({
                "id": _next_id(), "type": "hard", "campaign_id": campaign_id,
                "subscriber": {"email": emails[0]},
                "error": "550 mailbox unavailable (simulated)",
            })
            c["bounces"] = 1
            last = next((s for s in STATE["subscribers"].values() if s["email"] == emails[-1]), None)
            if last:
                last["status"] = "unsubscribed"
        time.sleep(0.05)
        return {"data": c}

    @app.get("/api/bounces")
    def bounces(request: Request):
        campaign_id = request.query_params.get("campaign_id")
        results = [b for b in STATE["bounces"]
                   if not campaign_id or str(b["campaign_id"]) == campaign_id]
        return {"data": {"results": results, "total": len(results)}}

    return app
