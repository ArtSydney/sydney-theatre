# theatre review -- 2026-09-01 21:37 UTC

`theatres.json` -- **17 proposed changes**

## Summary

| Change | Confidence | Count |
|---|---|---|
| flag_record | high | 9 |
| flag_record | medium | 3 |
| merge | high | 3 |
| set_field | high | 2 |

## Field updates (2)

### high confidence (2)

- **sydney-lyric-theatre.capacity_tier: (empty) -> 'large'**
  - extracted from theatre venue website
  - source: https://www.sydneylyric.com.au/
  - evidence: _four seating configurations: 1350, 1500, 1750 and 2000 seats_
- **the-pavilion-performing-arts-centre.capacity_tier: (empty) -> 'mid'**
  - extracted from theatre venue website
  - source: https://thepavilionarts.au/
  - evidence: _seating for up to 686 patrons_

## Possible duplicates (3)

### high confidence (3)

- **merge drama-theatre into playhouse**
  - Same venue with different name variations
- **merge sydney-opera-house into drama-theatre**
  - Sub-venue listed under parent venue
- **merge sydney-opera-house into playhouse**
  - Sub-venue listed under parent venue

## Flagged for review (12)

### high confidence (9)

- **flag sydney-lyric-theatre: missing required field(s): address, suburb**
- **flag the-pavilion-performing-arts-centre: missing required field(s): address**
- **flag coliseum-theatre: missing required field(s): address**
- **flag foundry-theatre: website is dead (unreachable): https://www.foundrytheatresydney.com.au**
  - source: https://www.foundrytheatresydney.com.au
- **flag kxt: website is dead (unreachable): https://www.kfringe.com**
  - source: https://www.kfringe.com
- **flag old-fitz-theatre: website is dead (HTTP 403): https://www.oldfitztheatre.com**
  - source: https://www.oldfitztheatre.com
- **flag darlinghurst-theatre: website is dead (HTTP 404): https://www.darlinghursttheatre.com**
  - source: https://www.darlinghursttheatre.com
- **flag new-theatre: website is dead (HTTP 404): https://tickets.sydneyfringe.com/Venues/New-Theatre-Touring-Hub**
  - source: https://tickets.sydneyfringe.com/Venues/New-Theatre-Touring-Hub
- **flag eternity-playhouse: website is dead (HTTP 404): https://www.darlinghursttheatre.com**
  - source: https://www.darlinghursttheatre.com

### medium confidence (3)

- **flag atyp: website redirects to https://www.atyp.com.au/**
  - source: https://atyp.com.au
- **flag genesian-theatre: website redirects to https://genesiantheatre.com.au/**
  - source: https://www.genesiantheatre.com.au
- **flag riverside-theatres: website redirects to https://riversideparramatta.com.au/**
  - source: https://www.riversideparramatta.com.au

## Notes

- link check: 29 checked, 6 dead (0 blocked by robots.txt)
- review scanned 29 records
- geocode: 0/1 resolved (0 rejected as outside Sydney, 0 errors)
- enrich: 4 records visited, 2 field values proposed, 1 sites unreachable
- dedup: 5 pairs adjudicated, 3 duplicates proposed
- research: 38 search results, 10 already in the dataset
- research: 0 new theatre venue records proposed
- fetcher: fetched=10, cached=0, blocked=0, failed=0
