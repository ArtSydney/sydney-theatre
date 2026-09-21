#!/usr/bin/env python3
"""Shared "is this actually a stage production?" filtering.

City of Sydney's tag filtering in fetch.py catches most non-shows, but it only
works when the listing is tagged honestly. A dance class tagged only "dance",
or a boat party tagged "music", sails straight through. These title patterns
catch the rest; they are deliberately narrow, and every skip is logged so the
list is easy to tune.
"""

import re

# Each pattern means "not a production" on its own.
NOT_A_PRODUCTION = [
    r"\bworkshops?\b",
    r"\bmaster ?class(es)?\b",
    r"\bclasses\b",
    r"\bclass\s*[:\-]",
    r"\bclass\s+\d",
    r"\bclass\s*\(",
    r"\bclass$",
    r"\bcourse\b",
    r"\blessons?\b",
    r"\bcomedy school\b",
    r"\bschool experience\b",
    r"\bafter[- ]school\b",
    r"\bcorporate training\b",
    r"\bkaraoke\b",
    r"\bsalsa\b",
    r"\btango (class|night|social)\b",
    r"\b(boat|block|brunch|pool|rooftop) party\b",
    r"\bgames night\b",
    r"\bspeed dating\b",
    r"\bsingles \d",
    r"\btrivia\b",
    r"\bopen mic\b",
    # Screenings: not stage productions. City of Sydney's "film"/"cinema" tags
    # catch most of them, but a series tagged only "performance" slips past.
    r"\b(movie|film) club\b",
    r"\bscreenings?\b",
    r"\bdouble feature\b",
]

_COMPILED = [re.compile(p, re.I) for p in NOT_A_PRODUCTION]


def not_a_production(title):
    """Return the matching pattern if the title is not a stage production."""
    if not title:
        return None
    for pattern in _COMPILED:
        if pattern.search(title):
            return pattern.pattern
    return None
