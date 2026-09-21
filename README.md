# Sydney Theatre

What's on stage in Sydney. Aggregates theatre productions from multiple sources
into a simple dashboard.

**Live site:** [artsydney.github.io/sydney-theatre](https://artsydney.github.io/sydney-theatre)

## Pipeline

Runs daily at 6am Sydney time via [`.github/workflows/daily.yml`](.github/workflows/daily.yml):

| Step | Module | What it does |
|---|---|---|
| fetch | `fetch.py` | Scrapes TodayTix (JSON-LD) and City of Sydney What's On (embedded Algolia JSON) |
| classify | `classify.py` | Rule-based genre from title, venue and blurb |
| dedup | `dedup.py` | Collapses the same show listed by both sources onto a title-derived key |
| cleanup | `main.py` | Re-applies `filters.py` to records already stored, suppresses non-productions |
| sweep | `main.py` | Closes runs whose last night has passed (Sydney time) |
| notify | `notify.py` | Discord embeds for new shows, openings and closings — once each |
| build | `build_data.py` | Writes `docs/data.json`, `docs/data-current.json`, `docs/theatres.json` |

All date logic goes through `localdate.py`, which works in `Australia/Sydney`.
The runner is on UTC, and at 20:00 UTC it is already tomorrow in Sydney, so
anything keyed off the runner's date is a day out.

## Data

- `seen.json` — pipeline state: every production ever seen, plus the dedup index
  and which notifications have gone out. Committed by the workflow.
- `theatres.json` — hand-curated venue database (id, name, suburb, address).
- `docs/data-current.json` — active shows, what the site loads.
- `docs/data.json` — the full archive, including closed shows.

### Statuses

| Status | Meaning |
|---|---|
| `active` | Running or announced, with dates |
| `needs_review` | Seen, but without both dates — shown as "Unconfirmed" |
| `closed` | Last night has passed. Reopens automatically if a source later advertises a later end date |
| `suppressed` | Not a stage production (a class, workshop or party) — never shown |

## Running locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests   # tests
python main.py                         # full pipeline (hits the live sources)
python build_data.py                   # rebuild docs/ from existing seen.json
```

The frontend is a single static file, `docs/index.html`. To preview it:

```bash
python -m http.server -d docs 8000
```

Set `DISCORD_WEBHOOK_URL` (see `.env.example`) to enable notifications; without
it the notify step is skipped.
