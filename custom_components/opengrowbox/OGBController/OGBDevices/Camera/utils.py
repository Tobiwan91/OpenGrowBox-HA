"""
Camera utility functions.

Pure utility functions with no class dependencies.
These functions can be used independently and are easily testable.
"""

import re
from datetime import datetime, timezone
from typing import Optional


def parse_datetime_value(value) -> Optional[datetime]:
    """Parse stored/user datetime values to timezone-aware datetime.

    Supports valid ISO strings and common legacy localized formats.
    Fixes malformed legacy strings like 2026-03-20T12:00:00+00:00Z.

    Args:
        value: Datetime string, datetime object, or None

    Returns:
        Timezone-aware datetime object, or None if parsing fails.
    """
    if not value:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    # Fix malformed legacy strings like: 2026-03-20T12:00:00+00:00Z
    if text.endswith("+00:00Z"):
        text = text[:-1]

    # Primary ISO parser
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    # Legacy localized fallbacks (seen in older frontend states)
    legacy_formats = [
        "%d.%m.%Y, %H:%M",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in legacy_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def to_storage_iso(dt_value) -> str:
    """Serialize datetime to canonical UTC ISO with Z suffix.

    Args:
        dt_value: Datetime object or None

    Returns:
        ISO format string with Z suffix (e.g., "2026-03-21T12:00:00Z")
        or empty string if not a valid datetime.
    """
    if not isinstance(dt_value, datetime):
        return ""

    dt_utc = (
        dt_value.astimezone(timezone.utc)
        if dt_value.tzinfo
        else dt_value.replace(tzinfo=timezone.utc)
    )
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sanitize_filename_part(value, fallback: str = "plant") -> str:
    """Convert free text to filesystem-safe filename part.

    Converts to lowercase, replaces non-alphanumeric chars with underscores,
    removes consecutive underscores, and strips leading/trailing underscores.

    Args:
        value: String to sanitize
        fallback: Default value if result is empty (default: "plant")

    Returns:
        Sanitized filename-safe string
    """
    text = str(value or "").strip().lower()
    if not text:
        return fallback

    # Replace non-alphanumeric chars (except underscore and hyphen) with underscore
    text = re.sub(r"[^a-z0-9_-]+", "_", text)

    # Remove consecutive underscores and strip leading/trailing
    text = re.sub(r"_+", "_", text).strip("_")

    return text or fallback
