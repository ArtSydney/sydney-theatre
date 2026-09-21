#!/usr/bin/env python3
"""Build data.json and data-current.json for the frontend."""

import json
import os
import shutil

DOCS_DIR = "docs"
THEATRES_FILE = "theatres.json"

# Fields the frontend reads. Anything else in state (internal bookkeeping,
# suppression reasons, raw snippets we no longer use) stays out of the
# published JSON.
PUBLIC_FIELDS = [
    "id", "title", "venue", "venue_id", "suburb", "genre", "status",
    "start_date", "end_date", "booking_url", "price_from", "free_event",
    "source", "snippet",
]


def load_theatres():
    if os.path.exists(THEATRES_FILE):
        with open(THEATRES_FILE, "r", encoding="utf-8") as f:
            return {t["id"]: t for t in json.load(f)}
    return {}


def safe_url(url):
    """Drop anything that is not an http(s) link.

    booking_url comes from scraped third-party pages and ends up in an href,
    so a javascript: or data: URL must never reach the page.
    """
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return url
    return ""


def enrich(prod, theatres):
    """Project a state record onto the fields the frontend needs."""
    out = {f: prod.get(f) for f in PUBLIC_FIELDS}

    # Fill suburb from theatres.json if we have a venue_id match
    if not out.get("suburb") and out.get("venue_id"):
        theatre = theatres.get(out["venue_id"])
        if theatre:
            out["suburb"] = theatre.get("suburb", "")

    out["suburb"] = out.get("suburb") or ""
    out["venue"] = out.get("venue") or ""
    out["genre"] = out.get("genre") or "unknown"
    out["free_event"] = bool(out.get("free_event"))
    out["source"] = out.get("source") or ""
    out["booking_url"] = safe_url(out.get("booking_url"))
    return out


def publish_theatres():
    """Copy theatres.json into docs/ so the deployed frontend can fetch it.

    docs/ is what GitHub Pages actually serves as the site root; the daily
    workflow never copied the repo-root theatres.json in, so the frontend's
    fetch for venue data (suburb, address, lat/lng) was 404ing in production.
    """
    if not os.path.exists(THEATRES_FILE):
        print(f"  Warning: {THEATRES_FILE} not found, skipping publish")
        return
    dest = os.path.join(DOCS_DIR, "theatres.json")
    shutil.copyfile(THEATRES_FILE, dest)
    print(f"  Published {THEATRES_FILE} to {dest}")


def build_output(state):
    """Write full archive and active-only data files."""
    productions = state.get("productions", {})
    theatres = load_theatres()
    os.makedirs(DOCS_DIR, exist_ok=True)
    publish_theatres()

    # Full archive
    all_prods = [enrich(p, theatres) for p in productions.values()]
    all_prods.sort(key=lambda p: p.get("start_date", "9999"), reverse=True)

    full_path = os.path.join(DOCS_DIR, "data.json")
    with open(full_path, "w", encoding="utf-8") as f:
        json.dump(all_prods, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(all_prods)} productions to {full_path}")

    # Active + needs_review only (for frontend performance)
    current = [p for p in all_prods if p.get("status") in ("active", "needs_review")]
    current_path = os.path.join(DOCS_DIR, "data-current.json")
    with open(current_path, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(current)} current productions to {current_path}")


if __name__ == "__main__":
    # Standalone build from existing state
    if os.path.exists("seen.json"):
        with open("seen.json", "r", encoding="utf-8") as f:
            state = json.load(f)
        build_output(state)
    else:
        print("No seen.json found")
