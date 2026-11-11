# Architecture

## Overview

```
                 ┌───────────────────────────────────────────────┐
                 │                KULISA agent (VPS)             │
                 │                                               │
  CSV/XLSX ───▶  │  importer ─▶ validator ─▶ PostgreSQL ◀─ segm. │
                 │                    │            ▲             │
                 │              suppression_list    │             │
                 │                    │        segmenter          │
                 │                    ▼            │             │
                 │              generator (Mistral API)          │
                 │                    │                          │
                 │              campaigns (lifecycle + approval) │
                 │                    │                          │
                 │              listmonk_client ────┐            │
                 │                    │            │            │
                 │              monitor ─▶ reports  │            │
                 │                    │            │            │
                 │              dashboard (FastAPI) │            │
                 └────────────────────┼────────────┼────────────┘
                                      ▼            ▼
                             Listmonk (API)   PostgreSQL
                                      │
                                      ▼
                          external SMTP delivery provider
```

## Components

### 1. Import & validation (`importer.py`, `validator.py`)
- Reads CSV and Excel (openpyxl), tolerant column aliases (`Email`, `E-mail`, `email address`, ...).
- Normalizes addresses, checks syntax, disposable domains, role-based prefixes (flagged `risky`, not dropped).
- Optional MX verification (`KULISA_CHECK_MX=1`, requires `dnspython`).
- Invalid addresses never enter `contacts`; they are recorded as suppressed with reason `invalid`.
- Exact duplicates (case-insensitive) are skipped and counted per import batch.
- Language inferred from country when not supplied (`COUNTRY_LANGUAGE` map).

### 2. Suppression (`suppression.py`)
Single hard-stop table consulted by import, segmentation, and campaign audience building. Fed by: manual entries, prior unsubscribes, Listmonk unsubscribe sync, hard bounces, complaints. Nothing ever overrides it.

### 3. Segmentation (`segmentation.py`)
Segments are stored rules (country / language / org type). Membership is re-resolved from live data on every use and always excludes suppressed and invalid contacts.

### 4. Content generation (`generator.py`)
- Uses the Mistral chat API (`MISTRAL_MODEL`, default `mistral-large-latest`) with a strict system prompt and a JSON response contract.
- Recipient language drives the output language (English base, automatic adaptation).
- Offline fallback templates (EN/DE/FR + default EN) keep the whole workflow testable without an API key.

### 5. Campaign lifecycle (`campaigns.py`)
`draft → pending_approval → approved → sending → sent`
- `create_draft` mirrors the campaign into Listmonk (list, subscribers with attributes, template, draft campaign) but **never starts it**.
- `approve` requires the human approver's name; stored with timestamp in `campaigns` and `action_log`.
- `start` requires **both** DB approval and `KULISA_SENDING_ENABLED=true`.

### 6. Listmonk integration (`listmonk_client.py`)
Admin API over HTTP: health, lists, templates, subscribers, campaigns (create/update/status), bounces, unsubscribed subscribers. Auth via API token or basic auth from env. All state changes logged.

### 7. Monitoring (`monitor.py`)
Pulls campaign stats and bounces from Listmonk; auto-suppresses hard bounces and unsubscribed subscribers; records replies (optionally polled from an IMAP inbox using stdlib `imaplib`).

### 8. Reporting (`reports.py`)
Daily markdown report: contact health, campaign pipeline, sent/bounce/complaint/reply/unsubscribe numbers, per-campaign approval trail, and the last 15 audit-log actions. Stored in `daily_reports` and written to `reports/`.

### 9. Dashboard (`dashboard.py`)
FastAPI: `/` (HTML cards + campaign/segment tables) and `/api/stats` (JSON).

## Data model (schema.sql)
`contacts`, `import_batches`, `suppression_list`, `segments`, `segment_members`, `campaigns`, `campaign_stats`, `replies`, `daily_reports`, `action_log` (JSONB audit trail of every campaign action).

## Deployment (separate VPS)
- Run PostgreSQL + Listmonk via `docker-compose.yml` (Listmonk bound to loopback; put a reverse proxy in front if remote admin access is needed).
- Run the agent (CLI + dashboard) under systemd or a process manager, with `.env` holding `KULISA_DATABASE_URL`, `LISTMONK_*`, `MISTRAL_API_KEY`.
- Configure Listmonk's SMTP with the external professional delivery provider.
- The existing Beget hosting environment is not touched.
