#!/usr/bin/env python3
"""Deduplication for theatre productions using title-based canonical key.

Key is derived from title only (not venue) because the same production
appears under different venue names across sources:
  TodayTix:       "Downstairs Theatre | Belvoir St Theatre"
  City of Sydney: "Belvoir Street Theatre"

Title alone is specific enough to identify a production in Sydney.
"""

import re
import hashlib

from localdate import sydney_today

# Bump whenever canonical_key's behaviour changes, so reindex() knows the
# stored ids were produced by an older rule.
KEY_VERSION = 2

# Which source's booking link to trust when several offer one.
SOURCE_RANK = {"": 0, "cityofsydney": 1, "todaytix": 2, "venue-feed": 3}

# Common words to ignore in title matching
STOP_WORDS = {
    "the", "a", "an", "of", "in", "at", "on", "and", "or", "to",
    "for", "by", "with", "from", "is", "are", "was", "were",
}


def canonical_key(title):
    """Generate a canonical dedup key from title only."""
    title_clean = normalize(strip_attribution(title))
    return hashlib.md5(title_clean.encode()).hexdigest()[:12]


def strip_attribution(title):
    """Strip playwright/author attribution from title.

    City of Sydney often adds these patterns that TodayTix doesn't:
      "David Williamson's Top Silk"  -> "Top Silk"
      "The Boys Are Kissing by Zak Zarafshan" -> "The Boys Are Kissing"
      "Noël Coward's Private Lives"  -> "Private Lives"
      "Pinchgut Opera presents Coffee..." -> "Coffee..."
    """
    text = title.strip()

    # Strip leading "Company Name presents ". Requires at least two
    # capitalized words before "presents" so titles that merely contain the
    # word ("Christmas Presents for All") are left alone.
    text = re.sub(
        r"^(?:[A-Z][\w\u2019'-]*\s+){1,3}[A-Z][\w\u2019'-]*\s+presents?\s+",
        "", text,
    )

    # Strip trailing " by Author Name" (1-4 capitalized words at end)
    text = re.sub(r"\s+by\s+[A-Z][a-zA-Z\u00e0-\u00ff\-]+(?:\s+[A-Z][a-zA-Z\u00e0-\u00ff\-]+){0,3}\s*$", "", text)

    # Strip leading "Author's " or "Author Name's " (possessive name prefix)
    # Match 1-3 capitalized words followed by 's
    text = re.sub(r"^(?:[A-Z][a-zA-Z\u00e0-\u00ff\-]+\s+){0,2}[A-Z][a-zA-Z\u00e0-\u00ff\-]+[\u2019']s\s+", "", text)

    return text.strip() if len(text.strip()) >= 3 else title.strip()


def normalize(text):
    """Normalize text for matching: lowercase, strip punctuation, remove stop words."""
    text = text.lower().strip()
    # Punctuation becomes a space, not nothing: dropping it outright made
    # "All-Star Circus" normalize to "allstar circus" and never match the
    # same show listed elsewhere as "All Star Circus".
    text = re.sub(r"[^\w\s]+", " ", text)
    words = [w for w in text.split() if w not in STOP_WORDS]
    return " ".join(sorted(words))


def reindex(state, today=None):
    """Rebuild __dedup_index__ from the productions, collapsing collisions.

    A production's id *is* its canonical key, so improving canonical_key
    changes it. The stored ids then no longer match what the next fetch
    computes, the same show is filed again under a new id, and the site
    lists it twice. (Spacing punctuation instead of deleting it did exactly
    this to 13 shows.) Rebuilding from the productions themselves makes a
    rule change self-healing instead of a data migration.
    """
    today = today or sydney_today()
    productions = state.setdefault("productions", {})

    groups = {}
    for prod in productions.values():
        groups.setdefault(canonical_key(prod.get("title", "")), []).append(prod)

    rebuilt = {}
    merged = 0
    for key, group in groups.items():
        # Oldest first: merge_production treats its second argument as the
        # newer, more authoritative record.
        group.sort(key=lambda p: p.get("fetched_at") or "")
        base = group[0]
        was_suppressed = any(p.get("status") == "suppressed" for p in group)
        for other in group[1:]:
            merge_production(base, other, today=today)
            merged += 1
        if was_suppressed:
            base["status"] = "suppressed"
        base["id"] = key
        rebuilt[key] = base

    if merged:
        print(f"  [reindex] Merged {merged} duplicate record(s) after a key change")

    state["productions"] = rebuilt
    state["__dedup_index__"] = {key: key for key in rebuilt}
    state["__key_version__"] = KEY_VERSION
    return merged


def deduplicate(item, state, today=None):
    """Merge an incoming item into state.

    Returns (status, pid) where status is "new", "existing" or "skip".
    """
    title = item.get("title", "")

    if not title:
        return "skip", None

    key = canonical_key(title)
    dedup_index = state.setdefault("__dedup_index__", {})
    productions = state.setdefault("productions", {})

    if key in dedup_index:
        pid = dedup_index[key]
        existing = productions.get(pid)
        if existing:
            # Existing: merge data if we have better info
            productions[pid] = merge_production(existing, item, today=today)
            return "existing", pid
        # Index pointed at a production that is no longer in state. Fall
        # through and rebuild the record rather than merging into {}, which
        # used to produce an entry with no id and no title.
        key = pid

    # New production
    pid = key
    dedup_index[key] = pid
    productions[pid] = {
        "id": pid,
        "title": title,
        "venue": item.get("venue", ""),
        "venue_id": item.get("venue_id", ""),
        "genre": item.get("genre", "unknown"),
        "status": item.get("status", "needs_review"),
        "start_date": item.get("start_date", ""),
        "end_date": item.get("end_date", ""),
        "booking_url": item.get("booking_url", ""),
        "source": item.get("source", ""),
        "source_url": item.get("source_url", ""),
        "snippet": item.get("snippet", ""),
        "suburb": item.get("suburb", ""),
        "free_event": item.get("free_event", False),
        "price_from": item.get("price_from", None),
        "fetched_at": item.get("fetched_at", ""),
        # Kept so cleanup_state can re-apply filters to stored records.
        "categories": item.get("categories", []),
        "sessions": [],
    }
    _refresh_status(productions[pid], today or sydney_today())
    return "new", pid


def merge_production(existing, new, today=None):
    """Merge new source data into an existing production.

    Fields that sources genuinely revise (dates, venue, price, booking link)
    are refreshed from the incoming record; fields we may have curated by hand
    are only filled when empty.
    """
    today = today or sydney_today()

    # Fill-if-empty only: never overwrite something we already know.
    for field in ["venue_id", "suburb", "snippet", "source", "source_url"]:
        if not existing.get(field) and new.get(field):
            existing[field] = new[field]

    # Refresh-if-present: a source that re-lists a show is the authority on
    # when it now runs. The old fill-if-empty behaviour meant an extended or
    # rescheduled run was silently ignored forever.
    for field in ["start_date", "end_date", "venue", "fetched_at", "categories"]:
        if new.get(field) and new[field] != existing.get(field):
            existing[field] = new[field]

    # Best available booking link. The venue's own box office beats a
    # reseller, which beats an aggregator's event page.
    if new.get("booking_url"):
        if SOURCE_RANK.get(new.get("source"), 0) >= SOURCE_RANK.get(existing.get("booking_source"), 0):
            existing["booking_url"] = new["booking_url"]
            existing["booking_source"] = new.get("source", "")

    # Prefer the lowest advertised price we have seen
    new_price = new.get("price_from")
    if new_price is not None:
        old_price = existing.get("price_from")
        if old_price is None or new_price < old_price:
            existing["price_from"] = new_price

    if new.get("free_event"):
        existing["free_event"] = True

    # Update genre if it was unknown
    if existing.get("genre") in ("", "unknown", None) and new.get("genre") not in ("", "unknown", None):
        existing["genre"] = new["genre"]

    _refresh_status(existing, today)
    return existing


def _refresh_status(prod, today):
    """Re-derive status from the dates we now hold.

    Runs in both directions: needs_review becomes active once dates arrive,
    and a closed show whose source now advertises a future end date is
    reopened (extensions, return seasons, and dates we had simply got wrong
    used to stay closed permanently).
    """
    status = prod.get("status")
    if status == "suppressed":
        return  # a manual suppression always wins

    start = prod.get("start_date") or ""
    end = prod.get("end_date") or ""

    if status == "needs_review" and start and end:
        prod["status"] = "active"
        status = "active"

    if status == "closed" and end and end >= today:
        prod["status"] = "active"
        print(f"  [reopen] {prod.get('title', prod.get('id'))} now runs to {end}")
    elif status == "active" and end and end < today:
        prod["status"] = "closed"
