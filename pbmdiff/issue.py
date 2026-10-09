"""Weeks and issues.

A week is any seven days of events for a zone, cleaned by the digest rules.
The website shows rolling weeks ending yesterday, rebuilt every morning.

An issue is the email. It is dated on the issue weekday (Thursday by
default), covers the seven days before it, and is frozen in
data/issues/<date>.json the first time it is made. Pinball Map edits that
arrive late show up on the website, never in an issue that has gone out.
"""
import datetime as dt
import json

from . import areas, digest, ifpa, podcasts, store
from .config import SITE

ISSUES = store.DATA / "issues"
COMPS_AHEAD = 10          # Thursday to the Sunday after next


def today():
    return dt.datetime.now(store.LOCAL).date()


def week(events, zone, until, days=7):
    until = until if isinstance(until, str) else until.isoformat()
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=days - 1)).isoformat()
    picked = [e for e in store.between(events, since, until) if areas.zone_of(e["lat"], e["lon"]) == zone]
    d = digest.build(picked)
    return {"zone": zone, "label": areas.LABELS[zone], "since": since, "until": until, **d}


def zone_order():
    """Email zones first in their configured order, then the rest as listed."""
    first = [z for z in SITE["email_zones"] if z in areas.LABELS]
    return first + [z for z in areas.LABELS if z not in first]


def latest_issue_date(on=None):
    on = on or today()
    back = (on.weekday() - SITE["issue_weekday"]) % 7
    return on - dt.timedelta(days=back)


def make(events, issue_date):
    """Build the issue dated `issue_date` covering the seven days before it."""
    until = (issue_date - dt.timedelta(days=1)).isoformat()
    zones = [week(events, z, until) for z in zone_order()]
    since = zones[0]["since"]
    ahead = (issue_date + dt.timedelta(days=COMPS_AHEAD)).isoformat()
    comps = ifpa.between(ifpa.enrich(ifpa.load(), ifpa.venues_from_events(events)), issue_date.isoformat(), ahead)
    pods = podcasts.load()
    shows = {sh["key"]: sh["name"] for sh in pods.get("shows", [])}
    episodes = [dict(ep, show_name=shows.get(ep["show"], "")) for ep in podcasts.between(pods, since, until)]
    return {"date": issue_date.isoformat(), "since": since, "until": until, "zones": zones,
            "comps": comps, "comps_until": ahead, "episodes": episodes, "email": None}


def path(date):
    return ISSUES / f"{date}.json"


def load(date):
    return json.loads(path(date).read_text(encoding="utf-8"))


def save(issue):
    ISSUES.mkdir(parents=True, exist_ok=True)
    path(issue["date"]).write_text(json.dumps(issue, indent=1), encoding="utf-8")


def all_dates():
    if not ISSUES.exists():
        return []
    return sorted((p.stem for p in ISSUES.glob("????-??-??.json")), reverse=True)


def published_dates():
    """Issues that reached Buttondown. Skipped ones never appear in the archive or feed."""
    return [d for d in all_dates() if (load(d).get("email") or {}).get("status") in ("draft", "about_to_send")]


def ensure_latest(events, on=None):
    """Make this week's issue if it is due and not made yet. Returns it, or None."""
    on = on or today()
    date = latest_issue_date(on)
    if path(date.isoformat()).exists() or (on - date).days > 2:
        return None                      # already made, or too late to be worth sending
    issue = make(events, date)
    save(issue)
    return issue


HIGHLIGHT_WEIGHT = {"New release": 3, "Limited Edition": 3, "Collector's Edition": 3, "Premium": 1}


def highlights(issue, limit=6):
    """The week's notable arrivals outside the email zones: new venues, rarer
    editions and new releases, best first, so a quiet local week still has
    something worth the open."""
    out = []
    for z in issue["zones"]:
        if z["zone"] in SITE["email_zones"]:
            continue
        for item in z["items"]:
            arriving = {n: f for n, f in (item.get("flags") or {}).items()}
            score = sum(HIGHLIGHT_WEIGHT.get(f, 0) for fl in arriving.values() for f in fl)
            if item["kind"] == "new_venue":
                score += 2
            if score == 0:
                continue
            best = max(arriving, key=lambda n: sum(HIGHLIGHT_WEIGHT.get(f, 0) for f in arriving[n])) if arriving else None
            out.append({**item, "zone": z["zone"], "state": z["label"], "score": score, "star": best})
    out.sort(key=lambda h: (-h["score"], h["location_name"]))
    return out[:limit]


def email_comps(issue):
    return [c for c in issue.get("comps", []) if c["zone"] in SITE["email_zones"]]


def email_zones(issue):
    return [z for z in issue["zones"] if z["zone"] in SITE["email_zones"]]
