# KULISA Email Campaign Manager Agent

Autonomous AI agent for managing permission-based B2B email campaigns for **KULISA Talent Network**, targeting theatres, theatre companies, producers and performing-arts organizations worldwide.

- **AI model:** Mistral (`mistral-large-latest` via `MISTRAL_API_KEY`)
- **Mailing platform:** Listmonk (admin API)
- **Database:** PostgreSQL
- **Hosting:** your own VPS (the existing Beget environment is **not** used or modified)
- **SMTP:** configured inside Listmonk with your external professional delivery provider

> **Safety first: sending is disabled until the owner explicitly approves a campaign, and it stays disabled unless `KULISA_SENDING_ENABLED=true` is set in the environment.** Both gates must pass; there is no code path that bypasses them.

## Quick start (safe test environment, no real email)

```bash
pip install -r requirements.txt
python -m kulisa.demo
```

This runs the complete workflow fully offline: embedded PostgreSQL + a mock Listmonk API + `example.com` test recipients only. It demonstrates import, validation, dedupe, suppression, segmentation, draft generation, the approval gate (including the blocked attempts), sending to the mock, monitoring, and the daily report. The report is also written to `reports/demo_report.md`.

## Production-style test stack on the VPS

```bash
cp .env.example .env          # fill in real values; keep KULISA_SENDING_ENABLED=false
POSTGRES_PASSWORD=... docker compose up -d    # PostgreSQL + Listmonk
python -m kulisa.cli init-db
```

Configure Listmonk's SMTP settings in its admin UI (your external delivery provider). Then:

```bash
python -m kulisa.cli import recipients.csv
python -m kulisa.cli validate
python -m kulisa.cli segment --name "DACH theatres" --country Germany --language de --org-type theatre
python -m kulisa.cli draft --campaign "Spring intro" --segment 1 --pitch "..."
python -m kulisa.cli approve --campaign 1 --by "Owner"     # explicit human approval
KULISA_SENDING_ENABLED=true python -m kulisa.cli start --campaign 1
python -m kulisa.cli monitor --campaign 1
python -m kulisa.cli report
python -m kulisa.cli dashboard --port 8080
```

## Commands

| Command | Purpose |
|---|---|
| `init-db` | Create the PostgreSQL schema |
| `import FILE` | Import CSV/XLSX contacts (validates, dedupes, enforces suppression) |
| `validate` | Re-validate all stored contacts |
| `segment --name ... [--country --language --org-type]` | Create/refresh a segment |
| `draft --campaign --segment --pitch` | Generate content (Mistral) and mirror a draft into Listmonk |
| `approve --campaign --by NAME` | Record explicit human approval (audit-logged) |
| `start --campaign` | Start via Listmonk; **refuses without approval + sending flag** |
| `status` | List campaigns and their lifecycle status |
| `monitor --campaign` | Sync stats, bounces (-> suppression), unsubscribes (-> suppression) |
| `report` | Build and store the daily performance report |
| `dashboard [--port]` | Web dashboard on `127.0.0.1` |

## Dashboard

`http://127.0.0.1:8080/` shows total contacts, valid/invalid emails, drafts, approved campaigns, sent emails, delivery failures, replies, unsubscribes, complaints, and whether sending is currently locked. The interface is bilingual — **Russian and English** with a RU/EN toggle (choice is remembered in the browser). JSON API at `/api/stats`.

## Tests

```bash
python -m pytest tests/ -q
```

Covers validation, import/dedupe/suppression, segmentation, draft creation, both approval-gate refusals, mock sending, bounce/unsubscribe suppression, replies, reports and dashboard stats.

## Project layout

```
kulisa/
  config.py            env-based settings (secrets never in code)
  db.py                PostgreSQL access + audit log
  importer.py          CSV/XLSX import, validation, dedupe, suppression
  validator.py         syntax / disposable / role-based checks, language inference
  suppression.py       suppression list (hard stop)
  segmentation.py      country / language / org-type segments
  generator.py         Mistral-powered personalized copy (EN + language adaptation)
  campaigns.py         lifecycle: draft -> pending_approval -> approved -> sending -> sent
  listmonk_client.py   Listmonk admin API client with the sending gate
  monitor.py           stats, bounces, unsubscribes, replies (optional IMAP)
  reports.py           daily markdown reports
  dashboard.py         FastAPI dashboard
  cli.py               operator CLI
  demo.py              full offline workflow demonstration
schema.sql             PostgreSQL schema
tests/                 pytest suite + mock Listmonk API
docs/                  architecture & safety notes
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/SAFETY.md](docs/SAFETY.md).
