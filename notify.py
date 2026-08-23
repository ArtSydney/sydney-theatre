#!/usr/bin/env python3
"""Discord webhook notifications for Sydney Theatre."""

import os
import json
import requests
from datetime import date

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

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

def send_embed(embed):
    """Send a Discord embed via webhook."""
    if not WEBHOOK_URL:
        return
    try:
        resp = requests.post(
            WEBHOOK_URL,
            json={"embeds": [embed]},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [discord] Error: {e}")

def notify_new(prod):
    """Notify about a newly discovered production."""
    genre = prod.get("genre", "unknown")
    color = GENRE_COLORS.get(genre, 0x9A9590)
    title = prod.get("title", "Unknown")
    venue = prod.get("venue", "TBC")

    fields = [{"name": "Venue", "value": venue, "inline": True}]

    if genre != "unknown":
        fields.append({"name": "Genre", "value": genre.capitalize(), "inline": True})

    dates = format_dates(prod.get("start_date"), prod.get("end_date"))
    if dates:
        fields.append({"name": "Dates", "value": dates, "inline": True})

    embed = {
        "title": f"🎭 New: {title}",
        "color": color,
        "fields": fields,
    }

    if prod.get("booking_url"):
        embed["url"] = prod["booking_url"]

    if prod.get("snippet"):
        embed["description"] = prod["snippet"][:200]

    send_embed(embed)

def notify_opening_tonight(state):
    """Notify about productions opening tonight."""
    today = date.today().isoformat()
    for pid, prod in state.get("productions", {}).items():
        if prod.get("status") != "active":
            continue
        if prod.get("start_date") == today:
            embed = {
                "title": f"🌟 Opening Tonight: {prod.get('title', '?')}",
                "description": f"At {prod.get('venue', 'TBC')}",
                "color": 0xE9C46A,
            }
            if prod.get("booking_url"):
                embed["url"] = prod["booking_url"]
            send_embed(embed)

def notify_closing_soon(prod):
    """Notify about a production closing today."""
    embed = {
        "title": f"⏳ Closing Today: {prod.get('title', '?')}",
        "description": f"Last chance at {prod.get('venue', 'TBC')}",
        "color": 0xE76F51,
    }
    if prod.get("booking_url"):
        embed["url"] = prod["booking_url"]
    send_embed(embed)

def format_dates(start, end):
    if not start:
        return ""
    if not end:
        return start
    return f"{start} to {end}"
