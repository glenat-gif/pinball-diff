"""Command line.

  python -m pbmdiff.run demo                        run on the bundled real week for Melbourne, no token needed
  python -m pbmdiff.run fetch [--since YYYY-MM-DD]  pull every area's feed into data/events.jsonl
  python -m pbmdiff.run digest --area melbourne [--days 7] [--until YYYY-MM-DD]
                                                    write a digest from the store, no network
  python -m pbmdiff.run sync [--days 7]             fetch, then write a digest for every area
  python -m pbmdiff.run areas                       list the areas and what the store holds for each
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
    print(digest.to_markdown(d, areas.AREAS["melbourne"][0], "the week to 2 October 2026 (real data)"))


def cmd_fetch(args):
    client = api.PinballMap()
    # Reach back two days past the last fetch so a late or slow run never leaves a hole.
    last = store.last_fetch()
    since = args.since or ((dt.date.fromisoformat(last) - dt.timedelta(days=2)).isoformat() if last
                           else (today() - dt.timedelta(days=args.backfill)).isoformat())
    total, fresh = 0, 0
    for name, (label, lat, lon) in areas.AREAS.items():
        subs = client.submissions_within(lat, lon, areas.MILES, since)
        n = store.add(subs)
        total += len(subs)
        fresh += n
        print(f"{name:<12} {len(subs):>4} since {since}, {n} new")
    store.mark_fetched(today().isoformat())
    print(f"{total} fetched, {fresh} new; store holds {len(store.load())} events")


def cmd_digest(args):
    _digest(args.area, args.days, args.until)


def _digest(area, days, until=None):
    until = until or (today() - dt.timedelta(days=1)).isoformat()      # yesterday is the last full day
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=days - 1)).isoformat()
    events = [e for e in store.between(store.load(), since, until) if areas.inside(area, e["lat"], e["lon"])]
    d = digest.build(events)
    md = digest.to_markdown(d, areas.AREAS[area][0], _period(since, until))
    out = digest.save(area, until, d, md)
    print(md)
    print(f"written to {out}", file=sys.stderr)
    return d


def cmd_sync(args):
    cmd_fetch(args)
    for area in areas.AREAS:
        _digest(area, args.days)


def cmd_areas(args):
    events = store.load().values()
    for name, (label, lat, lon) in areas.AREAS.items():
        n = sum(1 for e in events if areas.inside(name, e["lat"], e["lon"]))
        print(f"{name:<12} {label:<42} {n:>5} events in store")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    f = sub.add_parser("fetch"); f.add_argument("--since"); f.add_argument("--backfill", type=int, default=14)
    f.set_defaults(fn=cmd_fetch)
    d = sub.add_parser("digest"); d.add_argument("--area", default="melbourne", choices=list(areas.AREAS))
    d.add_argument("--days", type=int, default=7); d.add_argument("--until"); d.set_defaults(fn=cmd_digest)
    s = sub.add_parser("sync"); s.add_argument("--since"); s.add_argument("--backfill", type=int, default=14)
    s.add_argument("--days", type=int, default=7); s.set_defaults(fn=cmd_sync)
    sub.add_parser("areas").set_defaults(fn=cmd_areas)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
