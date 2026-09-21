#!/usr/bin/env python3
"""Sydney Theatre pipeline: fetch -> classify -> dedup -> sweep -> build -> notify"""

import json
import os
import tempfile

from fetch import fetch_all
from filters import not_a_production
from classify import classify_production
from dedup import deduplicate
from build_data import build_output
from localdate import sydney_today
from notify import notify_new, notify_opening_tonight, notify_closing_soon

STATE_FILE = "seen.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {}
    state.setdefault("productions", {})
    state.setdefault("__dedup_index__", {})
    state.setdefault("__notified__", {})
    return state


def save_state(state):
    """Write state atomically so an interrupted run cannot truncate seen.json."""
    directory = os.path.dirname(os.path.abspath(STATE_FILE))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".seen-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def cleanup_state(state):
    """Re-apply current filters to records already in state.

    Filters only used to run at fetch time, so anything admitted by an older,
    looser version of them stayed on the site forever.
    """
    suppressed = 0
    regenred = 0
    for pid, prod in state["productions"].items():
        junk = not_a_production(prod.get("title", ""))
        if junk and prod.get("status") != "suppressed":
            prod["status"] = "suppressed"
            prod["suppressed_reason"] = f"not a production ({junk})"
            suppressed += 1
            continue
        # "film" was dropped from the genre map; it has no place in the UI.
        if prod.get("genre") in ("film", "", None):
            prod["genre"] = classify_production(dict(prod, genre="")) or "unknown"
            regenred += 1
    if suppressed:
        print(f"  Suppressed {suppressed} non-productions")
    if regenred:
        print(f"  Reclassified {regenred} productions")


def sweep_deadlines(state, today=None):
    """Auto-close productions past their end date, in Sydney time."""
    today = today or sydney_today()
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


def send_notifications(state, new_pids, closing_soon, today):
    """Send Discord notifications, at most once each.

    The workflow can be re-run by hand on the same day; without these markers
    every manual dispatch re-announced the same shows.
    """
    sent = state.setdefault("__notified__", {})
    productions = state["productions"]

    def once(key, fn, *args):
        if sent.get(key):
            return
        fn(*args)
        sent[key] = today

    for pid in new_pids:
        prod = productions.get(pid)
        if prod and prod.get("status") != "suppressed":
            once(f"new:{pid}", notify_new, prod)

    for pid, prod in productions.items():
        if prod.get("status") == "active" and prod.get("start_date") == today:
            once(f"opening:{pid}:{today}", notify_opening_tonight, prod)

    for prod in closing_soon:
        once(f"closing:{prod['id']}:{today}", notify_closing_soon, prod)


def run():
    print("=== Sydney Theatre Pipeline ===")
    state = load_state()
    today = sydney_today()
    print(f"Sydney date: {today}")

    print("\n[1/6] Fetching productions...")
    raw = fetch_all()
    print(f"  Found {len(raw)} raw results")

    print("\n[2/6] Classifying...")
    for item in raw:
        if not item.get("genre"):
            item["genre"] = classify_production(item)

    print("\n[3/6] Deduplicating...")
    new_pids = []
    for item in raw:
        status, pid = deduplicate(item, state, today=today)
        if status == "new":
            new_pids.append(pid)
    print(f"  {len(new_pids)} new productions")

    print("\n[4/6] Cleaning up state...")
    cleanup_state(state)

    print("\n[5/6] Sweeping deadlines...")
    closing_soon = sweep_deadlines(state, today)

    if os.environ.get("DISCORD_WEBHOOK_URL"):
        print("\n[notify] Sending Discord notifications...")
        send_notifications(state, new_pids, closing_soon, today)
    else:
        print("\n[notify] No DISCORD_WEBHOOK_URL set, skipping")

    # Saved after notifying so the "already announced" markers persist.
    save_state(state)

    print("\n[6/6] Building output...")
    build_output(state)

    print("\nDone.")


if __name__ == "__main__":
    run()
