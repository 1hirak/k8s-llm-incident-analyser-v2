"""ID and timestamp helpers aligned with the contracts SSOT.

All entity IDs are UUIDv7 strings (time-sortable). All timestamps are
ISO 8601 strings with a ``Z`` suffix (e.g. ``2026-07-21T10:05:33Z``).
"""

from __future__ import annotations

from datetime import datetime, timezone

try:  # uuid-utils >= 0.10 exposes uuid7 at the top level
    from uuid_utils import uuid7 as _uuid7
except ImportError:  # older layouts expose it under compat
    from uuid_utils.compat import uuid7 as _uuid7  # type: ignore[no-redef]


def new_id() -> str:
    """Return a new UUIDv7 string (time-sortable, collision-proof)."""
    return str(_uuid7())


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with a Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
