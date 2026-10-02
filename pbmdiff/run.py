"""Command line.

  python -m pbmdiff.run demo                      run on the bundled fixtures, no token needed
  python -m pbmdiff.run regions [word]            find the Pinball Map region name to use
  python -m pbmdiff.run sync --region melbourne   fetch today, diff against the last snapshot, write the digest
  python -m pbmdiff.run digest --region melbourne --since 2026-10-01 [--until 2026-10-08]
                                                  rebuild a digest from stored snapshots, no network
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

from . import api, diff, digest, snapshot

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def cmd_demo(args):
    old = snapshot.normalise(_load_fixture("lmx_day1.json"), _load_fixture("locations_day1.json"), "2026-09-28")
    new = snapshot.normalise(_load_fixture("lmx_day2.json"), _load_fixture("locations_day2.json"), "2026-10-01")
    events = diff.diff(old, new)
    d = digest.build(events, old, new)
    print(digest.to_markdown(d, "victoria", new["taken"], period="28 Sep to 1 Oct 2026 (demo data)"))


def cmd_regions(args):
    client = api.PinballMap()
    word = (args.word or "").lower()
    for r in client.regions():
        text = f"{r.get('name','')} {r.get('full_name','')}".lower()
        if word in text:
            print(f"{r.get('name'):<20} {r.get('full_name','')}")


def cmd_sync(args):
    client = api.PinballMap()
    today = args.date or dt.date.today().isoformat()
    lmxs = client.region_machines(args.region)
    locations = client.region_locations(args.region)
    new = snapshot.normalise(lmxs, locations, today)
    path = snapshot.save(args.region, new)
    print(f"saved {path} ({len(new['venues'])} venues, {len(new['machines'])} machines)")
    old = snapshot.previous(args.region, today)
    if not old:
        print("first snapshot; nothing to compare yet. Run again tomorrow.")
        return
    _write(args.region, old, new, today)


def cmd_digest(args):
    old = snapshot.load(args.region, args.since)
    until = args.until or snapshot.dates(args.region)[-1]
    new = snapshot.load(args.region, until)
    _write(args.region, old, new, until, period=f"{args.since} to {until}")


def _write(region, old, new, day, period=None):
    events = diff.diff(old, new)
    d = digest.build(events, old, new)
    md = digest.to_markdown(d, region, day, period)
    out = digest.save(region, day, d, md)
    print(md)
    print(f"written to {out}", file=sys.stderr)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    r = sub.add_parser("regions"); r.add_argument("word", nargs="?"); r.set_defaults(fn=cmd_regions)
    s = sub.add_parser("sync"); s.add_argument("--region", default="melbourne"); s.add_argument("--date"); s.set_defaults(fn=cmd_sync)
    d = sub.add_parser("digest"); d.add_argument("--region", default="melbourne"); d.add_argument("--since", required=True)
    d.add_argument("--until"); d.set_defaults(fn=cmd_digest)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
