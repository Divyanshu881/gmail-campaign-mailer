"""Contact parsing for campaigns.

Reuses the useful logic from the legacy `mailer.py` (column normalization,
email validation, duplicate removal) but returns structured rows of plain
dicts instead of pandas DataFrames, so arbitrary contact fields can be stored
as JSONB and used as Jinja2 template variables.
"""

import io
import re

import pandas as pd

# Matches a basic, clearly-valid email. Same regex as the legacy mailer.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Keep this mapping in sync with mailer.py normalize_column_names(). It only
# standardizes the common Apollo/outreach variants; everything else keeps its
# original name and becomes a template placeholder as-is.
COLUMN_MAPPING = {
    "first name": "First_name",
    "firstname": "First_name",
    "first_name": "First_name",
    "last name": "Last_name",
    "lastname": "Last_name",
    "last_name": "Last_name",
    "company": "Company_name",
    "organization": "Company_name",
    "company name": "Company_name",
    "company_name": "Company_name",
    "email": "Email",
    "email address": "Email",
    "email_address": "Email",
}

# Values pandas/Excel turn empty cells into.
_EMPTY_VALUES = {"", "nan", "none", "null", "na", "n/a"}


class ContactFileError(Exception):
    """Raised when a contact file cannot be parsed (user-facing message)."""


def normalize_column(name) -> str:
    """Map a column name to a valid Jinja2-safe placeholder name."""
    return COLUMN_MAPPING.get(str(name).strip().lower(), str(name).strip())


def is_valid_email(email) -> bool:
    """Basic format validation for an email address."""
    if not isinstance(email, str) or not email.strip():
        return False
    return EMAIL_RE.match(email.strip()) is not None


def _read_dataframe(filename: str, data: bytes) -> pd.DataFrame:
    """Read CSV or Excel into a DataFrame based on the file extension."""
    lower = filename.lower()
    try:
        if lower.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(data), engine="openpyxl")
        if lower.endswith(".csv") or lower.endswith(".txt"):
            return pd.read_csv(io.BytesIO(data), encoding="utf-8-sig")
    except Exception as exc:
        raise ContactFileError(f"Could not read '{filename}': {exc}")
    raise ContactFileError(
        f"Unsupported file type: '{filename}'. Upload a .csv or .xlsx file."
    )


def parse_contacts_file(filename: str, data: bytes) -> dict:
    """Parse and validate a CSV/Excel file into per-contact rows.

    Returns:
        {
          "filename": str,
          "columns": [normalized column names],
          "rows": [{"email", "data", "status", "reason"}],
          "summary": {"total", "valid", "invalid", "duplicates"},
        }

    Row status is one of: "pending" (valid & unique), "invalid" (bad/missing
    email), "duplicate" (email already seen). `data` holds the full normalized
    row (JSONB-ready) so any column can be used as a template placeholder.
    """
    df = _read_dataframe(filename, data)
    df = df.rename(columns=lambda c: normalize_column(c))

    if "Email" not in df.columns:
        raise ContactFileError(
            "Missing 'Email' column in contact file. "
            "Expected one of: Email, Email Address, email_address."
        )

    df["Email"] = df["Email"].astype(str).str.strip()
    df = df.fillna("")

    rows = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        record = {
            str(k): (str(v) if str(v) not in _EMPTY_VALUES else "")
            for k, v in row.items()
        }
        email = record.get("Email", "").strip()

        if not email or email.lower() in _EMPTY_VALUES:
            rows.append(
                {
                    "email": email,
                    "data": record,
                    "status": "invalid",
                    "reason": "missing email",
                }
            )
            continue

        if not is_valid_email(email):
            rows.append(
                {
                    "email": email,
                    "data": record,
                    "status": "invalid",
                    "reason": "invalid email",
                }
            )
            continue

        key = email.lower()  # case-insensitive duplicate detection
        if key in seen:
            rows.append(
                {
                    "email": email,
                    "data": record,
                    "status": "duplicate",
                    "reason": "duplicate email",
                }
            )
            continue

        seen.add(key)
        rows.append({"email": email, "data": record, "status": "pending", "reason": None})

    summary = {
        "total": len(rows),
        "valid": sum(1 for r in rows if r["status"] == "pending"),
        "invalid": sum(1 for r in rows if r["status"] == "invalid"),
        "duplicates": sum(1 for r in rows if r["status"] == "duplicate"),
    }
    return {
        "filename": filename,
        "columns": list(df.columns),
        "rows": rows,
        "summary": summary,
    }


def merge_rows_placeholder_fields(rows: list) -> set[str]:
    """Union of all contact fields (normalized column names) across rows."""
    fields: set[str] = set()
    for row in rows:
        fields.update(row.get("data", {}).keys())
    return fields