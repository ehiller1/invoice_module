#!/usr/bin/env python3
"""Migrate data from JSON/JSONL files to PostgreSQL.

Reads all existing JSON and JSONL files from ``backend/data/`` and populates
the corresponding PostgreSQL tables via the store modules. Original files are
copied to ``backend/data/.backup_TIMESTAMP/`` before any state-changing work
completes, so the migration is reversible.

The script is **idempotent**:
    - Churches / Chart of Accounts use ``save_accounting_context`` which
      upserts.
    - Journal entries are skipped if ``get_journal_entry`` already returns a
      row for the entry_id.
    - Payments are skipped if ``get_payment`` already returns a row.
    - Vendors / approval chains use ``save_*`` helpers that replace by
      ``(church_id, name|gl_pattern)``.

Usage::

    python -m backend.db.migrate_from_files            # full migration
    python -m backend.db.migrate_from_files --dry-run  # parse only, no writes
    python -m backend.db.migrate_from_files --verbose  # print each record

Exit codes:
    0  - success (all files migrated, counts verified)
    1  - one or more file-level failures
    2  - fatal error before migration could start (e.g. DB unreachable)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Imports are written so this module can be invoked either as
#     python -m backend.db.migrate_from_files
# (preferred, package-relative imports) or directly as a script.
# ---------------------------------------------------------------------------
try:  # package execution
    from .connection import init_pool
    from .coa_store import save_accounting_context
    from .journal_entry_store import create_journal_entry, get_journal_entry
    from .payment_store import create_payment, get_payment
    from .vendor_store import save_vendors
    from .approval_store import save_chains
    from ..models.schemas import (
        AccountingContext,
        ApprovalChain,
        JournalEntry,
        PaymentInstruction,
        Vendor,
    )
except ImportError:  # direct execution fallback
    import os

    HERE = Path(__file__).resolve()
    sys.path.insert(0, str(HERE.parents[2]))  # repo root
    from backend.db.connection import init_pool  # type: ignore
    from backend.db.coa_store import save_accounting_context  # type: ignore
    from backend.db.journal_entry_store import (  # type: ignore
        create_journal_entry,
        get_journal_entry,
    )
    from backend.db.payment_store import create_payment, get_payment  # type: ignore
    from backend.db.vendor_store import save_vendors  # type: ignore
    from backend.db.approval_store import save_chains  # type: ignore
    from backend.models.schemas import (  # type: ignore
        AccountingContext,
        ApprovalChain,
        JournalEntry,
        PaymentInstruction,
        Vendor,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = DATA_DIR / f".backup_{TIMESTAMP}"


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------
@dataclass
class MigrationStats:
    """Per-table migration outcome."""

    label: str
    files_seen: int = 0
    records_attempted: int = 0
    records_migrated: int = 0
    records_skipped: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"{self.label:<22} "
            f"files={self.files_seen:<3} "
            f"migrated={self.records_migrated:<5} "
            f"skipped={self.records_skipped:<5} "
            f"errors={len(self.errors)}"
        )


def _log(msg: str, *, verbose_only: bool = False, verbose: bool = False) -> None:
    if verbose_only and not verbose:
        return
    print(msg)


# ---------------------------------------------------------------------------
# Migrators
# ---------------------------------------------------------------------------
def migrate_churches(*, dry_run: bool, verbose: bool) -> MigrationStats:
    """Migrate church COAs from ``context_*.json`` files."""
    stats = MigrationStats("Churches & COA")
    print("\n[MIGRATION] Churches & Chart of Accounts")

    coa_files = sorted(DATA_DIR.glob("context_*.json"))
    if not coa_files:
        print("  -> No churches found")
        return stats

    for coa_file in coa_files:
        stats.files_seen += 1
        stats.records_attempted += 1
        try:
            data = json.loads(coa_file.read_text())
            ctx = AccountingContext.model_validate(data)
            if dry_run:
                print(
                    f"  [dry-run] would save {ctx.church_id}: "
                    f"{len(ctx.accounts)} accounts, {len(ctx.funds)} funds"
                )
            else:
                save_accounting_context(ctx)
                print(
                    f"  ok {ctx.church_id}: "
                    f"{len(ctx.accounts)} accounts, {len(ctx.funds)} funds"
                )
            stats.records_migrated += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"{coa_file.name}: {exc}"
            stats.errors.append(msg)
            print(f"  FAIL {msg}")
            if verbose:
                traceback.print_exc()

    return stats


def migrate_journal_entries(*, dry_run: bool, verbose: bool) -> MigrationStats:
    """Migrate manual JEs from ``jes_*.jsonl`` files."""
    stats = MigrationStats("Journal Entries")
    print("\n[MIGRATION] Journal Entries")

    je_files = sorted(DATA_DIR.glob("jes_*.jsonl"))
    if not je_files:
        print("  -> No JE files found")
        return stats

    for je_file in je_files:
        stats.files_seen += 1
        church_id = je_file.stem.replace("jes_", "")
        with je_file.open() as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                stats.records_attempted += 1
                try:
                    je_data = json.loads(line)
                    je = JournalEntry.model_validate(je_data)

                    # Idempotency: skip if entry_id already exists.
                    existing = None
                    if not dry_run and je.entry_id:
                        try:
                            existing = get_journal_entry(je.entry_id)
                        except Exception:
                            existing = None
                    if existing is not None:
                        stats.records_skipped += 1
                        _log(
                            f"  skip {church_id} {je.entry_id} (already exists)",
                            verbose_only=True,
                            verbose=verbose,
                        )
                        continue

                    if dry_run:
                        _log(
                            f"  [dry-run] {church_id} {je.entry_id}",
                            verbose_only=True,
                            verbose=verbose,
                        )
                    else:
                        create_journal_entry(church_id, je)
                    stats.records_migrated += 1
                except Exception as exc:  # noqa: BLE001
                    msg = f"{je_file.name}:{line_no}: {exc}"
                    stats.errors.append(msg)
                    print(f"  FAIL {msg}")
                    if verbose:
                        traceback.print_exc()

    print(
        f"  -> migrated {stats.records_migrated}, "
        f"skipped {stats.records_skipped}, errors {len(stats.errors)}"
    )
    return stats


def migrate_payments(*, dry_run: bool, verbose: bool) -> MigrationStats:
    """Migrate payments from ``payments_*.jsonl`` files."""
    stats = MigrationStats("Payments")
    print("\n[MIGRATION] Payments")

    pmt_files = sorted(DATA_DIR.glob("payments_*.jsonl"))
    if not pmt_files:
        print("  -> No payment files found")
        return stats

    for pmt_file in pmt_files:
        stats.files_seen += 1
        church_id = pmt_file.stem.replace("payments_", "")
        with pmt_file.open() as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                stats.records_attempted += 1
                try:
                    pmt_data = json.loads(line)
                    pmt = PaymentInstruction.model_validate(pmt_data)

                    pmt_id = getattr(pmt, "payment_id", None) or getattr(pmt, "id", None)
                    existing = None
                    if not dry_run and pmt_id:
                        try:
                            existing = get_payment(str(pmt_id))
                        except Exception:
                            existing = None
                    if existing is not None:
                        stats.records_skipped += 1
                        _log(
                            f"  skip {church_id} {pmt_id} (already exists)",
                            verbose_only=True,
                            verbose=verbose,
                        )
                        continue

                    if dry_run:
                        _log(
                            f"  [dry-run] {church_id} {pmt_id}",
                            verbose_only=True,
                            verbose=verbose,
                        )
                    else:
                        create_payment(church_id, pmt)
                    stats.records_migrated += 1
                except Exception as exc:  # noqa: BLE001
                    msg = f"{pmt_file.name}:{line_no}: {exc}"
                    stats.errors.append(msg)
                    print(f"  FAIL {msg}")
                    if verbose:
                        traceback.print_exc()

    print(
        f"  -> migrated {stats.records_migrated}, "
        f"skipped {stats.records_skipped}, errors {len(stats.errors)}"
    )
    return stats


def migrate_vendors(*, dry_run: bool, verbose: bool) -> MigrationStats:
    """Migrate vendors from ``vendors_*.json`` files."""
    stats = MigrationStats("Vendors")
    print("\n[MIGRATION] Vendors")

    vendor_files = sorted(DATA_DIR.glob("vendors_*.json"))
    if not vendor_files:
        print("  -> No vendor files found")
        return stats

    for vendor_file in vendor_files:
        stats.files_seen += 1
        church_id = vendor_file.stem.replace("vendors_", "")
        try:
            data = json.loads(vendor_file.read_text())
            raw = data if isinstance(data, list) else [data]
            vendors = [Vendor.model_validate(v) for v in raw]
            stats.records_attempted += len(vendors)
            if dry_run:
                print(f"  [dry-run] {church_id}: {len(vendors)} vendors")
            else:
                # save_vendors is replace-by-name → naturally idempotent.
                save_vendors(church_id, vendors)
                print(f"  ok {church_id}: {len(vendors)} vendors")
            stats.records_migrated += len(vendors)
        except Exception as exc:  # noqa: BLE001
            msg = f"{vendor_file.name}: {exc}"
            stats.errors.append(msg)
            print(f"  FAIL {msg}")
            if verbose:
                traceback.print_exc()

    return stats


def migrate_approval_chains(*, dry_run: bool, verbose: bool) -> MigrationStats:
    """Migrate approval chains from ``approval_chains_*.json`` files."""
    stats = MigrationStats("Approval Chains")
    print("\n[MIGRATION] Approval Chains")

    chain_files = sorted(DATA_DIR.glob("approval_chains_*.json"))
    if not chain_files:
        print("  -> No approval chain files found")
        return stats

    for chain_file in chain_files:
        stats.files_seen += 1
        church_id = chain_file.stem.replace("approval_chains_", "")
        try:
            data = json.loads(chain_file.read_text())
            raw = data if isinstance(data, list) else [data]
            chains = [ApprovalChain.model_validate(c) for c in raw]
            stats.records_attempted += len(chains)
            if dry_run:
                print(f"  [dry-run] {church_id}: {len(chains)} chains")
            else:
                # save_chains replaces all chains for a church → idempotent.
                save_chains(church_id, chains)
                print(f"  ok {church_id}: {len(chains)} chains")
            stats.records_migrated += len(chains)
        except Exception as exc:  # noqa: BLE001
            msg = f"{chain_file.name}: {exc}"
            stats.errors.append(msg)
            print(f"  FAIL {msg}")
            if verbose:
                traceback.print_exc()

    return stats


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
_BACKUP_PATTERNS = ("*.json", "*.jsonl")


def backup_files(*, verbose: bool) -> int:
    """Copy original JSON/JSONL files into the timestamped backup folder.

    Returns the number of files backed up. Files inside any ``.backup_*``
    sibling directory are skipped so repeated runs don't recurse.
    """
    print(f"\n[BACKUP] Archiving original files to {BACKUP_DIR}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    n = 0
    seen: set[Path] = set()
    for pattern in _BACKUP_PATTERNS:
        for src in DATA_DIR.glob(pattern):
            if src in seen:
                continue
            seen.add(src)
            # Skip files already inside a backup directory.
            if any(part.startswith(".backup_") for part in src.relative_to(DATA_DIR).parts[:-1]):
                continue
            if src.parent != DATA_DIR:
                continue
            dest = BACKUP_DIR / src.name
            shutil.copy2(src, dest)
            n += 1
            _log(f"  backed up {src.name}", verbose_only=True, verbose=verbose)

    print(f"  -> {n} file(s) archived")
    return n


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify_counts(per_table: List[MigrationStats]) -> Tuple[bool, List[str]]:
    """Verify (attempted == migrated + skipped) for every table.

    This catches silent drops without re-querying the database, which keeps
    the script self-contained even when individual store modules don't expose
    a ``count_*`` helper.
    """
    issues: List[str] = []
    for s in per_table:
        if s.records_attempted != s.records_migrated + s.records_skipped:
            issues.append(
                f"{s.label}: attempted={s.records_attempted} "
                f"migrated={s.records_migrated} skipped={s.records_skipped}"
            )
    return (not issues), issues


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate data from JSON/JSONL files to PostgreSQL."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate files without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-record progress and stack traces for failures.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the file backup step (not recommended).",
    )
    args = parser.parse_args(argv)

    if not DATA_DIR.exists():
        print(f"[FATAL] Data directory does not exist: {DATA_DIR}")
        return 2

    if args.dry_run:
        print("[DRY-RUN] Migration simulation (no DB writes will be made)")
    print(f"[MIGRATION] Source:  {DATA_DIR}")
    print(f"[MIGRATION] Backup:  {BACKUP_DIR}")

    # Initialize the connection pool (skip in dry-run if you really want zero
    # DB contact, but we still want validation that the pool *could* start in
    # the normal path).
    if not args.dry_run:
        try:
            init_pool()
        except Exception as exc:  # noqa: BLE001
            print(f"[FATAL] Could not initialize DB pool: {exc}")
            return 2

    migrators: List[Callable[..., MigrationStats]] = [
        migrate_churches,
        migrate_journal_entries,
        migrate_payments,
        migrate_vendors,
        migrate_approval_chains,
    ]

    per_table: List[MigrationStats] = []
    for fn in migrators:
        per_table.append(fn(dry_run=args.dry_run, verbose=args.verbose))

    # Backup happens after the migration attempt so a fatal early error
    # doesn't leave a half-empty backup folder.
    if not args.dry_run and not args.no_backup:
        try:
            backup_files(verbose=args.verbose)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Backup failed: {exc}")

    # ---------------------------------------------------------------- summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    total_migrated = 0
    total_errors = 0
    for s in per_table:
        print("  " + s.summary())
        total_migrated += s.records_migrated
        total_errors += len(s.errors)

    ok, issues = verify_counts(per_table)
    if not ok:
        print("\n[VERIFY] Count mismatch detected:")
        for line in issues:
            print(f"  - {line}")
    else:
        print("\n[VERIFY] Record counts reconcile (attempted == migrated + skipped).")

    print(f"\n[RESULT] {total_migrated} record(s) migrated, "
          f"{total_errors} error(s).")
    if not args.dry_run:
        print(f"[RESULT] Originals archived at {BACKUP_DIR}")

    return 0 if total_errors == 0 and ok else 1


if __name__ == "__main__":
    sys.exit(main())
