#!/usr/bin/env python3
"""Sydney Theatre pipeline: fetch -> classify -> dedup -> build -> notify"""

import json
import os
import sys
from datetime import date

from fetch import fetch_all
from classify import classify_production
from dedup import deduplicate
from build_data import build_output
from notify import notify_new, notify_opening_tonight, notify_closing_soon

STATE_FILE = "seen.json"

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"productions": {}, "__dedup_index__": {}}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def sweep_deadlines(state):
    """Auto-close productions past their end date."""
    today = date.today().isoformat()
    closing_soon = []
    for pid, prod in state["productions"].items():
        if prod.get("status") != "active":
            continue
        end = prod.get("end_date", "")
        if not end:
            continue
        if end < today:
            prod["status"] = "closed"
            print(f"  [sweep] Closed: {prod.get('title', pid)}")
        elif end == today:
            closing_soon.append(prod)
    return closing_soon

def run():
    print("=== Sydney Theatre Pipeline ===")
    state = load_state()

    # 1. Fetch
    print("\n[1/5] Fetching productions...")
    raw = fetch_all()
    print(f"  Found {len(raw)} raw results")

    # 2. Classify
    print("\n[2/5] Classifying...")
    for item in raw:
        if not item.get("genre"):
            item["genre"] = classify_production(item)

    # 3. Dedup and merge into state
    print("\n[3/5] Deduplicating...")
    new_productions = []
    for item in raw:
        result = deduplicate(item, state)
        if result == "new":
            new_productions.append(item)

    print(f"  {len(new_productions)} new productions")

    # 4. Sweep deadlines
    print("\n[4/5] Sweeping deadlines...")
    closing_soon = sweep_deadlines(state)

    # 5. Save state
    save_state(state)

    # 6. Build output
    print("\n[5/5] Building output...")
    build_output(state)

    # 7. Notify
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        print("\n[notify] Sending Discord notifications...")
        for prod in new_productions:
            notify_new(prod)
        notify_opening_tonight(state)
        for prod in closing_soon:
            notify_closing_soon(prod)
    else:
        print("\n[notify] No DISCORD_WEBHOOK_URL set, skipping")

    print("\nDone.")

if __name__ == "__main__":
    run()
