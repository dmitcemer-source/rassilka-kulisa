-- KULISA Email Campaign Manager - PostgreSQL schema

CREATE TABLE IF NOT EXISTS contacts (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    first_name      TEXT,
    last_name       TEXT,
    organization    TEXT,
    org_type        TEXT,              -- theatre | company | producer | festival | agency | other
    country         TEXT,
    language        TEXT,              -- ISO 639-1, defaults from country mapping
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending | valid | invalid | risky
    status_reason   TEXT,
    source          TEXT,
    listmonk_subscriber_id INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS import_batches (
    id              SERIAL PRIMARY KEY,
    filename        TEXT NOT NULL,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_rows      INTEGER NOT NULL DEFAULT 0,
    valid_count     INTEGER NOT NULL DEFAULT 0,
    invalid_count   INTEGER NOT NULL DEFAULT 0,
    duplicate_count INTEGER NOT NULL DEFAULT 0,
    suppressed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS suppression_list (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    reason          TEXT NOT NULL,     -- unsubscribe | bounce | complaint | manual | invalid | seeded
    source          TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS segments (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    country         TEXT,
    language        TEXT,
    org_type        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS segment_members (
    segment_id      INTEGER NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
    contact_id      INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (segment_id, contact_id)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    subject         TEXT,
    body            TEXT,
    language        TEXT DEFAULT 'en',
    segment_id      INTEGER REFERENCES segments(id),
    listmonk_campaign_id INTEGER,
    listmonk_list_id INTEGER,
    status          TEXT NOT NULL DEFAULT 'draft',
                    -- draft | pending_approval | approved | sending | sent | failed | cancelled
    test_mode       BOOLEAN NOT NULL DEFAULT TRUE,
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS campaign_stats (
    id              SERIAL PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    sent            INTEGER NOT NULL DEFAULT 0,
    delivered       INTEGER NOT NULL DEFAULT 0,
    bounced         INTEGER NOT NULL DEFAULT 0,
    complained      INTEGER NOT NULL DEFAULT 0,
    unsubscribed    INTEGER NOT NULL DEFAULT 0,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS replies (
    id              SERIAL PRIMARY KEY,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    contact_id      INTEGER REFERENCES contacts(id),
    from_email      TEXT,
    subject         TEXT,
    body_excerpt    TEXT,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id              SERIAL PRIMARY KEY,
    report_date     DATE NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (report_date)
);

CREATE TABLE IF NOT EXISTS action_log (
    id              SERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    details         JSONB
);

CREATE INDEX IF NOT EXISTS idx_contacts_status ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_language ON contacts(language);
CREATE INDEX IF NOT EXISTS idx_contacts_country ON contacts(country);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
