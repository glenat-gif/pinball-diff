"""Australian pinball podcasts.

Each show's public feed is read once a day and its episodes kept in
data/podcasts.json: title, date, length, a short summary and the show's own
page for the episode. Audio is never copied; every listen goes to the show,
so its numbers stay its own. Shows are listed in site.json.
"""
import datetime as dt
import email.utils
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET

from . import store
from .config import SITE

PODCASTS = store.DATA / "podcasts.json"
IT = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def _text(s, limit=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        cut = s[:limit].rsplit(" ", 1)[0]
        s = cut.rstrip(",;:-") + "…"
    return s


def _tidy_title(title, strip=""):
    t = (title or "").strip()
    if strip and t.upper().startswith(strip.upper()):
        t = t[len(strip):].strip()
    t = re.sub(r"\s*:\s*", ": ", t)
    if t.isupper():                                  # "EPISODE 24: THE GAMES WE HATE TO LOVE"
        small = {"a", "an", "and", "the", "of", "to", "in", "on", "at", "for", "with", "vs", "or"}
        words = t.lower().split()
        t = " ".join(w if (i and w in small and not words[i - 1].endswith(":")) else w[:1].upper() + w[1:]
                     for i, w in enumerate(words))
        t = re.sub(r"\b(W\.a|Nsw|Sa|Vic|Qld|Ifpa|Le|Ce|Vpx|Wa)\b", lambda m: m.group(0).upper().replace(".A", ".A"), t)
    return t


def _minutes(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    if ":" in raw:
        parts = [int(p) for p in raw.split(":") if p.isdigit()]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
    elif raw.isdigit():
        secs = int(raw)
    else:
        return None
    return round(secs / 60)


def parse(xml_text, show):
    root = ET.fromstring(xml_text)
    ch = root.find("channel")
    img = ch.find(IT + "image")
    info = {"key": show["key"], "name": show["name"], "link": ch.findtext("link") or "",
            "image": img.get("href") if img is not None else "", "about": _text(ch.findtext("description"), 170),
            "apple": show.get("apple", ""), "spotify": show.get("spotify", ""), "feed": show["feed"]}
    episodes = []
    for it in ch.findall("item"):
        when = email.utils.parsedate_to_datetime(it.findtext("pubDate")) if it.findtext("pubDate") else None
        if not when:
            continue
        date = when.astimezone(store.LOCAL).date().isoformat()
        episodes.append({"show": show["key"], "title": _tidy_title(it.findtext("title"), show.get("strip", "")),
                         "date": date, "minutes": _minutes(it.findtext(IT + "duration")),
                         "summary": _text(it.findtext("description") or it.findtext(IT + "summary"), 240),
                         "link": it.findtext("link") or info["link"],
                         "id": it.findtext("guid") or it.findtext("link") or it.findtext("title")})
    return info, episodes


def fetch(get=None):
    shows, episodes, errors = [], [], []
    for show in SITE.get("podcasts", []):
        try:
            if get:
                text = get(show["feed"])
            else:
                req = urllib.request.Request(show["feed"], headers={"User-Agent": "pinball-diff/0.5 (github.com/glenat-gif/pinball-diff)"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    text = resp.read()
            info, eps = parse(text, show)
            shows.append(info)
            episodes += eps
        except Exception as err:                      # one broken feed must not hide the others
            errors.append(f"{show['name']}: {err}")
    if not shows and PODCASTS.exists():
        return load()                                  # keep yesterday's copy rather than blank the page
    episodes.sort(key=lambda e: e["date"], reverse=True)
    data = {"shows": shows, "episodes": episodes, "errors": errors}
    PODCASTS.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def load():
    if not PODCASTS.exists():
        return {"shows": [], "episodes": []}
    return json.loads(PODCASTS.read_text(encoding="utf-8"))


def between(data, since, until):
    return [e for e in data.get("episodes", []) if since <= e["date"] <= until]
