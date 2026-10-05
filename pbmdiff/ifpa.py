"""Upcoming IFPA-sanctioned competitions in Australia.

One search a day for the next 60 days of tournaments and leagues, paged 250
at a time (the API's maximum), kept in data/comps.json. Private events are
dropped. Each event is filed into the same zones as everything else, from
its own coordinates.

Needs IFPA_API_KEY (sign in at https://www.ifpapinball.com/api/ to make one).
Without a key the fetch is skipped and the site simply has no comps.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import areas, store

BASE = "https://api.ifpapinball.com/"
EVENT_URL = "https://www.ifpapinball.com/tournaments/view.php?t={id}"
COMPS = store.DATA / "comps.json"
DAYS_AHEAD = 60
PAGE = 250


def _get(path, key, **params):
    params["api_key"] = key
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "pinball-diff/0.4 (github.com/glenat-gif/pinball-diff)",
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _yes(v):
    """IFPA flags may arrive as true/false, "Y"/"N" or 1/0."""
    return str(v).strip().lower() in ("true", "y", "yes", "1")


def _country_ok(t):
    code = str(t.get("country_code") or "").upper()
    name = str(t.get("country_name") or "").lower()
    return code in ("", "AU", "AUS") or name == "australia"


_BLANK = {"", "none", "not set", "n/a", "tbd"}


def _venue(t):
    """IFPA often leaves location_name empty; the address usually starts with the venue."""
    name = (t.get("location_name") or "").strip()
    if name:
        return name
    first = (t.get("raw_address") or "").split(",")[0].strip()
    street = (t.get("address1") or "").strip().lower()
    looks_like_street = bool(re.match(r"^\d", first)) or (street and street.split()[-1] in first.lower()
                                                          and first.lower().split()[-1] in street)
    return "" if not first or looks_like_street else first


def _format(t):
    parts = [str(x).strip() for x in (t.get("qualifying_format"), t.get("finals_format")) if x]
    return " / ".join(p for p in parts if p.lower() not in _BLANK)


def normalise(t):
    lat, lon = _num(t.get("latitude")), _num(t.get("longitude"))
    start = (t.get("event_start_date") or "")[:10]
    end = (t.get("event_end_date") or "")[:10] or start
    name = (t.get("tournament_name") or "").strip()
    event = (t.get("event_name") or "").strip()
    return {
        "id": t.get("tournament_id"), "name": name,
        "event": event if event and event.lower() not in ("main tournament", name.lower()) else "",
        "type": t.get("event_type") or "Tournament", "start": start, "end": end,
        "venue": _venue(t), "city": (t.get("city") or "").strip(),
        "state": (t.get("stateprov") or "").strip(), "lat": lat, "lon": lon,
        "zone": areas.zone_of(lat, lon),
        "website": (t.get("website") or "").strip(), "director": (t.get("director_name") or "").strip(),
        "format": _format(t),
        "ranking": t.get("ranking_system") or "MAIN", "women": (t.get("ranking_system") or "") == "WOMEN",
        "link": EVENT_URL.format(id=t.get("tournament_id")),
    }


QUERIES = [  # the country name, code and a continent-wide radius all return the same events
    {"country": "Australia"},
]


def fetch(key=None, today=None, sleep=time.sleep, get=_get):
    key = key or os.environ.get("IFPA_API_KEY")
    if not key:
        return None
    today = today or dt.datetime.now(store.LOCAL).date()
    end = today + dt.timedelta(days=DAYS_AHEAD)
    found, report, sample = {}, [], {}
    for query in QUERIES:
        for event_type in ("Tournament",):          # IFPA ignores the type filter; leagues come back too
            pos, seen = 1, 0
            while True:
                try:
                    data = get("tournament/search", key, event_type=event_type, start_date=today.isoformat(),
                               end_date=end.isoformat(), total=PAGE, start_pos=pos, **query)
                except urllib.error.HTTPError as err:
                    report.append({"query": query, "type": event_type, "http": err.code,
                                   "body": err.read()[:300].decode("utf-8", "replace")})
                    break
                rows = data.get("tournaments") or []
                if isinstance(rows, dict):
                    rows = [rows]
                seen += len(rows)
                dropped = {"private": 0, "country": 0, "no_date": 0}
                for t in rows:
                    if _yes(t.get("private_flag")):
                        dropped["private"] += 1
                        continue
                    if not _country_ok(t):
                        dropped["country"] += 1
                        continue
                    c = normalise(t)
                    if c["id"] and c["start"]:
                        found[c["id"]] = c
                    else:
                        dropped["no_date"] += 1
                if rows and not sample:
                    sample.update({k: rows[0].get(k) for k in list(rows[0])[:30]})
                total = int(data.get("total_results") or 0)
                pos += PAGE
                if len(rows) < PAGE or pos > total:
                    report.append({"query": query, "type": event_type, "total_results": total, "rows": seen,
                                   "keys": sorted(data.keys())[:8],
                                   "error": data.get("error") or data.get("message"), "dropped": dropped})
                    break
                sleep(1)
            sleep(0.5)
    comps = sorted(found.values(), key=lambda c: (c["start"], c["name"]))
    COMPS.write_text(json.dumps({"fetched": today.isoformat(), "report": report, "sample": sample, "comps": comps},
                                indent=1, ensure_ascii=False), encoding="utf-8")
    return comps


def load():
    if not COMPS.exists():
        return []
    return json.loads(COMPS.read_text(encoding="utf-8")).get("comps", [])


def between(comps, since, until, zones=None):
    """Comps running at any point between two dates, optionally only in some zones."""
    return [c for c in comps if c["start"] <= until and (c["end"] or c["start"]) >= since
            and (zones is None or c["zone"] in zones)]
