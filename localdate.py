#!/usr/bin/env python3
"""Sydney-local dates.

The pipeline runs on a GitHub runner in UTC, but the site is about what is on
stage in Sydney tonight. At the scheduled 20:00 UTC run it is already the next
day in Sydney, so anything keyed off the runner's UTC date is a day behind:
finished shows stayed 'active' and "Opening Tonight" fired for shows that had
opened the day before.
"""

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    SYDNEY = ZoneInfo("Australia/Sydney")
except Exception:  # no tzdata on this host
    SYDNEY = timezone(timedelta(hours=10), "AEST")


def sydney_now():
    return datetime.now(SYDNEY)


def sydney_today():
    """Today's date in Sydney, as an ISO string."""
    return sydney_now().date().isoformat()


def utc_now_iso():
    """Timezone-aware UTC timestamp (datetime.utcnow() is deprecated in 3.12+)."""
    return datetime.now(timezone.utc).isoformat()
