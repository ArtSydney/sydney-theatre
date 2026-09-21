#!/usr/bin/env python3
"""Deduplication for theatre productions using title-based canonical key.

Key is derived from title only (not venue) because the same production
appears under different venue names across sources:
  TodayTix:       "Downstairs Theatre | Belvoir St Theatre"
  City of Sydney: "Belvoir Street Theatre"

Title alone is specific enough to identify a production in Sydney.
"""

import json
import os
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


# ============================================================
# Provenance and adjudication
#
# Merging used to be destructive: two sources became one record and what
# the loser said was gone, so a wrong merge could not be reviewed, undone,
# or explained. Each production now keeps a sighting per source -- the
# evidence a human or an LLM needs to judge a pair.
#
# Judgements live in dedup-overrides.json and always win over the
# heuristics. That is how an LLM contributes without running in the daily
# job: ArtsReviewer adjudicates the candidates this pipeline could not
# call, writes verdicts to that file, and the pipeline applies them
# deterministically the next morning.
# ============================================================

OVERRIDES_FILE = "dedup-overrides.json"
_overrides_cache = None


def load_overrides():
    """{"same": [[keyA, keyB], ...], "different": [[keyA, keyB], ...]}"""
    global _overrides_cache
    if _overrides_cache is None:
        data = {"same": [], "different": []}
        if os.path.exists(OVERRIDES_FILE):
            try:
                with open(OVERRIDES_FILE, encoding="utf-8") as f:
                    loaded = json.load(f)
                for verdict in ("same", "different"):
                    data[verdict] = [tuple(sorted(pair)) for pair in loaded.get(verdict, [])
                                     if isinstance(pair, (list, tuple)) and len(pair) == 2]
            except Exception as e:
                print(f"  [dedup] Could not read {OVERRIDES_FILE}: {e}")
        _overrides_cache = data
    return _overrides_cache


def override_verdict(key_a, key_b):
    """'same', 'different', or None."""
    pair = tuple(sorted((key_a, key_b)))
    ov = load_overrides()
    if pair in ov["different"]:
        return "different"
    if pair in ov["same"]:
        return "same"
    return None


def record_sighting(prod, item):
    """Keep what each source said, so a merge stays reviewable."""
    source = item.get("source") or "unknown"
    sighting = {
        "source": source,
        "title": item.get("title", ""),
        "venue": item.get("venue", ""),
        "start_date": item.get("start_date", ""),
        "end_date": item.get("end_date", ""),
        "url": item.get("source_url") or item.get("booking_url", ""),
    }
    sightings = [s for s in prod.get("sightings", []) if s.get("source") != source]
    sightings.append(sighting)
    prod["sightings"] = sorted(sightings, key=lambda s: s.get("source", ""))
    return prod

# ============================================================
# Second-stage matching
#
# The canonical key is exact: two titles either normalise to the same
# string or they do not. That misses the same show written differently by
# two sources -- TodayTix "Copland Dance Episodes" against City of Sydney
# "The Australian Ballet: Copland Dance Episodes" -- which is how a
# duplicate reaches the site.
#
# Loosening the key itself is not safe. "The Nutcracker" is wholly
# contained in "The Nutcracker on Ice", "The Man" in "The Choir of Man",
# so anything based on containment merges different shows. Instead this
# stage asks for corroboration: titles must be similar AND the two must
# plausibly be the same engagement -- same venue, overlapping dates.
# ============================================================

THEATRES_FILE = "theatres.json"
_parent_cache = None

# Similar titles alone are never enough, and neither are overlapping dates:
# plenty of unrelated shows run the same fortnight. Venue agreement is the
# signal that actually distinguishes a re-listing from a coincidence, so it
# is required for every fuzzy merge.
STRONG_TITLE = 0.70   # same venue
WEAK_TITLE = 0.55     # same venue AND overlapping dates
MIN_TOKENS = 2        # one-word titles are too ambiguous to fuzzy match

# Words that, if they appear on one side of a pair and not the other, mean
# the two listings are deliberately different events rather than two
# spellings of one. A Friday showcase is not a Saturday showcase.
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday", "mon", "tue", "wed", "thu", "fri", "sat", "sun"}
EDITION_WORDS = {"junior", "senior", "matinee", "encore", "relaxed", "auslan",
                 "preview", "opening", "closing", "returns", "return", "revival",
                 "am", "pm", "morning", "afternoon", "evening", "night", "late",
                 "part", "chapter", "volume", "edition", "kids", "adult", "adults"}


def discriminating_difference(title_a, title_b):
    """Do the words that differ mark these out as separate events?"""
    ta, tb = title_tokens(title_a), title_tokens(title_b)
    only_a, only_b = ta - tb, tb - ta
    if not (only_a and only_b):
        # One title is the other plus extra words. Usually a company prefix
        # or a subtitle -- but "Bluey's Big Play Junior" against "Bluey's
        # Big Play" is a separate, differently-cast performance.
        diff = only_a or only_b
        return bool(diff & WEEKDAYS or diff & EDITION_WORDS
                    or any(t.isdigit() for t in diff))
    diff = only_a | only_b
    if diff & WEEKDAYS:
        return True
    if diff & EDITION_WORDS:
        return True
    if any(t.isdigit() for t in diff):
        return True
    return False


def _venue_parents():
    """venue id -> its building, so a room and its building compare equal."""
    global _parent_cache
    if _parent_cache is None:
        _parent_cache = {}
        if os.path.exists(THEATRES_FILE):
            try:
                with open(THEATRES_FILE, encoding="utf-8") as f:
                    for t in json.load(f):
                        _parent_cache[t["id"]] = t.get("parent") or t["id"]
            except Exception:
                pass
    return _parent_cache


def venue_root(venue_id):
    if not venue_id:
        return ""
    parents = _venue_parents()
    seen = set()
    while venue_id in parents and parents[venue_id] != venue_id and venue_id not in seen:
        seen.add(venue_id)
        venue_id = parents[venue_id]
    return venue_id


def title_tokens(title):
    return set(normalize(strip_attribution(title)).split())


def title_similarity(a, b):
    """Jaccard over tokens. Deliberately not containment."""
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def dates_overlap(a, b):
    a1 = (a.get("start_date") or "")[:10]
    a2 = (a.get("end_date") or a.get("start_date") or "")[:10]
    b1 = (b.get("start_date") or "")[:10]
    b2 = (b.get("end_date") or b.get("start_date") or "")[:10]
    if not (a1 and b1 and a2 and b2):
        return False
    return a1 <= b2 and b1 <= a2


def same_venue(a, b):
    ra, rb = venue_root(a.get("venue_id")), venue_root(b.get("venue_id"))
    if ra and rb:
        return ra == rb
    # Fall back to the suburb when neither carries a matched venue.
    sa = (a.get("suburb") or "").strip().lower()
    sb = (b.get("suburb") or "").strip().lower()
    return bool(sa and sa == sb)


def is_same_production(a, b):
    """Corroborated match. Returns (bool, reason)."""
    ta, tb = title_tokens(a.get("title", "")), title_tokens(b.get("title", ""))
    if len(ta) < MIN_TOKENS or len(tb) < MIN_TOKENS:
        return False, "title too short to match loosely"

    sim = title_similarity(a.get("title", ""), b.get("title", ""))
    if sim < WEAK_TITLE:
        return False, f"titles too different ({sim:.2f})"

    if discriminating_difference(a.get("title", ""), b.get("title", "")):
        return False, "titles differ by a word that marks a separate event"

    venue = same_venue(a, b)
    overlap = dates_overlap(a, b)

    # Without venue agreement we do not merge, whatever the titles say.
    if not venue:
        return False, f"different venue (sim {sim:.2f})"

    if sim >= STRONG_TITLE:
        return True, f"similar titles ({sim:.2f}) + same venue"
    if sim >= WEAK_TITLE and overlap:
        return True, f"related titles ({sim:.2f}) + same venue + overlapping dates"
    return False, f"no corroboration (sim {sim:.2f}, venue {venue}, dates {overlap})"


def find_fuzzy_match(item, productions):
    """The existing production this item is probably a re-listing of."""
    best, best_sim, best_reason = None, 0.0, ""
    item_key = canonical_key(item.get("title", ""))
    for pid, prod in productions.items():
        if prod.get("status") == "suppressed":
            continue
        # An adjudicated pair is never re-litigated by the heuristics.
        verdict = override_verdict(item_key, canonical_key(prod.get("title", "")))
        if verdict == "different":
            continue
        if verdict == "same":
            return pid, "adjudicated same in " + OVERRIDES_FILE
        ok, reason = is_same_production(item, prod)
        if not ok:
            continue
        sim = title_similarity(item.get("title", ""), prod.get("title", ""))
        if sim > best_sim:
            best, best_sim, best_reason = pid, sim, reason
    return best, best_reason


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
            record_sighting(productions[pid], item)
            productions[pid]["last_seen"] = today or sydney_today()
            return "existing", pid
        # Index pointed at a production that is no longer in state. Fall
        # through and rebuild the record rather than merging into {}, which
        # used to produce an entry with no id and no title.
        key = pid

    # No exact key hit. Before filing this as new, check whether it is the
    # same show written differently by another source.
    fuzzy_pid, reason = find_fuzzy_match(item, productions)
    if fuzzy_pid:
        print(f"  [dedup] {item.get('title','')!r} -> "
              f"{productions[fuzzy_pid].get('title','')!r} ({reason})")
        productions[fuzzy_pid] = merge_production(productions[fuzzy_pid], item, today=today)
        record_sighting(productions[fuzzy_pid], item)
        productions[fuzzy_pid]["last_seen"] = today or sydney_today()
        # Remember this spelling so the next run hits the fast path.
        dedup_index[key] = fuzzy_pid
        return "existing", fuzzy_pid

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
    record_sighting(productions[pid], item)
    productions[pid]["last_seen"] = today or sydney_today()
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


def dedup_candidates(state, limit=40):
    """Pairs that look related but that the rules would not merge.

    The heuristics are deliberately cautious: a pair that is similar but
    lacks corroboration is left as two records rather than risk collapsing
    two different shows. Those are exactly the pairs worth a second look,
    so they are written out as a work queue for adjudication -- by a person
    or by ArtsReviewer's LLM deduper -- whose verdicts come back through
    dedup-overrides.json.
    """
    live = [p for p in state.get("productions", {}).values()
            if p.get("status") in ("active", "needs_review")]
    out = []
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            ka, kb = canonical_key(a.get("title", "")), canonical_key(b.get("title", ""))
            if override_verdict(ka, kb):
                continue                      # already judged
            merged, _ = is_same_production(a, b)
            if merged:
                continue                      # the rules already handle it
            sim = title_similarity(a.get("title", ""), b.get("title", ""))
            if sim < WEAK_TITLE:
                continue                      # not worth anyone's time
            out.append({
                "similarity": round(sim, 2),
                "same_venue": same_venue(a, b),
                "dates_overlap": dates_overlap(a, b),
                "keys": [ka, kb],
                "a": _candidate_side(a),
                "b": _candidate_side(b),
            })
    out.sort(key=lambda c: -c["similarity"])
    return out[:limit]


def _candidate_side(p):
    return {
        "id": p.get("id"), "title": p.get("title"),
        "venue": p.get("venue"), "venue_id": p.get("venue_id"),
        "suburb": p.get("suburb"),
        "start_date": p.get("start_date"), "end_date": p.get("end_date"),
        "sources": [s.get("source") for s in p.get("sightings", [])] or [p.get("source")],
    }


def consolidate(state, today=None):
    """Merge existing productions that are the same show under two records.

    reindex() collapses records sharing a canonical key. This catches the
    other case: two records with different keys that the corroborated rules
    say are one show, which is how a duplicate that predates a rule
    improvement gets cleaned up instead of sitting there forever.
    """
    today = today or sydney_today()
    productions = state.setdefault("productions", {})
    dedup_index = state.setdefault("__dedup_index__", {})

    items = [p for p in productions.values() if p.get("status") != "suppressed"]
    # Oldest first, so the survivor is the record we have held longest.
    items.sort(key=lambda p: p.get("fetched_at") or "")

    absorbed = {}
    merged = 0
    for i, keeper in enumerate(items):
        if keeper.get("id") in absorbed:
            continue
        for other in items[i + 1:]:
            oid = other.get("id")
            if oid in absorbed or oid == keeper.get("id"):
                continue
            ka = canonical_key(keeper.get("title", ""))
            kb = canonical_key(other.get("title", ""))
            verdict = override_verdict(ka, kb)
            if verdict == "different":
                continue
            if verdict != "same":
                ok, reason = is_same_production(keeper, other)
                if not ok:
                    continue
            else:
                reason = "adjudicated same"
            print(f"  [consolidate] {other.get('title','')!r} -> "
                  f"{keeper.get('title','')!r} ({reason})")
            merge_production(keeper, other, today=today)
            for s_ in other.get("sightings", []) or []:
                record_sighting(keeper, dict(s_, source=s_.get("source"),
                                             source_url=s_.get("url", "")))
            absorbed[oid] = keeper.get("id")
            merged += 1

    if merged:
        for oid, keep_id in absorbed.items():
            productions.pop(oid, None)
        # Repoint every key that referenced an absorbed record.
        for key, pid in list(dedup_index.items()):
            if pid in absorbed:
                dedup_index[key] = absorbed[pid]
        print(f"  [consolidate] Merged {merged} duplicate record(s)")
    return merged
