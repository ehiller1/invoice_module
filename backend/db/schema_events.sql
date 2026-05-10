-- Phase 5a: Event Spine
--
-- Append-only event log + tag dimension + projection-version tracking.
-- This is the new system of record. The Phase 4 tables (journal_entries,
-- ytd_actuals, decision_ledger_entries, approval_audit_events) become
-- projections populated by event handlers; the events table is authoritative.
--
-- Idempotent: safe to run multiple times.

-- ---------------------------------------------------------------------------
-- events: the append-only log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    sequence       BIGSERIAL PRIMARY KEY,
    event_id       UUID NOT NULL UNIQUE,
    event_type     VARCHAR(64) NOT NULL,
    church_id      INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    occurred_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    recorded_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor          VARCHAR(255),
    confidence     NUMERIC(5, 4),
    payload        JSONB NOT NULL,
    caused_by      JSONB,
    correlation_id VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_events_church_type    ON events(church_id, event_type);
CREATE INDEX IF NOT EXISTS idx_events_church_time    ON events(church_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_correlation    ON events(correlation_id) WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_payload_gin    ON events USING GIN (payload);

-- ---------------------------------------------------------------------------
-- event_tags: many-to-many tag dimension
--   tag_kind ∈ {'account', 'fund', 'restriction', 'mission', 'vendor',
--               'period', 'denomination', 'document', 'job'}
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_tags (
    id        BIGSERIAL PRIMARY KEY,
    event_id  UUID NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    tag_kind  VARCHAR(32) NOT NULL,
    tag_value VARCHAR(255) NOT NULL,
    UNIQUE (event_id, tag_kind, tag_value)
);

CREATE INDEX IF NOT EXISTS idx_event_tags_kind_value ON event_tags(tag_kind, tag_value);
CREATE INDEX IF NOT EXISTS idx_event_tags_event      ON event_tags(event_id);

-- ---------------------------------------------------------------------------
-- projection_versions: tracks staleness of derived views
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projection_versions (
    projection_name      VARCHAR(64) PRIMARY KEY,
    last_event_sequence  BIGINT NOT NULL DEFAULT 0,
    last_rebuilt_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_stale             BOOLEAN NOT NULL DEFAULT FALSE
);

INSERT INTO projection_versions (projection_name) VALUES
    ('journal_entries'),
    ('ytd_actuals'),
    ('decision_ledger_entries'),
    ('approval_audit_events')
ON CONFLICT (projection_name) DO NOTHING;
