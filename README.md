# Sydney Theatre

What's on stage in Sydney. Aggregates theatre productions from multiple sources, classifies by genre, deduplicates, and publishes to a mobile-first dashboard.

**Live site:** [artsydney.github.io/sydney-theatre](https://artsydney.github.io/sydney-theatre)

## Architecture

Python pipeline (fetch, classify, dedup, build) runs daily via GitHub Actions cron. State persisted in `seen.json`, output to `docs/data.json` consumed by a vanilla HTML/CSS/JS frontend on GitHub Pages.

## Pipeline

```
fetch (Serper + venue sites) -> classify (genre) -> dedup (title+venue key) -> build (JSON) -> notify (Discord)
```

## Status fields

- `active` -- confirmed production with dates
- `needs_review` -- missing end date or thin data
- `suppressed` -- manually hidden
- `closed` -- past end date (auto-swept)

## Local dev

```bash
cp .env.example .env
# Add SERPER_API_KEY and optionally DISCORD_WEBHOOK_URL
python main.py
```

To test without Discord notifications:
```bash
unset DISCORD_WEBHOOK_URL
python main.py
```

## Data

- `theatres.json` -- venue database (name, address, instagram, booking platform, capacity)
- `seen.json` -- pipeline state + dedup index
- `docs/data.json` -- full archive
- `docs/data-current.json` -- active productions only
