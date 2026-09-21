#!/usr/bin/env python3
"""Sydney Theatre pipeline: fetch -> classify -> dedup -> sweep -> build -> notify"""

import json
import os
import tempfile
from datetime import date, timedelta

from fetch import fetch_all
from filters import not_a_production
from classify import classify_production
from dedup import deduplicate, reindex
from build_data import build_output
from localdate import sydney_today
from notify import notify_new, notify_opening_tonight, notify_closing_soon

STATE_FILE = "seen.json"

# A normal run fetches ~190 listings. Far below that means a source is
# down, not that Sydney stopped putting on plays.
MIN_HEALTHY_RESULTS = 50


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
        junk = not_a_production(prod.get("title", ""), prod.get("categories"))
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


# A run with no end date is closed once no source has listed it for this
# long. Long enough that a venue reshuffling its site does not bury a real
# show, short enough that a finished season does not linger for months.
STALE_AFTER_DAYS = 21


def sweep_deadlines(state, today=None, close_stale=True):
    """Auto-close finished runs, in Sydney time.

    Two ways a run ends. Most carry an end date and close the day after it
    passes. Some never carry one -- open-ended and recurring listings -- and
    those used to be skipped outright and stayed "active" forever, showing
    up under Tonight and on every future calendar day. They now close once
    no source has listed them for STALE_AFTER_DAYS.
    """
    today = today or sydney_today()
    closing_soon = []
    cutoff = (date.fromisoformat(today) - timedelta(days=STALE_AFTER_DAYS)).isoformat()

    for pid, prod in state["productions"].items():
        if prod.get("status") != "active":
            continue

        end = (prod.get("end_date") or "").strip()
        if not end:
            last_seen = prod.get("last_seen")
            if not last_seen:
                # First run since last_seen existed: start its clock now
                # rather than closing a show we have simply never stamped.
                prod["last_seen"] = today
            elif close_stale and last_seen < cutoff:
                prod["status"] = "closed"
                print(f"  [sweep] Closed (no end date, unlisted since {last_seen}): "
                      f"{prod.get('title', pid)}")
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
    reindex(state, today)
    new_pids = []
    for item in raw:
        status, pid = deduplicate(item, state, today=today)
        if status == "new":
            new_pids.append(pid)
    print(f"  {len(new_pids)} new productions")

    print("\n[4/6] Cleaning up state...")
    cleanup_state(state)

    print("\n[5/6] Sweeping deadlines...")
    # A source outage looks exactly like "nothing is listed any more", so
    # only age shows out when the fetch clearly worked.
    feed_healthy = len(raw) >= MIN_HEALTHY_RESULTS
    if not feed_healthy:
        print(f"  Only {len(raw)} results fetched; skipping the staleness sweep")
    closing_soon = sweep_deadlines(state, today, close_stale=feed_healthy)

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
