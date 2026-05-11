/**
 * EIME PostgreSQL Schema
 * Complete persistence layer for accounting system
 *
 * Includes 21 tables covering:
 * - Church hierarchy and COA
 * - Journal entries and reconciliation
 * - Plaid integration
 * - Payments and approvals
 * - Decision audit trail
 */

-- Create enum types
CREATE TYPE je_status AS ENUM (
    'DRAFT',
    'PENDING_APPROVAL',
    'APPROVED',
    'BALANCED',
    'POSTED',
    'REJECTED',
    'CANCELLED'
);

CREATE TYPE payment_status AS ENUM (
    'DRAFT',
    'PENDING_APPROVAL',
    'APPROVED',
    'PROCESSING',
    'CLEARED',
    'FAILED',
    'CANCELLED'
);

CREATE TYPE decision_category AS ENUM (
    'RECOGNIZE',      -- Extraction confidence
    'ROUTE',          -- Fraud assessment
    'CODE',           -- GL mapper choice
    'APPROVE'         -- Approval chain resolution
);

CREATE TYPE decision_outcome AS ENUM (
    'APPROVED',
    'REJECTED',
    'ESCALATED',
    'UNCERTAIN'
);

CREATE TYPE processing_status AS ENUM (
    'RECEIVED',
    'EXTRACTING',
    'CLASSIFYING',
    'MAPPING',
    'REVIEW',
    'COMPLETING',
    'FAILED'
);

-- 1. Churches (root aggregate)
CREATE TABLE churches (
    id SERIAL PRIMARY KEY,
    church_id VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL UNIQUE,
    denomination_type VARCHAR(50),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_churches_church_id ON churches(church_id);

-- 2. GL Accounts
CREATE TABLE gl_accounts (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    account_number VARCHAR(50) NOT NULL,
    account_type VARCHAR(50),
    name VARCHAR(255),
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, account_number)
);
CREATE INDEX idx_gl_accounts_church_id ON gl_accounts(church_id);
CREATE INDEX idx_gl_accounts_type ON gl_accounts(church_id, account_type);

-- 3. Funds
CREATE TABLE funds (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    fund_id VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, fund_id)
);
CREATE INDEX idx_funds_church_id ON funds(church_id);

-- 4. Approval Chains
CREATE TABLE approval_chains (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    gl_pattern VARCHAR(255) NOT NULL,
    primary_approver_email VARCHAR(255),
    primary_approver_name VARCHAR(255),
    secondary_approver_email VARCHAR(255),
    secondary_approver_name VARCHAR(255),
    deadline_hours INTEGER DEFAULT 48,
    escalation_days INTEGER DEFAULT 3,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, gl_pattern)
);
CREATE INDEX idx_approval_chains_church_id ON approval_chains(church_id);

-- 5. Budgetary Authorities
CREATE TABLE budgetary_authorities (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    gl_pattern VARCHAR(255) NOT NULL,
    max_amount NUMERIC(12, 2),
    can_override_restrictions BOOLEAN DEFAULT false,
    fund_restrictions TEXT,  -- JSON array of fund IDs
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_budgetary_authorities_church_id ON budgetary_authorities(church_id);

-- 6. Vendors
CREATE TABLE vendors (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    ach_routing VARCHAR(20),
    ach_account_enc VARCHAR(255),
    ach_account_last4 VARCHAR(4),
    address TEXT,
    w9_on_file BOOLEAN DEFAULT false,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, name)
);
CREATE INDEX idx_vendors_church_id ON vendors(church_id);
CREATE INDEX idx_vendors_name ON vendors(church_id, name);

-- 7. Plaid Accounts
CREATE TABLE plaid_accounts (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    account_id VARCHAR(100) NOT NULL,
    access_token_enc VARCHAR(500),  -- Fernet-encrypted
    account_number VARCHAR(50),
    routing_number VARCHAR(20),
    account_type VARCHAR(50),
    account_subtype VARCHAR(50),
    mask VARCHAR(10),
    name VARCHAR(255),
    current_balance NUMERIC(12, 2),
    available_balance NUMERIC(12, 2),
    is_ach_enabled BOOLEAN DEFAULT true,
    last_synced_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, account_id)
);
CREATE INDEX idx_plaid_accounts_church_id ON plaid_accounts(church_id);

-- 8. Accounting Contexts (COA snapshots)
CREATE TABLE accounting_contexts (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    fiscal_year INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, fiscal_year)
);
CREATE INDEX idx_accounting_contexts_church_id ON accounting_contexts(church_id);

-- 9. Budget Plans
CREATE TABLE budget_plans (
    id SERIAL PRIMARY KEY,
    accounting_context_id INTEGER NOT NULL REFERENCES accounting_contexts(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 10. Budget Months (nested under BudgetPlan)
CREATE TABLE budget_months (
    id SERIAL PRIMARY KEY,
    budget_plan_id INTEGER NOT NULL REFERENCES budget_plans(id) ON DELETE CASCADE,
    account_number VARCHAR(50) NOT NULL,
    month INTEGER NOT NULL,
    budgeted_amount NUMERIC(12, 2) DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_budget_months_plan_id ON budget_months(budget_plan_id);
CREATE INDEX idx_budget_months_account ON budget_months(account_number);

-- 11. YTD Actuals
CREATE TABLE ytd_actuals (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    account_number VARCHAR(50) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    amount NUMERIC(12, 2) DEFAULT 0,
    version INTEGER DEFAULT 1,  -- For optimistic locking
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (church_id, account_number, fiscal_year)
);
CREATE INDEX idx_ytd_actuals_church_id ON ytd_actuals(church_id);
CREATE INDEX idx_ytd_actuals_period ON ytd_actuals(church_id, fiscal_year);

-- 12. Journal Entries
CREATE TABLE journal_entries (
    id SERIAL PRIMARY KEY,
    entry_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    status je_status NOT NULL DEFAULT 'DRAFT',
    entry_date DATE NOT NULL,
    posting_date DATE,
    fiscal_year INTEGER,
    accounting_period INTEGER,
    total_debits NUMERIC(12, 2) DEFAULT 0,
    total_credits NUMERIC(12, 2) DEFAULT 0,
    is_balanced BOOLEAN DEFAULT false,
    audit_trail_url VARCHAR(500),
    memo TEXT,
    version INTEGER DEFAULT 1,  -- For optimistic locking
    source VARCHAR(50),  -- 'MANUAL', 'INVOICE', 'PAYMENT', etc.
    source_id VARCHAR(100),  -- Links back to job_id, payment_id, etc.
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_journal_entries_entry_id ON journal_entries(entry_id);
CREATE INDEX idx_journal_entries_church_id ON journal_entries(church_id);
CREATE INDEX idx_journal_entries_status ON journal_entries(church_id, status);
CREATE INDEX idx_journal_entries_date ON journal_entries(church_id, entry_date);
CREATE INDEX idx_journal_entries_period ON journal_entries(church_id, fiscal_year, accounting_period);

-- 13. Journal Entry Lines
CREATE TABLE journal_entry_lines (
    id SERIAL PRIMARY KEY,
    journal_entry_id INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_number VARCHAR(50) NOT NULL,
    fund_id VARCHAR(50),
    debit NUMERIC(12, 2),
    credit NUMERIC(12, 2),
    description TEXT,
    line_no INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_je_lines_entry_id ON journal_entry_lines(journal_entry_id);
CREATE INDEX idx_je_lines_account ON journal_entry_lines(account_number);

-- 14. Payment Instructions
CREATE TABLE payment_instructions (
    id SERIAL PRIMARY KEY,
    payment_id VARCHAR(100) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    je_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
    vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
    status payment_status NOT NULL DEFAULT 'DRAFT',
    method VARCHAR(50),  -- 'ACH', 'CHECK', 'CARD'
    amount NUMERIC(12, 2) NOT NULL,
    memo TEXT,
    ach_record JSONB,  -- ACH debit/credit record
    check_record JSONB,
    cc_memo VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
CREATE INDEX idx_payments_payment_id ON payment_instructions(payment_id);
CREATE INDEX idx_payments_church_id ON payment_instructions(church_id);
CREATE INDEX idx_payments_status ON payment_instructions(church_id, status);
CREATE INDEX idx_payments_date ON payment_instructions(church_id, created_at);

-- 15. Plaid Transactions
CREATE TABLE plaid_transactions (
    id SERIAL PRIMARY KEY,
    txn_id VARCHAR(100) NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES plaid_accounts(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    description VARCHAR(500),
    amount NUMERIC(12, 2) NOT NULL,
    category VARCHAR(100),
    merchant_name VARCHAR(255),
    fetched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (account_id, txn_id)
);
CREATE INDEX idx_plaid_txns_church_id ON plaid_transactions(church_id);
CREATE INDEX idx_plaid_txns_account_id ON plaid_transactions(account_id);
CREATE INDEX idx_plaid_txns_date ON plaid_transactions(church_id, date);
CREATE INDEX idx_plaid_txns_account_date ON plaid_transactions(account_id, date);

-- 16. Bank Transactions (from statement uploads)
CREATE TABLE bank_transactions (
    id SERIAL PRIMARY KEY,
    txn_id VARCHAR(100),
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    description VARCHAR(500),
    amount NUMERIC(12, 2) NOT NULL,
    type VARCHAR(50),  -- 'DEBIT', 'CREDIT', 'FEE', etc.
    source_filename VARCHAR(255),
    raw TEXT,  -- Raw CSV/OFX line if needed
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_bank_txns_church_id ON bank_transactions(church_id);
CREATE INDEX idx_bank_txns_date ON bank_transactions(church_id, date);

-- 17. Reconciliation Matches
CREATE TABLE recon_matches (
    id SERIAL PRIMARY KEY,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    plaid_txn_id INTEGER NOT NULL REFERENCES plaid_transactions(id) ON DELETE CASCADE,
    journal_entry_id INTEGER REFERENCES journal_entries(id) ON DELETE SET NULL,
    amount_diff NUMERIC(12, 2),
    days_diff INTEGER,
    matched_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recon_matches_church_id ON recon_matches(church_id);
CREATE INDEX idx_recon_matches_plaid_txn_id ON recon_matches(plaid_txn_id);
CREATE INDEX idx_recon_matches_je_id ON recon_matches(journal_entry_id);
CREATE INDEX idx_recon_matches_date ON recon_matches(church_id, matched_at);

-- 18. Processing Jobs
CREATE TABLE processing_jobs (
    id SERIAL PRIMARY KEY,
    job_id VARCHAR(64) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    status processing_status NOT NULL DEFAULT 'RECEIVED',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Store the full ProcessingJob as JSONB for flexibility
    payload JSONB NOT NULL
);
CREATE INDEX idx_processing_jobs_job_id ON processing_jobs(job_id);
CREATE INDEX idx_processing_jobs_church_id ON processing_jobs(church_id);
CREATE INDEX idx_processing_jobs_status ON processing_jobs(church_id, status);
CREATE INDEX idx_processing_jobs_created ON processing_jobs(church_id, created_at);

-- 19. Decision Ledger Entries
CREATE TABLE decision_ledger_entries (
    id SERIAL PRIMARY KEY,
    entry_id VARCHAR(64) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    job_id VARCHAR(64),  -- Links to processing_jobs.job_id
    decision_id VARCHAR(100),  -- Composite: {job_id}-{step}
    category decision_category NOT NULL,
    authoring_actor VARCHAR(255),
    policy_invoked VARCHAR(255),
    evidence_refs TEXT,  -- JSON array
    inference_chain JSONB,  -- Full decision logic
    conclusion TEXT,
    alternatives JSONB,  -- Considered alternatives
    outcome decision_outcome NOT NULL,
    disavowed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    entry_hash VARCHAR(64),
    prev_hash VARCHAR(64)
);
CREATE INDEX idx_decision_entries_entry_id ON decision_ledger_entries(entry_id);
CREATE INDEX idx_decision_entries_church_id ON decision_ledger_entries(church_id);
CREATE INDEX idx_decision_entries_job_id ON decision_ledger_entries(church_id, job_id);
CREATE INDEX idx_decision_entries_category ON decision_ledger_entries(church_id, category);
CREATE INDEX idx_decision_entries_actor ON decision_ledger_entries(church_id, authoring_actor);
CREATE INDEX idx_decision_entries_created ON decision_ledger_entries(church_id, created_at);

-- Wave 3.14: hash chain columns for tamper evidence (idempotent migration)
ALTER TABLE decision_ledger_entries ADD COLUMN IF NOT EXISTS entry_hash VARCHAR(64);
ALTER TABLE decision_ledger_entries ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64);

-- 20. Approval Audit Events
CREATE TABLE approval_audit_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    job_id VARCHAR(64),
    line_id VARCHAR(50),
    actor_email VARCHAR(255),
    actor_role VARCHAR(50),
    action VARCHAR(100),  -- 'APPROVE', 'REJECT', 'ESCALATE', etc.
    gl_at_action VARCHAR(50),
    original_gl VARCHAR(50),
    rationale TEXT,
    notes TEXT,
    prev_hash VARCHAR(64),  -- SHA-256 hash chain
    hash VARCHAR(64),
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_events_church_id ON approval_audit_events(church_id);
CREATE INDEX idx_audit_events_job_id ON approval_audit_events(job_id);
CREATE INDEX idx_audit_events_actor ON approval_audit_events(church_id, actor_email);
CREATE INDEX idx_audit_events_timestamp ON approval_audit_events(church_id, timestamp);

-- 21. Recurring Journal Entries
CREATE TABLE recurring_journal_entries (
    id SERIAL PRIMARY KEY,
    recurring_id VARCHAR(64) UNIQUE NOT NULL,
    church_id INTEGER NOT NULL REFERENCES churches(id) ON DELETE CASCADE,
    template_je_json JSONB NOT NULL,
    schedule_cron VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    next_run TIMESTAMP,
    last_run TIMESTAMP,
    draft_count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recurring_je_church_id ON recurring_journal_entries(church_id);
CREATE INDEX idx_recurring_je_next_run ON recurring_journal_entries(next_run);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description VARCHAR(255)
);

INSERT INTO schema_version (version, description) VALUES (1, 'Initial schema with 21 tables')
ON CONFLICT DO NOTHING;
