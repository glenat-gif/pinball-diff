"""Turn raw events into the dozen things a week worth telling someone.

Rules, in the order they run:
  1. A new venue and its first machines are one item.
  2. A removal and an addition of the same title at one venue is a swap.
  3. What is left is grouped per venue: "added A, B and C", or a rotation
     when a venue both added and removed in the same period.
  4. Condition notes become a status: amber for trouble, green for good news.
  5. Bare confirmations are not news; they are counted in the footer.
Items are ranked so the biggest change at the quietest venue comes first.
"""
import re
import json
from collections import defaultdict

from . import store

DIGESTS = store.DATA / "digests"
ATTRIB = "https://pinballmap.com/map?by_location_id={id}"

EDITIONS = {"pro", "premium", "prem", "le", "limited", "edition", "remake", "special", "classic",
            "ce", "collector's", "collectors", "standard", "se", "sle", "home", "vault", "deluxe", "pin"}
TROUBLE = ["turned off", "switched off", "not working", "isn't working", "broken", "stuck", "dead",
           "out of order", "weak", "doesn't", "does not", "won't", "wont", "issue", "problem", "fault",
           "sticky", "unplayable", "no sound", "no display", "reset", "tilt", "missing", "off ", " off",
           "credit dot", "ball search", "needs", "cracked", "flaky", "intermittent", "not playable",
           "display only", "unplugged", "coin mech", "coinmech", "eating"]
GOOD = ["fixed", "repaired", "working", "plays great", "plays well", "playing great", "great condition",
        "good condition", "excellent", "back on", "all good", "no issues", "no problems", "fine now",
        "mint", "waxed", "cleaned", "new rubbers", "fully", "perfect"]


def base_title(name):
    """'Cactus Canyon (Remake Special)' and 'Cactus Canyon' are the same title."""
    t = re.sub(r"\([^)]*\)", " ", name or "").lower()
    words = [w for w in re.findall(r"[a-z0-9']+", t) if w not in EDITIONS]
    return " ".join(words)


def status_of(comment):
    text = " " + (comment or "").lower() + " "
    if any(g in text for g in GOOD) and not any(t in text for t in ["turned off", "not working", "broken", "dead", "unplayable"]):
        return "green"
    if any(t in text for t in TROUBLE):
        return "amber"
    return "note"


def _label(e):
    return e["machine"]


_FLAG = [(re.compile(r"\((?:LE|Limited Edition)\b", re.I), "Limited Edition"),
         (re.compile(r"\((?:CE|Collector'?s Edition)\b", re.I), "Collector's Edition"),
         (re.compile(r"\(Premium\b", re.I), "Premium")]
_YEAR = re.compile(r"(\d{4})\)\s*$")


def flags(name, this_year=None):
    """What makes a machine worth the drive: a rarer edition, or a new game."""
    import datetime as _dt
    this_year = this_year or _dt.date.today().year
    out = [label for rx, label in _FLAG if rx.search(name or "")][:1]
    m = _YEAR.search(name or "")
    if m and int(m.group(1)) >= this_year - 1:
        out.append("New release")
    return out


def _ids(evs):
    return {e["machine"]: e["machine_id"] for e in evs if e.get("machine_id")}


def build(events):
    by_venue = defaultdict(list)
    for e in sorted(events, key=lambda e: e["id"]):
        by_venue[str(e["location_id"])].append(e)
    items, confirmations = [], 0

    for lid, evs in by_venue.items():
        venue = {"location_id": evs[0]["location_id"], "location_name": evs[0]["location_name"],
                 "city": evs[0]["city"], "link": ATTRIB.format(id=evs[0]["location_id"]),
                 "lat": evs[0].get("lat"), "lon": evs[0].get("lon")}
        kinds = defaultdict(list)
        for e in evs:
            kinds[e["type"]].append(e)
        confirmations += len(kinds["venue_confirmed"])

        ids = _ids(evs)
        venue["ids"] = ids
        if kinds["venue_added"]:
            items.append({**venue, "kind": "new_venue", "rank": 0, "date": kinds["venue_added"][0]["date"],
                          "machines": [_label(e) for e in kinds["machine_added"]],
                          "by": sorted({e["user"] for e in kinds["venue_added"] + kinds["machine_added"] if e["user"]})})
            kinds["machine_added"] = []
        added, removed = list(kinds["machine_added"]), list(kinds["machine_removed"])
        for r in list(removed):
            for a in list(added):
                if base_title(r["machine"]) == base_title(a["machine"]):
                    items.append({**venue, "kind": "swap", "rank": 2, "date": a["date"],
                                  "out": _label(r), "in": _label(a), "by": sorted({x for x in (a["user"], r["user"]) if x})})
                    removed.remove(r)
                    added.remove(a)
                    break
        by = sorted({e["user"] for e in added if e["user"]})
        if added and removed:                  # a rotation: one line, in and out together
            items.append({**venue, "kind": "rotation", "rank": 3 - min(len(added), 3) * 0.1,
                          "date": max(e["date"] for e in added + removed),
                          "machines": [_label(e) for e in added], "out": [_label(e) for e in removed], "by": by})
        elif added:
            items.append({**venue, "kind": "added", "rank": 3 - min(len(added), 3) * 0.1, "date": max(e["date"] for e in added),
                          "machines": [_label(e) for e in added], "by": by})
        elif removed:
            items.append({**venue, "kind": "removed", "rank": 4, "date": max(e["date"] for e in removed),
                          "machines": [_label(e) for e in removed], "by": sorted({e["user"] for e in removed if e["user"]})})

        latest = {}
        for c in sorted(kinds["condition"], key=lambda e: e["id"]):
            latest[c["machine_id"]] = c         # keep the newest note per machine
        for c in latest.values():
            s = status_of(c["comment"])
            items.append({**venue, "kind": "condition", "status": s, "rank": 5 if s == "amber" else 6,
                          "date": c["date"], "machine": _label(c), "comment": c["comment"], "user": c["user"],
                          "by": [c["user"]] if c["user"] else []})

    for i in items:
        arriving = i.get("machines", []) if i["kind"] in ("new_venue", "added", "rotation") else \
            [i["in"]] if i["kind"] == "swap" else []
        i["flags"] = {n: flags(n) for n in arriving if flags(n)}
        if i["flags"]:
            i["rank"] -= 0.05
    items.sort(key=lambda i: (i["rank"], i["location_name"]))
    return {"items": items, "confirmations": confirmations}


def _venue_md(i):
    where = f" in {i['city']}" if i["city"] and i["city"].lower() not in i["location_name"].lower() else ""
    return f"[{i['location_name']}]({i['link']}){where}"


def _join(names):
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def to_markdown(digest, label, period):
    lines = [f"# Pinball changes: {label}, {period}", ""]
    if not digest["items"]:
        lines.append("Nothing changed on the map.")
    for i in digest["items"]:
        v = _venue_md(i)
        if i["kind"] == "new_venue":
            what = f" with {_join(i['machines'])}" if i["machines"] else ""
            lines.append(f"- **New venue:** {v}{what}.")
        elif i["kind"] == "swap":
            lines.append(f"- **Swap:** {v} replaced {i['out']} with {i['in']}.")
        elif i["kind"] == "added":
            n = len(i["machines"])
            head = "**New machine:**" if n == 1 else f"**{n} new machines:**"
            who = f" (thanks {_join(i['by'])})" if i.get("by") else ""
            lines.append(f"- {head} {v} added {_join(i['machines'])}.{who}")
        elif i["kind"] == "rotation":
            who = f" (thanks {_join(i['by'])})" if i.get("by") else ""
            lines.append(f"- **Rotation:** {v} brought in {_join(i['machines'])} and moved out {_join(i['out'])}.{who}")
        elif i["kind"] == "removed":
            n = len(i["machines"])
            head = "**Gone:**" if n == 1 else f"**{n} gone:**"
            lines.append(f"- {head} {v} removed {_join(i['machines'])}.")
        elif i["kind"] == "condition":
            flag = {"amber": "Needs a tech", "green": "Good news", "note": "Note"}[i["status"]]
            who = f" ({i['user']})" if i["user"] else ""
            lines.append(f"- **{flag}:** {i['machine']} at {v}: \"{i['comment']}\"{who}")
    lines += ["", f"Lineups confirmed unchanged at {digest['confirmations']} venue{'s' if digest['confirmations'] != 1 else ''}.",
              "", "Data from [Pinball Map](https://pinballmap.com), CC BY-SA 4.0. "
              "Each venue link opens its Pinball Map listing, where you can update it."]
    return "\n".join(lines) + "\n"


def save(area, day, digest, markdown):
    folder = DIGESTS / area
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.md").write_text(markdown, encoding="utf-8")
    (folder / f"{day}.json").write_text(json.dumps(digest, indent=1), encoding="utf-8")
    return folder / f"{day}.md"
