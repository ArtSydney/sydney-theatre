#!/usr/bin/env python3
"""Rule-based genre classification for theatre productions."""

# Genre keywords - order matters (first match wins for ambiguous cases)
GENRE_RULES = [
    ("musical", [
        "musical", "the musical", "broadway", "west end",
        "hamilton", "wicked", "phantom", "les mis", "chicago",
        "grease", "cats", "matilda", "lion king", "frozen",
        "book of mormon", "dear evan hansen", "six the musical",
        "moulin rouge", "come from away", "hadestown",
    ]),
    ("opera", [
        "opera", "la boheme", "bohème", "tosca", "carmen",
        "madama butterfly", "rigoletto", "aida", "figaro",
        "don giovanni", "magic flute", "traviata",
        "opera australia", "pinchgut",
    ]),
    ("dance", [
        "ballet", "dance", "swan lake", "nutcracker", "giselle",
        "contemporary dance", "choreograph",
        "sydney dance company", "bangarra",
    ]),
    ("cabaret", [
        "cabaret", "burlesque", "variety show", "spiegeltent",
        "late night", "one-woman show", "one-man show",
        "solo show", "comedy cabaret",
    ]),
    ("comedy", [
        "comedy", "stand-up", "standup", "stand up",
        "improv", "sketch", "comedic",
    ]),
    ("family", [
        "family", "children", "kids", "young people",
        "all ages", "school holiday", "pantomime", "panto",
        "atyp",
    ]),
    ("play", [
        "play", "drama", "theatre", "theater", "tragedy",
        "shakespeare", "chekhov", "ibsen", "beckett", "stoppard",
        "new writing", "world premiere", "australian premiere",
        "adaptation", "monologue",
        "sydney theatre company", "belvoir", "griffin",
        "bell shakespeare", "ensemble theatre",
    ]),
]

def classify_production(prod):
    """Classify a production dict by genre. Returns genre string."""
    text = " ".join([
        prod.get("title", ""),
        prod.get("venue", ""),
        prod.get("snippet", ""),
    ]).lower()

    for genre, keywords in GENRE_RULES:
        for kw in keywords:
            if kw in text:
                return genre

    return "unknown"
