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

### Deduplication

The same production reaches us from several sources under different names —
TodayTix files *Copland Dance Episodes* under the room, City of Sydney files
*The Australian Ballet: Copland Dance Episodes* under the building. Matching
runs in three stages, each more cautious than the last:

1. **Canonical key** — titles normalised (punctuation spaced, stop words and
   author/company attribution stripped) and hashed. Exact, cheap, handles most
   re-listings.
2. **Corroborated match** — for titles that don't normalise identically,
   Jaccard similarity over tokens *plus* venue agreement. Overlapping dates
   alone are never enough; plenty of unrelated shows run the same fortnight.
   Containment is never used: *The Man* is inside *The Choir of Man*.
   A word that marks a separate event (a weekday, a number, "junior") blocks
   the merge outright.
3. **Adjudication** — `dedup-overrides.json` pins pairs as `same` or
   `different` and always beats the rules. Pairs the rules decline to call are
   written to `dedup-candidates.json` as a work queue.

   That queue is worked by `tools/adjudicate_dedup.py` in the ArtsReviewer
   repo, which asks a local model about each pair and records only confident
   verdicts; anything thinner stays in the queue for a person. **No model runs
   in the daily job** — it applies verdicts already recorded. The prompt's bias
   matches the pipeline's: when evidence is thin, answer *different*, because a
   missed duplicate shows one extra row while a wrong merge deletes a real show.

Venue rooms resolve to their building via `parent` in `theatres.json`, so the
Drama Theatre and the Opera House compare equal.

A touring production keeps its title from venue to venue, so every merge path
also checks it is the same *engagement*: Bell Shakespeare's *Macbeth* plays the
Opera House in November and the Pavilion in September, and those are two
listings, not one. Where neither side matched a venue record, the venue wording
is compared with generic words ("the", "theatre", "sydney") removed.

Every production keeps a `sightings` entry per source — what each one called
it, and where. Merging is no longer destructive, so a wrong merge can be seen
and reversed.

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
