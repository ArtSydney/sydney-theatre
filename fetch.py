#!/usr/bin/env python3
"""Fetch Sydney theatre productions from multiple sources.

Sources:
  1. TodayTix  - JSON-LD structured data (commercial shows)
  2. City of Sydney What's On - Algolia JSON embedded in page (indie + fringe + major)
"""

import json
import os
import re
import html
import requests
from datetime import datetime

THEATRES_FILE = "theatres.json"
TODAYTIX_URL = "https://www.todaytix.com/sydney/category/all-shows"
CITYOFSYDNEY_URL = "https://whatson.cityofsydney.nsw.gov.au/?categories=theatre-dance-and-film"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

_theatres_cache = None


def load_theatres():
    global _theatres_cache
    if _theatres_cache is None:
        with open(THEATRES_FILE, "r") as f:
            _theatres_cache = json.load(f)
    return _theatres_cache


def fetch_all():
    """Run all fetch sources, return list of raw production dicts."""
    results = []
    results.extend(fetch_todaytix())
    results.extend(fetch_cityofsydney())
    return results


# ============================================================
# TodayTix: commercial shows via JSON-LD structured data
# ============================================================

def fetch_todaytix():
    """Fetch all shows from TodayTix Sydney via embedded JSON-LD."""
    print("  [todaytix] Fetching...")
    try:
        resp = requests.get(
            TODAYTIX_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=30
        )
        resp.raise_for_status()
        page = resp.text
    except Exception as e:
        print(f"  [todaytix] Failed to fetch: {e}")
        return []

    # Extract JSON-LD blocks
    events = []
    pattern = r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>'
    matches = re.findall(pattern, page, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue

        if isinstance(data, list):
            for item in data:
                if item.get("@type") == "TheaterEvent":
                    events.append(item)
        elif isinstance(data, dict):
            if data.get("@type") == "TheaterEvent":
                events.append(data)

    results = []
    for event in events:
        prod = parse_todaytix_event(event)
        if prod:
            results.append(prod)

    print(f"  [todaytix] {len(results)} productions")
    return results


def parse_todaytix_event(event):
    """Parse a TodayTix TheaterEvent JSON-LD object into a production dict."""
    name = html.unescape(event.get("name", "")).strip()
    if not name or len(name) < 2:
        return None

    skip_names = ["todaytix digital gift cards", "gift card"]
    if name.lower() in skip_names:
        return None

    venue_name = ""
    location = event.get("location", {})
    if isinstance(location, dict):
        venue_name = html.unescape(location.get("name", "")).strip()

    start_date = event.get("startDate", "")
    end_date = event.get("endDate", "")

    booking_url = event.get("url", "")
    offers = event.get("offers", {})
    if isinstance(offers, dict) and offers.get("url"):
        booking_url = offers["url"]

    price = None
    if isinstance(offers, dict):
        price = offers.get("price")

    venue_id = match_venue_id(venue_name)
    status = "active" if start_date else "needs_review"

    return {
        "title": name,
        "venue": venue_name,
        "venue_id": venue_id,
        "genre": "",
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "booking_url": booking_url,
        "price_from": price,
        "source": "todaytix",
        "source_url": booking_url,
        "snippet": "",
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ============================================================
# City of Sydney What's On: indie, fringe, and major shows
# Algolia search results embedded as JSON in the HTML page
# ============================================================

# Map City of Sydney venue slugs to our theatres.json IDs
COS_VENUE_MAP = {
    "sydney-opera-house": "sydney-opera-house",
    "the-old-fitzroy-theatre": "old-fitz-theatre",
    "ensemble-theatre": "ensemble-theatre",
    "hayes-theatre-co": "hayes-theatre",
    "flight-path-theatre": "flight-path-theatre",
    "belvoir-street-theatre": "belvoir-st-theatre",
    "seymour-centre": "seymour-centre",
    "the-concourse": "the-concourse",
    "carriageworks": "carriageworks",
    "the-factory-theatre": "factory-theatre",
    "kxt-on-broadway": "kxt-on-broadway",
    "eternity-playhouse": "eternity-playhouse",
    "qtopia-sydney": "qtopia-sydney",
    "theatre-royal-sydney": "theatre-royal-sydney",
    "sydney-lyric-theatre": "capitol-theatre",
    "state-theatre": "state-theatre",
    "city-recital-hall": "city-recital-hall",
    "icc-sydney": "icc-sydney",
    "the-star": "the-star",
    "riverside-theatres": "riverside-parramatta",
    "the-entertainment-quarter": "entertainment-quarter",
    "hayden-orpheum-picture-palace": "hayden-orpheum",
    "civic-underground": "civic-underground",
    "oxford-art-factory": "oxford-art-factory",
    "the-beresford-hotel": "beresford-hotel",
    "marrickville-town-hall": "marrickville-town-hall",
    "erskineville-town-hall": "erskineville-town-hall",
    "state-library-of-nsw": "state-library-nsw",
    "castlereagh-boutique-hotel": "castlereagh-hotel",
    "polish-club-ashfield": "polish-club-ashfield",
    "vaucluse-house": "vaucluse-house",
}

# Tags that map to our genre system
COS_TAG_GENRE_MAP = {
    "musical": "musical",
    "opera": "opera",
    "dance": "dance",
    "comedy": "comedy",
    "cabaret": "cabaret",
    "theatre": "play",
    "acting": "play",
    "performance": "play",
    "film": "film",
    "cinema": "film",
    "children": "family",
    "family": "family",
}


def fetch_cityofsydney():
    """Fetch theatre events from City of Sydney What's On via embedded Algolia JSON."""
    print("  [cityofsydney] Fetching...")
    try:
        resp = requests.get(
            CITYOFSYDNEY_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=30
        )
        resp.raise_for_status()
        page = resp.text
    except Exception as e:
        print(f"  [cityofsydney] Failed to fetch: {e}")
        return []

    hits = extract_algolia_hits(page)
    if not hits:
        print("  [cityofsydney] No Algolia hits found in page")
        return []

    results = []
    skipped = 0
    for hit in hits:
        prod = parse_cos_event(hit)
        if prod:
            results.append(prod)
        else:
            skipped += 1

    print(f"  [cityofsydney] {len(results)} productions ({skipped} skipped)")
    return results


def extract_algolia_hits(page_html):
    """Extract the Algolia hits array from the page HTML."""
    # The JSON blob is embedded after "hits": in the page source
    pattern = r'"hits"\s*:\s*(\[.*?\])\s*,\s*"nbHits"\s*:\s*(\d+)'
    m = re.search(pattern, page_html, re.DOTALL)
    if not m:
        return _extract_hits_fallback(page_html)

    try:
        hits = json.loads(m.group(1))
        expected = int(m.group(2))
        print(f"  [cityofsydney] Parsed {len(hits)} hits (expected {expected})")
        return hits
    except json.JSONDecodeError as e:
        print(f"  [cityofsydney] JSON parse error: {e}")
        return _extract_hits_fallback(page_html)


def _extract_hits_fallback(page_html):
    """Fallback: extract individual event JSON objects by objectID pattern."""
    hits = []
    pattern = r'\{"slug":"[^"]+","name":"[^"]+".*?"objectID":"[^"]+"[^}]*\}'
    matches = re.finditer(pattern, page_html)
    for m in matches:
        try:
            obj = json.loads(m.group())
            if obj.get("objectID") and obj.get("name"):
                hits.append(obj)
        except json.JSONDecodeError:
            continue
    print(f"  [cityofsydney] Fallback extracted {len(hits)} hits")
    return hits


def parse_cos_event(hit):
    """Parse a City of Sydney Algolia hit into a production dict."""
    name = hit.get("name", "").strip()
    if not name or len(name) < 2:
        return None

    slug = hit.get("slug", "")
    strapline = hit.get("strapline", "")
    dates = hit.get("dates", [])
    venue_slug_list = hit.get("venues", [])
    venue_name_raw = hit.get("venueName", "")
    tags = hit.get("tags", [])
    suburb = hit.get("suburbName", "")
    free_event = hit.get("freeEvent", "false")

    # Build event URL
    event_url = f"https://whatson.cityofsydney.nsw.gov.au/events/{slug}" if slug else ""

    # Derive start/end dates from the dates array
    start_date = ""
    end_date = ""
    if dates:
        sorted_dates = sorted(dates)
        start_date = sorted_dates[0]
        end_date = sorted_dates[-1]

    # Match venue to our database
    venue_id = ""
    venue_name = venue_name_raw

    # Try slug-based matching first
    if venue_slug_list:
        venue_slug = venue_slug_list[0]
        venue_id = COS_VENUE_MAP.get(venue_slug, "")

    # If slug match failed, try name-based matching
    if not venue_id and venue_name:
        venue_id = match_venue_id(venue_name)

    # Derive genre from tags
    genre = _genre_from_tags(tags, name)

    # Skip items that are clearly not shows (classes, workshops, courses)
    name_lower = name.lower()
    skip_keywords = [
        "acting class", "vocal training", "crash course",
        "screenwriting fundamentals", "ballet classes",
        "dance class", "workshop:",
    ]
    if any(kw in name_lower for kw in skip_keywords):
        return None

    status = "active" if start_date else "needs_review"

    return {
        "title": name,
        "venue": venue_name,
        "venue_id": venue_id,
        "genre": genre,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "booking_url": event_url,
        "source": "cityofsydney",
        "source_url": event_url,
        "snippet": strapline[:300] if strapline else "",
        "suburb": suburb,
        "free_event": free_event == "true",
        "fetched_at": datetime.utcnow().isoformat(),
    }


def _genre_from_tags(tags, name):
    """Derive genre from City of Sydney tags + name patterns."""
    genre = ""
    for tag in tags:
        mapped = COS_TAG_GENRE_MAP.get(tag.lower(), "")
        if mapped:
            # Prefer specific genres over generic "play"
            if mapped != "play" or not genre:
                genre = mapped

    # Override based on name patterns (musicals often tagged as just "theatre")
    name_lower = name.lower()
    if any(kw in name_lower for kw in ["musical", "the musical", "spamalot"]):
        genre = "musical"
    elif "opera" in name_lower:
        genre = "opera"
    elif any(kw in name_lower for kw in ["ballet", "dance episode"]):
        genre = "dance"

    return genre


# ============================================================
# Shared venue matching
# ============================================================

# TodayTix venue name aliases to theatres.json IDs
VENUE_ALIASES = {
    "the playhouse | sydney opera house": "playhouse",
    "playhouse | sydney opera house": "playhouse",
    "drama theatre | sydney opera house": "drama-theatre",
    "joan sutherland theatre | sydney opera house": "joan-sutherland-theatre",
    "studio | sydney opera house": "studio-soh",
    "wharf 1 theatre": "roslyn-packer-theatre",
    "wharf 2 theatre": "roslyn-packer-theatre",
    "roslyn packer theatre": "roslyn-packer-theatre",
    "sydney opera house": "sydney-opera-house",
    "capitol theatre": "capitol-theatre",
    "theatre royal sydney": "theatre-royal-sydney",
    "hayes theatre co": "hayes-theatre",
    "hayes theatre": "hayes-theatre",
    "ensemble theatre": "ensemble-theatre",
    "belvoir st theatre": "belvoir-st-theatre",
    "belvoir street theatre": "belvoir-st-theatre",
    "seymour centre": "seymour-centre",
    "the concourse": "the-concourse",
    "concourse chatswood": "the-concourse",
    "carriageworks": "carriageworks",
    "the old fitzroy theatre": "old-fitz-theatre",
    "old fitz theatre": "old-fitz-theatre",
    "kxt on broadway": "kxt-on-broadway",
    "eternity playhouse": "eternity-playhouse",
    "darlinghurst theatre": "darlinghurst-theatre",
    "genesian theatre": "genesian-theatre",
    "glen street theatre": "glen-street-theatre",
    "riverside theatres": "riverside-parramatta",
    "riverside parramatta": "riverside-parramatta",
    "the factory theatre": "factory-theatre",
    "factory theatre": "factory-theatre",
    "flight path theatre": "flight-path-theatre",
    "foundry theatre": "foundry-theatre",
    "nida theatres": "nida",
    "sydney theatre company": "roslyn-packer-theatre",
    "state theatre": "state-theatre",
    "the star": "the-star",
    "icc sydney": "icc-sydney",
    "city recital hall": "city-recital-hall",
}


def match_venue_id(venue_name):
    """Match a venue name to our theatres.json database."""
    if not venue_name:
        return ""

    venue_lower = venue_name.lower().strip()

    # Check aliases first (exact match)
    if venue_lower in VENUE_ALIASES:
        return VENUE_ALIASES[venue_lower]

    # Check theatres.json
    theatres = load_theatres()
    for t in theatres:
        tname = t["name"].lower()
        if tname in venue_lower or venue_lower in tname:
            return t["id"]
        # Partial word match
        t_words = [w for w in tname.split() if len(w) > 2]
        v_words = [w for w in venue_lower.split() if len(w) > 2]
        if len(t_words) >= 2 and t_words[0] in v_words and t_words[1] in v_words:
            return t["id"]

    return ""
