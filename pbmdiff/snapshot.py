"""Turn a day's API responses into one plain snapshot and keep it on disk.

A snapshot is the whole region on one day: every venue, every machine on
location, every condition note. Diffing two of them is the entire product.
Field access is defensive because Pinball Map nests `location` and `machine`
inside each xref in some responses and flattens them in others.
"""
import datetime as dt
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _pick(record, *names, default=None):
    """First present value among nested or flat spellings of a field."""
    for name in names:
        cur = record
        for part in name.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
            if cur is None:
                break
        if cur not in (None, ""):
            return cur
    return default


def _date(value):
    if not value:
        return None
    return str(value)[:10]


def normalise(lmxs, locations, taken=None):
    taken = taken or dt.date.today().isoformat()
    venues = {}
    for loc in locations:
        venues[str(loc["id"])] = {
            "id": loc["id"],
            "name": loc.get("name", "").strip(),
            "city": (loc.get("city") or "").strip(),
            "lat": loc.get("lat"), "lon": loc.get("lon"),
            "last_confirmed": _date(_pick(loc, "date_last_updated", "updated_at")),
            "confirmed_by": _pick(loc, "last_updated_by_username", default=""),
        }
    machines = {}
    for x in lmxs:
        loc_id = _pick(x, "location_id", "location.id")
        venue = venues.get(str(loc_id), {})
        conditions = []
        for c in x.get("machine_conditions") or []:
            conditions.append({"id": c.get("id"), "comment": (c.get("comment") or "").strip(),
                               "date": _date(c.get("created_at")),
                               "user": c.get("username") or c.get("user_name") or ""})
        if not conditions and _pick(x, "condition"):
            conditions.append({"id": None, "comment": _pick(x, "condition"),
                               "date": _date(_pick(x, "condition_date", "updated_at")), "user": ""})
        machines[str(x["id"])] = {
            "lmx_id": x["id"],
            "location_id": loc_id,
            "location_name": venue.get("name") or _pick(x, "location.name", "location_name", default=""),
            "machine_id": _pick(x, "machine_id", "machine.id"),
            "group_id": _pick(x, "machine.machine_group_id", "machine_group_id"),
            "name": _pick(x, "machine.name", "machine_name", default="").strip(),
            "manufacturer": _pick(x, "machine.manufacturer", "manufacturer", default=""),
            "year": _pick(x, "machine.year", "year"),
            "added": _date(x.get("created_at")),
            "conditions": sorted(conditions, key=lambda c: (c["date"] or "", c["id"] or 0)),
        }
    return {"taken": taken, "venues": venues, "machines": machines}


def snapshot_dir(region):
    return DATA / "snapshots" / region


def save(region, snap):
    folder = snapshot_dir(region)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snap['taken']}.json"
    path.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    return path


def load(region, date):
    return json.loads((snapshot_dir(region) / f"{date}.json").read_text(encoding="utf-8"))


def dates(region):
    folder = snapshot_dir(region)
    if not folder.exists():
        return []
    return sorted(p.stem for p in folder.glob("????-??-??.json"))


def previous(region, before):
    """The most recent snapshot taken before `before`, or None on day one."""
    earlier = [d for d in dates(region) if d < before]
    return load(region, earlier[-1]) if earlier else None
