"""Campaign validation.

All validation happens BEFORE sending. Produces a structured result of
user-facing errors:
  - invalid email / duplicate email / missing email   (from contact parsing)
  - unknown placeholder / invalid template            (from template parsing)
  - missing Gmail connection                           (provider check)
"""

import logging
import re
from typing import Optional

from jinja2 import Environment, meta
from jinja2.exceptions import TemplateSyntaxError

from app import connections, contacts
from app.providers import get_provider
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

_jinja_env = Environment()

# Matches `{{ Some Words }}` - a space-separated placeholder, which is invalid
# Jinja2. Column names are normalized to underscores (e.g. {{ First_name }}).
_SPACED_PLACEHOLDER_RE = re.compile(r"{{\s*\w+\s+\w+\s*}}")


def extract_placeholders(template: str) -> tuple[set, Optional[str]]:
    """Return the set of variables used in a template.

    Returns (variables, error). error is set when the template has a Jinja2
    syntax error (invalid template).
    """
    try:
        ast = _jinja_env.parse(template)
    except TemplateSyntaxError as exc:
        return set(), f"Invalid template: {exc}"
    return meta.find_undeclared_variables(ast), None


def render_templates(
    subject_template: str,
    body_template: str,
    data: dict,
) -> tuple[str, str]:
    """Render subject/body for one contact.

    `data` is the contact's JSONB row (already normalized column names). Values
    are plain strings. Placeholders missing from `data` render as empty strings
    (validation guarantees placeholders match the uploaded columns).
    """
    subject = _jinja_env.from_string(subject_template).render(**data)
    body = _jinja_env.from_string(body_template).render(**data)
    return subject, body


def validate_templates(
    subject_template: str,
    body_template: str,
    allowed_fields: set,
) -> list[dict]:
    """Check subject/body templates for syntax errors and unknown placeholders."""
    errors: list[dict] = []
    available = ", ".join(sorted(allowed_fields)) or "none"

    for label, template in (("subject", subject_template), ("body", body_template)):
        if not template.strip():
            errors.append(
                {"type": "invalid_template", "message": f"{label.title()} template is empty."}
            )
            continue

        variables, err = extract_placeholders(template)
        if err:
            if _SPACED_PLACEHOLDER_RE.search(template):
                err += " Hint: placeholders use underscores, e.g. {{ First_name }} (not {{ First Name }})."
            errors.append({"type": "invalid_template", "message": f"{label.title()}: {err}"})
            continue

        unknown = variables - allowed_fields
        if unknown:
            errors.append(
                {
                    "type": "unknown_placeholder",
                    "message": (
                        f"Unknown placeholder in {label}: {', '.join(sorted(unknown))}. "
                        f"Available placeholders: {available}"
                    ),
                }
            )
    return errors


def validate_connection(user_id: str, email_connection_id: Optional[str]) -> tuple[Optional[dict], list[dict]]:
    """Check the campaign's sending provider connection.

    Returns (connection, errors). Errors contain "missing Gmail connection"
    when there is no usable connection.
    """
    errors: list[dict] = []

    if not email_connection_id:
        errors.append(
            {
                "type": "missing_connection",
                "message": "No email connection selected for this campaign.",
            }
        )
        return None, errors

    connection = connections.get_connection(email_connection_id)
    if connection is None or connection.get("user_id") != user_id:
        errors.append(
            {
                "type": "missing_connection",
                "message": "The selected email connection was not found for this user.",
            }
        )
        return None, errors

    try:
        provider = get_provider(connection.get("provider", "gmail"))
    except ProviderError as exc:
        errors.append({"type": "missing_connection", "message": str(exc)})
        return None, errors

    result = provider.validate(connection)
    if not result.get("valid"):
        errors.append(
            {
                "type": "missing_connection",
                "message": f"Gmail connection is not usable: {result.get('detail', 'unknown')}",
            }
        )
        return None, errors

    return connection, errors


def validate_campaign(user_id: str, campaign: dict, contact_rows: list) -> dict:
    """Run every pre-send check for a campaign.

    contact_rows: rows as returned by contacts.parse_contacts_file() (or stored
    campaign_contacts records). Returns {"valid": bool, "errors": [...], "summary": {...}}.
    """
    errors: list[dict] = []

    allowed_fields = contacts.merge_rows_placeholder_fields(contact_rows)
    errors.extend(
        validate_templates(
            campaign.get("subject_template", ""),
            campaign.get("body_template", ""),
            allowed_fields,
        )
    )

    if not contact_rows:
        errors.append(
            {"type": "no_contacts", "message": "No contacts uploaded. Upload a CSV/Excel file first."}
        )
    else:
        # Per-contact checks that come straight from parsing.
        for row in contact_rows:
            if row.get("status") == "invalid":
                errors.append(
                    {
                        "type": "invalid_email",
                        "email": row.get("email"),
                        "message": f"{row.get('reason', 'invalid email')}: {row.get('email', '')}",
                    }
                )
            elif row.get("status") == "duplicate":
                errors.append(
                    {
                        "type": "duplicate_email",
                        "email": row.get("email"),
                        "message": f"duplicate email: {row.get('email', '')}",
                    }
                )

    _, connection_errors = validate_connection(user_id, campaign.get("email_connection_id"))
    errors.extend(connection_errors)

    summary = {
        "total": len(contact_rows),
        "valid": sum(1 for r in contact_rows if r.get("status") == "pending"),
        "invalid": sum(1 for r in contact_rows if r.get("status") == "invalid"),
        "duplicates": sum(1 for r in contact_rows if r.get("status") == "duplicate"),
    }

    return {"valid": not errors, "errors": errors, "summary": summary}