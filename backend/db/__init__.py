"""Database module — PostgreSQL persistence layer."""
from .connection import get_connection, close_pool, init_pool
from .migrations import run_migrations, check_schema_version

# Re-export store submodules so callers can do `from .db import coa_store`.
from . import (
    coa_store,
    journal_entry_store,
    payment_store,
    plaid_store,
    vendor_store,
    approval_store,
    approval_audit_store,
    bank_txn_store,
    recon_store,
    processing_job_store,
    decision_ledger_store,
)

__all__ = [
    "get_connection",
    "close_pool",
    "init_pool",
    "run_migrations",
    "check_schema_version",
    # store submodules
    "coa_store",
    "journal_entry_store",
    "payment_store",
    "plaid_store",
    "vendor_store",
    "approval_store",
    "approval_audit_store",
    "bank_txn_store",
    "recon_store",
    "processing_job_store",
    "decision_ledger_store",
]
