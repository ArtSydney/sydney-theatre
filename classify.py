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
        "spamalot", "shrek the musical", "hairspray",
        "how to succeed in business",
    ]),
    ("opera", [
        "la boheme", "bohème", "tosca", "carmen",
        "madama butterfly", "rigoletto", "aida", "figaro",
        "don giovanni", "magic flute", "traviata",
        "opera australia", "pinchgut opera", "semele",
    ]),
    ("dance", [
        "ballet", "swan lake", "nutcracker", "giselle",
        "contemporary dance", "choreograph",
        "sydney dance company", "bangarra",
        "dance episode", "copland dance",
    ]),
    ("cabaret", [
        "cabaret", "kabarett", "burlesque", "variety show", "spiegeltent",
        "late night", "one-woman show", "one-man show",
        "solo show", "comedy cabaret",
        "circus", "all star circus", "club kabarett",
        "velvet inferno", "bernie dieter",
    ]),
    ("comedy", [
        "comedy", "stand-up", "standup", "stand up",
        "improv", "sketch", "comedic", "comedy revue",
    ]),
    ("family", [
        "family", "children", "kids", "young people",
        "all ages", "school holiday", "pantomime", "panto",
        "atyp", "play school", "bluey",
    ]),
    ("play", [
        "play", "drama", "theatre", "theater", "tragedy",
        "shakespeare", "chekhov", "ibsen", "beckett", "stoppard",
        "new writing", "world premiere", "australian premiere",
        "adaptation", "monologue",
        "sydney theatre company", "belvoir", "griffin",
        "bell shakespeare", "ensemble theatre",
        "la ronde", "dangerous when wet",
        "pact centre", "old fitz", "kxt",
        "hayes theatre", "darlinghurst theatre",
    ]),
]


def classify_production(prod):
    """Classify a production dict by genre. Returns genre string.

    Venue is excluded from opera keyword matching to prevent
    'Sydney Opera House' from triggering false opera classification.
    """
    title = prod.get("title", "")
    venue = prod.get("venue", "")
    snippet = prod.get("snippet", "")

    # If the source already assigned a genre, keep it
    existing = prod.get("genre", "")
    if existing and existing != "unknown":
        return existing

    # Title + snippet only (no venue) for opera matching
    text_no_venue = f"{title} {snippet}".lower()
    # Title + venue + snippet for everything else
    text_full = f"{title} {venue} {snippet}".lower()

    for genre, keywords in GENRE_RULES:
        # Use text without venue for opera to avoid "Opera House" false match
        search_text = text_no_venue if genre == "opera" else text_full
        for kw in keywords:
            if kw in search_text:
                return genre

    return "unknown"
