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
    """
    text = title.strip()

    # Strip trailing " by Author Name" (1-4 capitalized words at end)
    text = re.sub(r"\s+by\s+[A-Z][a-zA-Z\u00e0-\u00ff\-]+(?:\s+[A-Z][a-zA-Z\u00e0-\u00ff\-]+){0,3}\s*$", "", text)

    # Strip leading "Author's " or "Author Name's " (possessive name prefix)
    # Match 1-3 capitalized words followed by 's
    text = re.sub(r"^(?:[A-Z][a-zA-Z\u00e0-\u00ff\-]+\s+){0,2}[A-Z][a-zA-Z\u00e0-\u00ff\-]+[\u2019']s\s+", "", text)

    return text.strip() if len(text.strip()) >= 3 else title.strip()


def normalize(text):
    """Normalize text for matching: lowercase, strip punctuation, remove stop words."""
    text = text.lower().strip()
    # Normalize dashes and special chars
    text = text.replace("\u2013", " ").replace("\u2014", " ").replace("\u2013", " ")
    text = re.sub(r'[^\w\s]', '', text)
    words = [w for w in text.split() if w not in STOP_WORDS]
    return " ".join(sorted(words))


def deduplicate(item, state):
    """
    Check if production already exists in state.
    If new, add to state and return "new".
    If existing, merge any new data and return "existing".
    """
    title = item.get("title", "")

    if not title:
        return "skip"

    key = canonical_key(title)
    dedup_index = state.setdefault("__dedup_index__", {})
    productions = state.setdefault("productions", {})

    if key in dedup_index:
        # Existing: merge data if we have better info
        pid = dedup_index[key]
        existing = productions.get(pid, {})
        merged = merge_production(existing, item)
        productions[pid] = merged
        return "existing"

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
        "sessions": [],
    }
    return "new"


def merge_production(existing, new):
    """Merge new data into existing production, preferring non-empty values."""
    for field in ["end_date", "start_date", "booking_url", "venue_id", "genre",
                   "suburb", "snippet"]:
        if not existing.get(field) and new.get(field):
            existing[field] = new[field]

    # Prefer TodayTix booking URL over City of Sydney event page
    if new.get("source") == "todaytix" and new.get("booking_url"):
        existing["booking_url"] = new["booking_url"]

    # Prefer TodayTix price
    if new.get("price_from") and not existing.get("price_from"):
        existing["price_from"] = new["price_from"]

    # Upgrade from needs_review if we now have dates
    if existing.get("status") == "needs_review":
        if existing.get("start_date") and existing.get("end_date"):
            existing["status"] = "active"

    # Update genre if was unknown
    if existing.get("genre") == "unknown" and new.get("genre") and new["genre"] != "unknown":
        existing["genre"] = new["genre"]

    return existing
