"""Discover each venue's ticketing platform, and where that platform has a
public listings API, the client id needed to call it.

The venue homepage almost never names its ticketing platform -- Old Fitz's
does not mention Spektrix anywhere. The platform only shows up once you
follow a Book/Buy link to the box-office host, so that is what this does.
"""
import json, pathlib, re, sys, time
from urllib.parse import urlparse, urljoin
import httpx

UA = "ArtSydneyBot/1.0 (+https://github.com/ArtSydney; daily arts listing data quality check)"
TIMEOUT = 20

# Hosts that look like a box office rather than a CDN or a social link.
TICKET_HOST = re.compile(
    r"(ticket|purchase|boxoffice|box-office|booking|seats?|spektrix|trybooking"
    r"|humanitix|eventbrite|premier|moshtix|oztix|sales|shop)", re.I)

SOCIAL = re.compile(r"(facebook|instagram|twitter|x\.com|youtube|tiktok|linkedin|google|gstatic|cloudflare|googletagmanager)", re.I)

PLATFORMS = [
    ("spektrix",     re.compile(r"spektrix", re.I)),
    ("trybooking",   re.compile(r"trybooking", re.I)),
    ("humanitix",    re.compile(r"humanitix", re.I)),
    ("eventbrite",   re.compile(r"eventbrite", re.I)),
    ("ticketek",     re.compile(r"ticketek", re.I)),
    ("ticketmaster", re.compile(r"ticketmaster", re.I)),
    ("moshtix",      re.compile(r"moshtix", re.I)),
    ("oztix",        re.compile(r"oztix", re.I)),
    ("ticketsearch", re.compile(r"ticketsearch", re.I)),
    ("tessitura",    re.compile(r"tessitura|tnew", re.I)),
    ("savoy",        re.compile(r"savoysystems|savoy", re.I)),
    ("enta",         re.compile(r"enta\.io|ticketsolve", re.I)),
    ("ticketsolve",  re.compile(r"ticketsolve", re.I)),
    ("audienceview", re.compile(r"audienceview|ovationtix", re.I)),
    ("roller",       re.compile(r"roller\.app|rollerdigital", re.I)),
    ("iwannaticket", re.compile(r"iwannaticket", re.I)),
    ("stickytickets",re.compile(r"stickytickets", re.I)),
    ("sydneyfringe", re.compile(r"tickets\.sydneyfringe", re.I)),
]

SPEKTRIX_CLIENT = [
    re.compile(r"system\.spektrix\.com/([a-z0-9_-]+)/", re.I),
    re.compile(r"spektrix-link\.com/clients/([a-z0-9_-]+)", re.I),
    re.compile(r"spektrix-link\.com/websites/([a-z0-9_]+)", re.I),
    re.compile(r"ticketing\.[^/\"'\s]+/([a-z0-9_-]+)/api/v\d", re.I),
    re.compile(r"/([a-z0-9_-]+)/api/v3/(?:events|customer|basket)", re.I),
]

WHATS_ON = ["", "/whats-on", "/what-s-on", "/whatson", "/events", "/shows", "/on-now", "/season"]


def get(client, url):
    try:
        r = client.get(url)
        return r if r.status_code == 200 else None
    except Exception:
        return None


def spektrix_events(client_id):
    """Confirm a Spektrix client by calling the documented endpoint."""
    try:
        r = httpx.get(f"https://system.spektrix.com/{client_id}/api/v3/events",
                      headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d, list):
                return len(d)
    except Exception:
        pass
    return None


def spektrix_client_from_host(host):
    """Spektrix's hosted web platform publishes the client id per site.

    purchase.oldfitztheatre.com.au
      -> app.spektrix-link.com/websites/purchase_oldfitztheatre_com_au/config.json
      -> {"client": "oldfitztheatre"}

    More reliable than scraping the JS bundle, where the id is assembled at
    runtime rather than written as a literal.
    """
    key = host.replace(".", "_")
    try:
        r = httpx.get(f"https://app.spektrix-link.com/websites/{key}/config.json",
                      headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code == 200:
            cid = r.json().get("client")
            if cid:
                return cid, spektrix_events(cid)
    except Exception:
        pass
    return None, None


def find_spektrix_client(text):
    for rx in SPEKTRIX_CLIENT:
        for m in rx.findall(text):
            cand = m if isinstance(m, str) else m[0]
            if cand.lower() in ("stable", "api", "www", "assets"):
                continue
            n = spektrix_events(cand)
            if n is not None:
                return cand, n
    return None, None


def discover(venue):
    site = (venue.get("website") or "").rstrip("/")
    out = {"id": venue["id"], "website": site, "platform": "", "client": "",
           "events": None, "ticket_hosts": [], "note": ""}
    if not site:
        out["note"] = "no website recorded"
        return out

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT,
                      follow_redirects=True) as c:
        pages, hosts = [], {}
        for path in WHATS_ON:
            r = get(c, site + path)
            if not r:
                continue
            pages.append(r.text)
            for m in re.finditer(r'href=["\'](https?://[^"\']+)', r.text):
                h = urlparse(m.group(1)).netloc.lower()
                if h and h != urlparse(str(r.url)).netloc.lower() and not SOCIAL.search(h):
                    hosts[h] = hosts.get(h, 0) + 1
            time.sleep(0.7)
            if len(pages) >= 3:
                break

        if not pages:
            out["note"] = "site unreachable"
            return out

        # platform sometimes named in the venue's own markup
        blob = "\n".join(pages)
        for name, rx in PLATFORMS:
            if rx.search(blob):
                out["platform"] = name
                break

        ticket_hosts = sorted([h for h in hosts if TICKET_HOST.search(h)],
                              key=lambda h: -hosts[h])[:3]
        out["ticket_hosts"] = ticket_hosts

        if out["platform"] == "spektrix":
            cid, n = find_spektrix_client(blob)
            if cid:
                out["client"], out["events"] = cid, n
                return out

        # follow the box office itself -- this is where the platform lives
        for h in ticket_hosts:
            r = get(c, f"https://{h}/")
            time.sleep(0.7)
            if not r:
                continue
            for name, rx in PLATFORMS:
                if rx.search(r.text):
                    out["platform"] = out["platform"] or name
                    if name == "spektrix":
                        cid, n = spektrix_client_from_host(h)
                        if not cid:
                            cid, n = find_spektrix_client(r.text)
                        if not cid:
                            # client id is often only in the JS bundle
                            for m in re.finditer(r'src=["\']([^"\']+\.js)', r.text):
                                js = get(c, urljoin(str(r.url), m.group(1)))
                                if js:
                                    cid, n = find_spektrix_client(js.text)
                                    if cid:
                                        break
                        if cid:
                            out["client"], out["events"] = cid, n
                    break
            if out["platform"]:
                break
    return out


if __name__ == "__main__":
    here = pathlib.Path(__file__).resolve().parent.parent
    venues = json.load(open(here / "theatres.json"))
    only = set(sys.argv[1:])
    rows = []
    for v in venues:
        if only and v["id"] not in only:
            continue
        r = discover(v)
        rows.append(r)
        ev = f"{r['events']} events" if r["events"] is not None else ""
        print(f"  {r['id']:36} {r['platform'] or '-':14} {r['client'] or '-':20} {ev}{r['note']}")
        sys.stdout.flush()
    out = here / "tools" / "feeds-discovered.json"
    json.dump(rows, open(out, "w"), indent=1)
    print(f"\nwrote {out} ({len(rows)} venues)")
    print("\nVerify a client before wiring it up: a valid API response is not")
    print("proof it is the right venue. theatreroyal.com.au resolved cleanly")
    print("to a 96-event Spektrix client -- Theatre Royal HOBART.")
