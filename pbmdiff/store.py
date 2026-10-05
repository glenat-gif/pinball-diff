"""Everything ever fetched, one JSON object per line, keyed by Pinball Map id.

The feed is the source of truth; this is the local copy the digest is built
from, so request volume never depends on how often anyone reads a digest.
"""
import datetime as dt
import json
import pathlib
import zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EVENTS = DATA / "events.jsonl"
STATE = DATA / "state.json"
LOCAL = zoneinfo.ZoneInfo("Australia/Melbourne")

KINDS = {"new_lmx": "machine_added", "remove_machine": "machine_removed", "new_condition": "condition",
         "add_location": "venue_added", "confirm_location": "venue_confirmed"}


def local_date(created_at):
    """Pinball Map stamps in US Pacific time; the digest lives in Melbourne time."""
    stamp = dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return stamp.astimezone(LOCAL).date().isoformat()


def normalise(sub):
    """Keep the fields the digest needs, with plain names."""
    kind = KINDS.get(sub.get("submission_type"))
    if not kind:
        return None                         # high scores and anything new are not news
    return {
        "id": sub["id"], "type": kind, "date": local_date(sub["created_at"]), "stamp": sub["created_at"],
        "location_id": sub.get("location_id"), "location_name": (sub.get("location_name") or "").strip(),
        "city": (sub.get("city_name") or "").strip(), "lat": sub.get("lat"), "lon": sub.get("lon"),
        "machine_id": sub.get("machine_id"), "machine": (sub.get("machine_name") or "").strip(),
        "comment": (sub.get("comment") or "").strip(), "user": sub.get("user_name") or "",
    }


def load():
    if not EVENTS.exists():
        return {}
    events = {}
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            events[e["id"]] = e
    return events


def add(submissions):
    """Merge new submissions into the store. Returns how many were new."""
    events = load()
    fresh = 0
    for sub in submissions:
        e = normalise(sub)
        if e and e["id"] not in events:
            events[e["id"]] = e
            fresh += 1
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in sorted(events.values(), key=lambda e: e["id"])),
                      encoding="utf-8")
    return fresh


def between(events, since, until):
    return [e for e in events.values() if since <= e["date"] <= until]


def last_fetch():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8")).get("last_fetch")
    return None


def mark_fetched(day):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"last_fetch": day}, indent=1), encoding="utf-8")


MACHINES = DATA / "machines.json"


def save_machines(machines):
    """Keep only what the site uses: id, name, group and the OPDB image."""
    slim = {str(m["id"]): {"name": m.get("name"), "group": m.get("machine_group_id"),
                           "img": m.get("opdb_img"), "w": m.get("opdb_img_width"), "h": m.get("opdb_img_height")}
            for m in machines}
    MACHINES.write_text(json.dumps(slim, indent=0, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return len(slim)


def load_machines():
    if not MACHINES.exists():
        return {}
    return json.loads(MACHINES.read_text(encoding="utf-8"))


def machines_age_days():
    if not MACHINES.exists():
        return None
    import time
    return (time.time() - MACHINES.stat().st_mtime) / 86400
