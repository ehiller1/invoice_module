-- Phase 3 Migration: Add card tables, fund restrictions, policy versioning, recurring learning
-- Applied to existing EIME database

-- Add new enums if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'restriction_type') THEN
        CREATE TYPE restriction_type AS ENUM ('SOFT', 'HARD');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'card_status') THEN
        CREATE TYPE card_status AS ENUM ('OPEN', 'IN_REVIEW', 'RESOLVED', 'CANCELLED');
    END IF;
END $$;

-- 22. Exception Cards (HITL inbox, Flow 5)
CREATE TABLE IF NOT EXISTS exception_cards (
    id SERIAL PRIMARY KEY,
    card_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    job_id VARCHAR(64),
    exception_type VARCHAR(100) NOT NULL,
    status card_status NOT NULL DEFAULT 'OPEN',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    evidence JSONB,
    suggested_action JSONB,
    assigned_to VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolution_data JSONB
);
CREATE INDEX IF NOT EXISTS idx_exception_cards_church_id ON exception_cards(church_id);
CREATE INDEX IF NOT EXISTS idx_exception_cards_status ON exception_cards(church_id, status);
CREATE INDEX IF NOT EXISTS idx_exception_cards_job_id ON exception_cards(church_id, job_id);
CREATE INDEX IF NOT EXISTS idx_exception_cards_created ON exception_cards(church_id, created_at);

-- 23. Policy Cards
CREATE TABLE IF NOT EXISTS policy_cards (
    id SERIAL PRIMARY KEY,
    card_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    policy_id VARCHAR(100),
    status card_status NOT NULL DEFAULT 'OPEN',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    proposed_by VARCHAR(255),
    requires_vote BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    resolution_data JSONB
);
CREATE INDEX IF NOT EXISTS idx_policy_cards_church_id ON policy_cards(church_id);
CREATE INDEX IF NOT EXISTS idx_policy_cards_status ON policy_cards(church_id, status);
CREATE INDEX IF NOT EXISTS idx_policy_cards_created ON policy_cards(church_id, created_at);

-- 24. Question Cards
CREATE TABLE IF NOT EXISTS question_cards (
    id SERIAL PRIMARY KEY,
    card_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    question_text VARCHAR(500) NOT NULL,
    status card_status NOT NULL DEFAULT 'OPEN',
    asked_by VARCHAR(255),
    assigned_to VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    response TEXT,
    response_data JSONB
);
CREATE INDEX IF NOT EXISTS idx_question_cards_church_id ON question_cards(church_id);
CREATE INDEX IF NOT EXISTS idx_question_cards_status ON question_cards(church_id, status);
CREATE INDEX IF NOT EXISTS idx_question_cards_created ON question_cards(church_id, created_at);

-- 25. Recommendation Cards
CREATE TABLE IF NOT EXISTS recommendation_cards (
    id SERIAL PRIMARY KEY,
    card_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    recommendation_type VARCHAR(100) NOT NULL,
    status card_status NOT NULL DEFAULT 'OPEN',
    title VARCHAR(255) NOT NULL,
    description TEXT,
    impact_score NUMERIC(5, 2),
    confidence_pct NUMERIC(5, 2),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMP,
    decision_data JSONB
);
CREATE INDEX IF NOT EXISTS idx_recommendation_cards_church_id ON recommendation_cards(church_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_cards_status ON recommendation_cards(church_id, status);
CREATE INDEX IF NOT EXISTS idx_recommendation_cards_created ON recommendation_cards(church_id, created_at);

-- 26. Fund Restrictions with Type
CREATE TABLE IF NOT EXISTS fund_restrictions (
    id SERIAL PRIMARY KEY,
    restriction_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    fund_id VARCHAR(50) NOT NULL,
    restriction_type restriction_type NOT NULL DEFAULT 'SOFT',
    restriction_reason VARCHAR(255),
    description TEXT,
    override_role VARCHAR(50),
    effective_date DATE,
    expiration_date DATE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_fund_restrictions_church_id ON fund_restrictions(church_id);
CREATE INDEX IF NOT EXISTS idx_fund_restrictions_fund_id ON fund_restrictions(church_id, fund_id);
CREATE INDEX IF NOT EXISTS idx_fund_restrictions_type ON fund_restrictions(restriction_type);

-- 27. Policy Versions
CREATE TABLE IF NOT EXISTS policy_versions (
    id SERIAL PRIMARY KEY,
    policy_id VARCHAR(100) NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    policy_text TEXT NOT NULL,
    effective_date DATE NOT NULL,
    expires_date DATE,
    created_by VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, policy_id, version)
);
CREATE INDEX IF NOT EXISTS idx_policy_versions_church_id ON policy_versions(church_id);
CREATE INDEX IF NOT EXISTS idx_policy_versions_effective ON policy_versions(church_id, effective_date);

-- 28. Recurring Tolerance History
CREATE TABLE IF NOT EXISTS recurring_tolerance_history (
    id SERIAL PRIMARY KEY,
    recurring_id VARCHAR(64) NOT NULL REFERENCES recurring_journal_entries(recurring_id) ON DELETE CASCADE,
    tolerance_low NUMERIC(12, 2),
    tolerance_high NUMERIC(12, 2),
    acceptance_count INTEGER DEFAULT 0,
    rejection_count INTEGER DEFAULT 0,
    last_adjusted_at TIMESTAMP,
    adjusted_by VARCHAR(255),
    rationale TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tolerance_history_recurring_id ON recurring_tolerance_history(recurring_id);
CREATE INDEX IF NOT EXISTS idx_tolerance_history_created ON recurring_tolerance_history(created_at);

-- Update schema version
INSERT INTO schema_version (version, description) VALUES (2, 'Phase 3: Cards, fund restrictions, policy versioning, recurring learning')
ON CONFLICT DO NOTHING;
