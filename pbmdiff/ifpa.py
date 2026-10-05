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
        "venue": (t.get("location_name") or "").strip(), "city": (t.get("city") or "").strip(),
        "state": (t.get("stateprov") or "").strip(), "lat": lat, "lon": lon,
        "zone": areas.zone_of(lat, lon),
        "website": (t.get("website") or "").strip(), "director": (t.get("director_name") or "").strip(),
        "format": " / ".join(x for x in (t.get("qualifying_format"), t.get("finals_format")) if x),
        "ranking": t.get("ranking_system") or "MAIN", "women": (t.get("ranking_system") or "") == "WOMEN",
        "link": EVENT_URL.format(id=t.get("tournament_id")),
    }


def fetch(key=None, today=None, sleep=time.sleep, get=_get):
    key = key or os.environ.get("IFPA_API_KEY")
    if not key:
        return None
    today = today or dt.datetime.now(store.LOCAL).date()
    end = today + dt.timedelta(days=DAYS_AHEAD)
    found = {}
    for event_type in ("Tournament", "League"):
        pos = 1
        while True:
            data = get("tournament/search", key, country="Australia", event_type=event_type,
                       start_date=today.isoformat(), end_date=end.isoformat(), total=PAGE, start_pos=pos)
            rows = data.get("tournaments") or []
            if isinstance(rows, dict):
                rows = [rows]
            for t in rows:
                if t.get("private_flag") or (t.get("country_code") or "AU").upper() != "AU":
                    continue
                c = normalise(t)
                if c["id"] and c["start"]:
                    found[c["id"]] = c
            total = int(data.get("total_results") or 0)
            pos += PAGE
            if len(rows) < PAGE or pos > total:
                break
            sleep(1)
    comps = sorted(found.values(), key=lambda c: (c["start"], c["name"]))
    COMPS.write_text(json.dumps({"fetched": today.isoformat(), "comps": comps}, indent=1, ensure_ascii=False),
                     encoding="utf-8")
    return comps


def load():
    if not COMPS.exists():
        return []
    return json.loads(COMPS.read_text(encoding="utf-8")).get("comps", [])


def between(comps, since, until, zones=None):
    """Comps running at any point between two dates, optionally only in some zones."""
    return [c for c in comps if c["start"] <= until and (c["end"] or c["start"]) >= since
            and (zones is None or c["zone"] in zones)]
