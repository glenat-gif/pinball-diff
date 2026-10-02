"""What changed between two snapshots.

Produces flat, factual events. No judgement here; the digest decides what is
worth saying. Event shapes:

  machine_added / machine_removed  venue, machine
  condition                        venue, machine, comment, user, date
  venue_added / venue_removed      venue (with the machines it has or had)
  venue_confirmed                  venue, date, user
"""


def _venue(snap, loc_id, machine=None):
    v = snap["venues"].get(str(loc_id))
    if v:
        return {"location_id": v["id"], "location_name": v["name"], "city": v["city"]}
    return {"location_id": loc_id, "location_name": (machine or {}).get("location_name", ""), "city": ""}


def _machine(m):
    return {"lmx_id": m["lmx_id"], "machine_id": m["machine_id"], "group_id": m.get("group_id"),
            "machine": m["name"], "manufacturer": m.get("manufacturer", ""), "year": m.get("year")}


def diff(old, new):
    day = new["taken"]
    events = []
    old_m, new_m = old["machines"], new["machines"]
    old_v, new_v = old["venues"], new["venues"]

    for loc_id in new_v.keys() - old_v.keys():
        events.append({"type": "venue_added", "date": day, **_venue(new, loc_id)})
    for loc_id in old_v.keys() - new_v.keys():
        had = [m["name"] for m in old_m.values() if str(m["location_id"]) == loc_id]
        events.append({"type": "venue_removed", "date": day, "machines": sorted(had), **_venue(old, loc_id)})

    for lmx_id in new_m.keys() - old_m.keys():
        m = new_m[lmx_id]
        events.append({"type": "machine_added", "date": m.get("added") or day,
                       **_venue(new, m["location_id"], m), **_machine(m)})
    for lmx_id in old_m.keys() - new_m.keys():
        m = old_m[lmx_id]
        events.append({"type": "machine_removed", "date": day, **_venue(old, m["location_id"], m), **_machine(m)})

    for lmx_id, m in new_m.items():
        seen = {c["id"] for c in old_m.get(lmx_id, {}).get("conditions", []) if c["id"] is not None}
        seen_text = {c["comment"] for c in old_m.get(lmx_id, {}).get("conditions", [])}
        for c in m["conditions"]:
            fresh = c["id"] not in seen if c["id"] is not None else c["comment"] not in seen_text
            if fresh and c["comment"]:
                events.append({"type": "condition", "date": c["date"] or day, "comment": c["comment"],
                               "user": c["user"], **_venue(new, m["location_id"], m), **_machine(m)})

    for loc_id, v in new_v.items():
        before = old_v.get(loc_id)
        if before and v["last_confirmed"] and v["last_confirmed"] != before["last_confirmed"]:
            events.append({"type": "venue_confirmed", "date": v["last_confirmed"],
                           "user": v["confirmed_by"], **_venue(new, loc_id)})

    order = {"venue_added": 0, "venue_removed": 1, "machine_added": 2, "machine_removed": 3,
             "condition": 4, "venue_confirmed": 5}
    events.sort(key=lambda e: (order[e["type"]], e["location_name"], e.get("machine", "")))
    return events
