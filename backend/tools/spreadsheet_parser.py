"""Parse spreadsheet files (Excel, CSV) into COA import format."""
from __future__ import annotations
import csv
import io
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple

import pandas as pd

# Month column names (canonical lowercase)
_MONTH_KEYS = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]
_MONTH_ALIASES = {
    "january": "jan", "jan": "jan",
    "february": "feb", "feb": "feb",
    "march": "mar", "mar": "mar",
    "april": "apr", "apr": "apr",
    "may": "may",
    "june": "jun", "jun": "jun",
    "july": "jul", "jul": "jul",
    "august": "aug", "aug": "aug",
    "september": "sep", "sep": "sep", "sept": "sep",
    "october": "oct", "oct": "oct",
    "november": "nov", "nov": "nov",
    "december": "dec", "dec": "dec",
}


def _to_decimal(value: Any) -> Decimal:
    """Best-effort conversion to Decimal; returns 0 on failure or empty."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none", "-", "n/a"):
        return Decimal("0")
    # Strip currency symbols and commas
    s = s.replace("$", "").replace(",", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_spreadsheet(file_content: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse Excel or CSV file into COA import format.
    Returns dict with 'accounts' and 'funds' lists.

    Expected columns (case-insensitive):
    - account_number, number, code (required for accounts)
    - account_name, name, description (required for accounts)
    - account_type, type (optional, defaults to EXPENSE)
    - fund, fund_id, fund_category (optional for accounts)
    - is_active, active (optional, defaults to true)

    For funds:
    - fund_id, fund, id (required)
    - fund_name, name, description (required)
    - category, fund_category (optional, defaults to GENERAL_OPERATING)
    - restriction_class, restriction (optional, defaults to WITHOUT_RESTRICTION)
    """
    if filename.lower().endswith((".xls", ".xlsx")):
        return _parse_excel(file_content)
    elif filename.lower().endswith((".csv",)):
        return _parse_csv(file_content)
    else:
        raise ValueError(f"Unsupported file format: {filename}")


def _parse_excel(file_content: bytes) -> Dict[str, Any]:
    """Parse Excel file with support for multiple sheets."""
    excel_file = io.BytesIO(file_content)
    excel_data = pd.ExcelFile(excel_file)

    result: Dict[str, Any] = {"accounts": [], "funds": [], "warnings": []}
    budget_accounts: Dict[str, Dict[str, Any]] = {}
    budget_annual_total = Decimal("0")
    budget_seen = False

    for sheet_name in excel_data.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        if df.empty:
            continue

        # Normalize column names: lowercase and replace spaces with underscores
        df.columns = [str(col).lower().strip().replace(" ", "_") for col in df.columns]

        # Detect sheet type
        has_account_id = any(col in df.columns for col in ["account_number", "number", "code"])
        has_annual = "annual_budget" in df.columns or "annual_total" in df.columns or "annual" in df.columns
        has_months = any(_MONTH_ALIASES.get(c) in _MONTH_KEYS for c in df.columns)
        has_fund_cols = any(col in df.columns for col in ["fund_id", "fund", "id"])
        has_account_name_col = any(col in df.columns for col in ["account_name", "name", "description"])

        is_budget = has_account_id and (has_annual or has_months)

        if is_budget:
            budget_seen = True
            accts, total, warnings = _extract_budget_from_df(df)
            for k, v in accts.items():
                budget_accounts[k] = v
            budget_annual_total += total
            result["warnings"].extend(warnings)
        elif has_account_id and has_account_name_col:
            result["accounts"].extend(_extract_accounts_from_df(df))
        elif has_fund_cols:
            result["funds"].extend(_extract_funds_from_df(df))

    if budget_seen:
        result["budget"] = {
            "accounts": budget_accounts,
            "annual_total": budget_annual_total,
        }

    return result


def _parse_csv(file_content: bytes) -> Dict[str, Any]:
    """Parse CSV file."""
    text_content = file_content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(text_content))

    if not reader:
        return {"accounts": [], "funds": [], "warnings": []}

    rows = list(reader)
    if not rows:
        return {"accounts": [], "funds": [], "warnings": []}

    # Normalize keys: lowercase, strip, and replace spaces with underscores.
    # Skip None keys (csv.DictReader assigns None when a row has more fields
    # than headers, e.g. when a value contains an unquoted comma).
    rows = [
        {
            k.lower().strip().replace(" ", "_"): v
            for k, v in row.items()
            if k is not None
        }
        for row in rows
    ]

    result: Dict[str, Any] = {"accounts": [], "funds": [], "warnings": []}

    # Detect type from columns
    cols = set(rows[0].keys())
    has_account_id = any(col in cols for col in ["account_number", "number", "code"])
    has_annual = "annual_budget" in cols or "annual_total" in cols or "annual" in cols
    has_months = any(_MONTH_ALIASES.get(c) in _MONTH_KEYS for c in cols)
    has_fund_cols = any(col in cols for col in ["fund_id", "fund", "id"])
    has_account_name_col = any(col in cols for col in ["account_name", "name", "description"])

    is_budget = has_account_id and (has_annual or has_months)

    if is_budget:
        accts, total, warnings = _extract_budget_from_rows(rows)
        result["budget"] = {"accounts": accts, "annual_total": total}
        result["warnings"].extend(warnings)
    elif has_account_id and has_account_name_col:
        result["accounts"] = _extract_accounts_from_rows(rows)
    elif has_fund_cols:
        result["funds"] = _extract_funds_from_rows(rows)

    return result


def _extract_budget_from_df(df: pd.DataFrame) -> Tuple[Dict[str, Dict[str, Any]], Decimal, List[str]]:
    """Extract budget rows from a DataFrame.

    Returns (accounts_dict, sum_of_annual_totals, warnings).
    accounts_dict maps account_number -> {jan..dec, annual_total} as Decimals.
    """
    rows = df.to_dict("records")
    return _extract_budget_from_rows(rows)


def _extract_budget_from_rows(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Decimal, List[str]]:
    """Extract budget rows from a list of dict rows."""
    out: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    total_sum = Decimal("0")

    for row in rows:
        # Skip empty rows
        if not any(str(v).strip() for v in row.values() if v is not None):
            continue

        # Account number (required)
        account_number = None
        for key in ["account_number", "number", "code"]:
            if key in row and row[key] is not None and str(row[key]).strip():
                account_number = str(row[key]).strip()
                # Skip NaN / null marker values from pandas
                if account_number.lower() in ("nan", "none", "null", "n/a", "-"):
                    account_number = None
                    continue
                # Strip trailing .0 from numerics
                if account_number.endswith(".0"):
                    account_number = account_number[:-2]
                break
        if not account_number:
            continue

        # Build month dict
        month_vals: Dict[str, Decimal] = {m: Decimal("0") for m in _MONTH_KEYS}
        for col, val in row.items():
            normalized = _MONTH_ALIASES.get(str(col).lower().strip())
            if normalized in _MONTH_KEYS:
                month_vals[normalized] = _to_decimal(val)

        monthly_sum = sum(month_vals.values(), Decimal("0"))

        # Annual total (explicit or derived)
        explicit_annual: "Decimal | None" = None
        for key in ["annual_budget", "annual_total", "annual"]:
            if key in row and row[key] is not None and str(row[key]).strip():
                explicit_annual = _to_decimal(row[key])
                break

        has_monthly = monthly_sum != Decimal("0")

        if explicit_annual is not None and has_monthly:
            if abs(explicit_annual - monthly_sum) > Decimal("1"):
                warnings.append(
                    f"Account {account_number}: monthly sum ${monthly_sum} disagrees with "
                    f"annual_total ${explicit_annual}; using explicit annual_total."
                )
            annual_total: Decimal = explicit_annual
        elif explicit_annual is not None:
            annual_total = explicit_annual
        elif has_monthly:
            annual_total = monthly_sum
        else:
            # All zero — skip
            continue

        entry = {**month_vals, "annual_total": annual_total}
        out[account_number] = entry
        total_sum += annual_total

    return out, total_sum, warnings


def _extract_accounts_from_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Extract accounts from pandas DataFrame."""
    rows = df.to_dict("records")
    return _extract_accounts_from_rows(rows)


def _extract_accounts_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract accounts from list of row dicts."""
    accounts = []

    for row in rows:
        # Skip empty rows
        if not any(str(v).strip() for v in row.values() if v):
            continue

        # Extract account number (required)
        account_number = None
        for key in ["account_number", "number", "code"]:
            if key in row and row[key]:
                account_number = str(row[key]).strip()
                break

        if not account_number:
            continue

        # Extract account name (required)
        account_name = None
        for key in ["account_name", "name", "description"]:
            if key in row and row[key]:
                account_name = str(row[key]).strip()
                break

        if not account_name:
            continue

        # Extract account type (optional)
        account_type = "EXPENSE"
        for key in ["account_type", "type"]:
            if key in row and row[key]:
                type_val = str(row[key]).strip().upper()
                if type_val in ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"]:
                    account_type = type_val
                break

        # Extract fund (optional)
        fund_id = None
        for key in ["fund", "fund_id", "fund_category"]:
            if key in row and row[key]:
                fund_id = str(row[key]).strip()
                break

        # Extract is_active (optional, default true)
        is_active = True
        for key in ["is_active", "active"]:
            if key in row and row[key]:
                val = str(row[key]).strip().lower()
                is_active = val not in ["false", "0", "no", "inactive"]
                break

        account = {
            "account_number": account_number,
            "account_name": account_name,
            "account_type": account_type,
            "is_active": is_active,
        }

        if fund_id:
            account["fund"] = fund_id

        accounts.append(account)

    return accounts


def _extract_funds_from_df(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Extract funds from pandas DataFrame."""
    rows = df.to_dict("records")
    return _extract_funds_from_rows(rows)


def _extract_funds_from_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract funds from list of row dicts."""
    funds = []

    for row in rows:
        # Skip empty rows
        if not any(str(v).strip() for v in row.values() if v):
            continue

        # Extract fund id (required)
        fund_id = None
        for key in ["fund_id", "fund", "id"]:
            if key in row and row[key]:
                fund_id = str(row[key]).strip()
                break

        if not fund_id:
            continue

        # Extract fund name (required)
        fund_name = None
        for key in ["fund_name", "name", "description"]:
            if key in row and row[key]:
                fund_name = str(row[key]).strip()
                break

        if not fund_name:
            continue

        # Extract category (optional) - map friendly names to enum values
        category = "GENERAL_OPERATING"
        category_mapping = {
            "GENERAL_OPERATING": "GENERAL_OPERATING",
            "OPERATING": "GENERAL_OPERATING",
            "TEMPORARY_RESTRICTED": "TEMP_RESTRICTED_PURPOSE",
            "TEMP_RESTRICTED": "TEMP_RESTRICTED_PURPOSE",
            "TEMP_RESTRICTED_PURPOSE": "TEMP_RESTRICTED_PURPOSE",
            "TEMP_RESTRICTED_TIME": "TEMP_RESTRICTED_TIME",
            "PERMANENTLY_RESTRICTED": "PERMANENTLY_RESTRICTED",
            "ENDOWMENT": "PERMANENTLY_RESTRICTED",
            "BOARD_DESIGNATED": "BOARD_DESIGNATED",
            "CAPITAL_CAMPAIGN": "CAPITAL_CAMPAIGN",
        }
        for key in ["category", "fund_category"]:
            if key in row and row[key]:
                cat_val = str(row[key]).strip().upper()
                if cat_val in category_mapping:
                    category = category_mapping[cat_val]
                break

        # Extract restriction class (optional)
        restriction_class = "WITHOUT_RESTRICTION"
        for key in ["restriction_class", "restriction"]:
            if key in row and row[key]:
                rest_val = str(row[key]).strip().upper()
                if rest_val in ["WITHOUT_RESTRICTION", "WITH_RESTRICTION_PURPOSE", "WITH_RESTRICTION_PERMANENT"]:
                    restriction_class = rest_val
                break

        fund = {
            "fund_id": fund_id,
            "fund_name": fund_name,
            "category": category,
            "restriction_class": restriction_class,
        }

        funds.append(fund)

    return funds
