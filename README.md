# Sydney Theatre

What's on stage in Sydney. Aggregates theatre productions from multiple sources into a mobile-first dashboard.

**Live site:** [artsydney.github.io/sydney-theatre](https://artsydney.github.io/sydney-theatre)

## Sources

| Source | Type | Coverage |
|--------|------|----------|
| [TodayTix](https://www.todaytix.com/sydney/category/all-shows) | JSON-LD structured data | Commercial shows (~50) |
| [City of Sydney What's On](https://whatson.cityofsydney.nsw.gov.au/?categories=theatre-dance-and-film) | Algolia JSON embedded in page | Indie, fringe, major venues (~180) |

## Pipeline

Daily cron via GitHub Actions (6am AEST):
