#!/usr/bin/env python3
"""Shared "is this actually a stage production?" filtering.

City of Sydney's tag filtering in fetch.py catches most non-shows, but it only
works when the listing is tagged honestly. A dance class tagged only "dance",
or a boat party tagged "music", sails straight through. These title patterns
catch the rest; they are deliberately narrow, and every skip is logged so the
list is easy to tune.
"""

import re

# City of Sydney files every event under one or more categories, and these
# ones are never a stage production. This is stronger signal than the tags:
# a book club and a dance class are both tagged "arts".
#
# Deliberately NOT in this set: "tours-and-experiences". It is where the
# source files immersive work, and also Disney's The Lion King.
JUNK_CATEGORIES = {
    "talks-courses-and-workshops",
    "exhibitions",
    "sport-and-fitness",
}

# Each pattern means "not a production" on its own.
NOT_A_PRODUCTION = [
    r"\bworkshops?\b",
    r"\bmaster ?class(es)?\b",
    r"\bclasses\b",
    r"\bclass\s*[:\-]",
    r"\bclass\s+\d",
    r"\bclass\s*\(",
    r"\bclass$",
    # "Improv class for beginners". A bare \bclass\b would be wrong -- A
    # Class Act is a musical -- so require a teaching context.
    r"\bclass(es)?\s+for\b",
    r"\bclass(es)?\b.*\bbeginners?\b",
    r"\bbeginners?\b.*\bclass(es)?\b",
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
    # Community-hall regulars. A multi-purpose arts centre's feed carries
    # dance-school recitals and school productions alongside its real
    # season; they are private showcases, not public theatre.
    r"\b(dance|performance|ballet|theatre) studio\b",
    # "Studio 23 2026 Concert" is a recital; Studio 54 The Musical is not,
    # so require the recital context.
    r"\bstudio \d+\b.{0,40}\b(concert|recital|showcase|presentation)\b",
    r"\b(college|grammar|preparatory|academy|high school|public school)\b[^|]{0,40}\bpresents\b",
    r"\beisteddfod\b",
    r"\bspeech night\b",
    r"\bgraduation\b",
    r"\bend of year concert\b",
    r"\b\d+(st|nd|rd|th)\s+annual\s+concert\b",
    r"\bannual\s+(concert|showcase|recital)\b",
    r"\b(movie|film) club\b",
    r"\bscreenings?\b",
    r"\bdouble feature\b",
]

_COMPILED = [re.compile(p, re.I) for p in NOT_A_PRODUCTION]


def not_a_production(title, categories=None):
    """Return a reason string if this is not a stage production, else None.

    Checks the source's own categories first (most reliable), then the title.
    The two catch different things: categories find the book club and the
    artist talks, titles find the dance classes that the source files under
    "theatre-dance-and-film" like everything else.
    """
    junk_cats = JUNK_CATEGORIES & {str(c).lower() for c in (categories or [])}
    if junk_cats:
        return f"category: {sorted(junk_cats)[0]}"

    if not title:
        return None
    for pattern in _COMPILED:
        if pattern.search(title):
            return f"title: {pattern.pattern}"
    return None
