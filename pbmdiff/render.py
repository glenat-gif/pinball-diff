"""Words and small pieces shared by the website and the email.

One place decides how a change reads, so the page and the inbox never
disagree. Machine names arrive from Pinball Map as
"Title (Edition) (Maker, Year)"; they are split so the title can carry the
weight and the maker and year can sit quietly beside it.
"""
import datetime as dt
import re

from .areas import SHORT as SHORT_NAMES

KIND_LABEL = {"new_venue": "New venue", "swap": "Swap", "rotation": "Rotation", "added": "Landed",
              "removed": "Gone", "condition": None}
STATUS_LABEL = {"amber": "Trouble", "green": "Good news", "note": "Note"}

_MAKER = re.compile(r"^(.*?)\s*\(([^()]*?,\s*\d{4})\)\s*$")


def split_machine(name):
    m = _MAKER.match(name or "")
    return (m.group(1), m.group(2)) if m else (name or "", "")


def label(item):
    if item["kind"] == "condition":
        return STATUS_LABEL[item["status"]]
    return KIND_LABEL[item["kind"]]


def tone(item):
    """A single word the page uses to colour the label."""
    if item["kind"] == "condition":
        return {"amber": "trouble", "green": "good", "note": "note"}[item["status"]]
    return {"new_venue": "new", "added": "new", "swap": "swap", "rotation": "swap", "removed": "gone"}[item["kind"]]


def join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def where(item):
    city = item.get("city") or ""
    return city if city and city.lower() not in item["location_name"].lower() else ""


def day(iso, today=None):
    """Sat 3 Oct this year; 3 Oct 2024 for anything older."""
    d = dt.date.fromisoformat(iso)
    today = today or dt.date.today()
    if (today - d).days < 300:
        return f"{d:%a} {d.day} {d:%b}"
    return f"{d.day} {d:%b %Y}"


def month(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%B %Y}"


def long_day(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%A} {d.day} {d:%B %Y}"


def span(since, until):
    a, b = dt.date.fromisoformat(since), dt.date.fromisoformat(until)
    if a.month == b.month:
        return f"{a.day} to {b.day} {b:%B %Y}"
    return f"{a.day} {a:%B} to {b.day} {b:%B %Y}"


def count_changes(zones):
    return sum(len(z["items"]) for z in zones)


def short_span(since, until):
    a, b = dt.date.fromisoformat(since), dt.date.fromisoformat(until)
    return f"{a.day} {a:%b} to {b.day} {b:%b}"
