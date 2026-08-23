#!/usr/bin/env python3
"""Build data.json and data-current.json for the frontend."""

import json
import os

DOCS_DIR = "docs"

def build_output(state):
    """Write full archive and active-only data files."""
    productions = state.get("productions", {})

    # Full archive
    all_prods = list(productions.values())
    all_prods.sort(key=lambda p: p.get("start_date", "9999"), reverse=True)

    full_path = os.path.join(DOCS_DIR, "data.json")
    with open(full_path, "w") as f:
        json.dump(all_prods, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(all_prods)} productions to {full_path}")

    # Active + needs_review only (for frontend performance)
    current = [p for p in all_prods if p.get("status") in ("active", "needs_review")]
    current_path = os.path.join(DOCS_DIR, "data-current.json")
    with open(current_path, "w") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(current)} current productions to {current_path}")

if __name__ == "__main__":
    # Standalone build from existing state
    if os.path.exists("seen.json"):
        with open("seen.json", "r") as f:
            state = json.load(f)
        build_output(state)
    else:
        print("No seen.json found")
