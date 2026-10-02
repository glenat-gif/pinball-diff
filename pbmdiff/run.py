"""Command line.

  python -m pbmdiff.run demo                        run on the bundled real week for Melbourne, no token needed
  python -m pbmdiff.run fetch [--since YYYY-MM-DD]  pull every area's feed into data/events.jsonl
  python -m pbmdiff.run digest --zone melbourne [--days 7] [--until YYYY-MM-DD]
                                                    write a digest from the store, no network
  python -m pbmdiff.run sync [--days 7]             fetch, then write a digest for every zone
  python -m pbmdiff.run zones                       list the zones and what the store holds for each
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from . import api, areas, digest, store

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def today():
    return dt.datetime.now(store.LOCAL).date()


def _period(since, until):
    return f"{since} to {until}" if since != until else until


def cmd_demo(args):
    subs = json.loads((FIXTURES / "melbourne_week.json").read_text(encoding="utf-8"))["user_submissions"]
    events = [e for e in (store.normalise(s) for s in subs) if e]
    d = digest.build(events)
    print(digest.to_markdown(d, "within 250 miles of Melbourne", "the week to 2 October 2026 (real data)"))


def cmd_fetch(args):
    client = api.PinballMap()
    # Reach back two days past the last fetch so a late or slow run never leaves a hole.
    last = store.last_fetch()
    since = args.since or ((dt.date.fromisoformat(last) - dt.timedelta(days=2)).isoformat() if last
                           else (today() - dt.timedelta(days=args.backfill)).isoformat())
    total, fresh = 0, 0
    for name, (lat, lon) in areas.FETCH.items():
        subs = client.submissions_within(lat, lon, areas.MILES, since)
        n = store.add(subs)
        total += len(subs)
        fresh += n
        print(f"{name:<12} {len(subs):>4} since {since}, {n} new")
    store.mark_fetched(today().isoformat())
    print(f"{total} fetched, {fresh} new; store holds {len(store.load())} events")


def cmd_digest(args):
    _digest(args.zone, args.days, args.until)


def _digest(zone, days, until=None):
    until = until or (today() - dt.timedelta(days=1)).isoformat()      # yesterday is the last full day
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=days - 1)).isoformat()
    events = [e for e in store.between(store.load(), since, until) if areas.zone_of(e["lat"], e["lon"]) == zone]
    d = digest.build(events)
    md = digest.to_markdown(d, areas.LABELS[zone], _period(since, until))
    out = digest.save(zone, until, d, md)
    print(md)
    print(f"written to {out}", file=sys.stderr)
    return d


def cmd_sync(args):
    cmd_fetch(args)
    for key in areas.LABELS:
        _digest(key, args.days)


def cmd_zones(args):
    events = list(store.load().values())
    for key, label, _ in areas.ZONES:
        n = sum(1 for e in events if areas.zone_of(e["lat"], e["lon"]) == key)
        print(f"{key:<18} {label:<70} {n:>4}")
    lost = [e for e in events if areas.zone_of(e["lat"], e["lon"]) is None]
    print(f"{'(no zone)':<18} {'':<70} {len(lost):>4}")
    for e in lost:
        print(f"   {e['location_name']} in {e['city']} ({e['lat']}, {e['lon']})")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    f = sub.add_parser("fetch"); f.add_argument("--since"); f.add_argument("--backfill", type=int, default=14)
    f.set_defaults(fn=cmd_fetch)
    d = sub.add_parser("digest"); d.add_argument("--zone", default="melbourne", choices=list(areas.LABELS))
    d.add_argument("--days", type=int, default=7); d.add_argument("--until"); d.set_defaults(fn=cmd_digest)
    s = sub.add_parser("sync"); s.add_argument("--since"); s.add_argument("--backfill", type=int, default=14)
    s.add_argument("--days", type=int, default=7); s.set_defaults(fn=cmd_sync)
    sub.add_parser("zones").set_defaults(fn=cmd_zones)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
