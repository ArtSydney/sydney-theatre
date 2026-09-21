#!/usr/bin/env python3
"""Discord webhook notifications for Sydney Theatre."""

import os

import requests

GENRE_COLORS = {
    "musical": 0xE9C46A,
    "play": 0x249D8F,
    "opera": 0xE76F51,
    "dance": 0xA882C8,
    "comedy": 0xFFC857,
    "cabaret": 0xE8937D,
    "family": 0x5DC4B8,
    "unknown": 0x9A9590,
}

# Discord rejects the whole payload if a field is over length.
TITLE_MAX = 256
DESC_MAX = 2000


def _webhook_url():
    # Read at call time, not import time, so the caller's env always wins.
    return os.environ.get("DISCORD_WEBHOOK_URL", "")


def _safe_url(url):
    """Only http(s) links are valid in a Discord embed."""
    return url if isinstance(url, str) and url.startswith(("http://", "https://")) else ""


def send_embed(embed):
    """Send a Discord embed via webhook. Returns True if it was accepted."""
    url = _webhook_url()
    if not url:
        return False
    try:
        resp = requests.post(
            url,
            json={"embeds": [embed]},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"  [discord] Error: {e}")
        return False


def notify_new(prod):
    """Notify about a newly discovered production."""
    genre = prod.get("genre", "unknown")
    color = GENRE_COLORS.get(genre, 0x9A9590)
    title = prod.get("title") or "Unknown"
    venue = prod.get("venue") or "TBC"

    fields = [{"name": "Venue", "value": venue[:1024], "inline": True}]

    if genre and genre != "unknown":
        fields.append({"name": "Genre", "value": genre.capitalize(), "inline": True})

    dates = format_dates(prod.get("start_date"), prod.get("end_date"))
    if dates:
        fields.append({"name": "Dates", "value": dates, "inline": True})

    if prod.get("price_from") is not None:
        fields.append({"name": "From", "value": format_price(prod["price_from"]), "inline": True})

    embed = {
        "title": f"🎭 New: {title}"[:TITLE_MAX],
        "color": color,
        "fields": fields,
    }

    url = _safe_url(prod.get("booking_url"))
    if url:
        embed["url"] = url

    if prod.get("snippet"):
        embed["description"] = prod["snippet"][:DESC_MAX]

    return send_embed(embed)


def notify_opening_tonight(prod):
    """Notify about a production opening tonight."""
    embed = {
        "title": f"🌟 Opening Tonight: {prod.get('title', '?')}"[:TITLE_MAX],
        "description": f"At {prod.get('venue') or 'TBC'}"[:DESC_MAX],
        "color": 0xE9C46A,
    }
    url = _safe_url(prod.get("booking_url"))
    if url:
        embed["url"] = url
    return send_embed(embed)


def notify_closing_soon(prod):
    """Notify about a production closing today."""
    embed = {
        "title": f"⏳ Closing Today: {prod.get('title', '?')}"[:TITLE_MAX],
        "description": f"Last chance at {prod.get('venue') or 'TBC'}"[:DESC_MAX],
        "color": 0xE76F51,
    }
    url = _safe_url(prod.get("booking_url"))
    if url:
        embed["url"] = url
    return send_embed(embed)


def format_price(price):
    """$70, not $70.0; $94.90, not $94.9."""
    if price is None:
        return ""
    if float(price) == int(float(price)):
        return f"${int(float(price))}"
    return f"${float(price):.2f}"


def format_dates(start, end):
    if not start:
        return ""
    if not end or end == start:
        return start
    return f"{start} to {end}"
