"""Command line.

  python -m pbmdiff.run demo                        run on the bundled real week for Melbourne, no token needed
  python -m pbmdiff.run fetch [--since YYYY-MM-DD]  pull every area's feed into data/events.jsonl
  python -m pbmdiff.run digest --zone melbourne [--days 7] [--until YYYY-MM-DD]
                                                    write a digest from the store, no network
  python -m pbmdiff.run sync [--days 7]             fetch, then write a digest for every zone
  python -m pbmdiff.run zones                       list the zones and what the store holds for each
  python -m pbmdiff.run issue [--date YYYY-MM-DD]   make this week's email issue if due, and deliver it
  python -m pbmdiff.run comps                       fetch the next 60 days of IFPA events (needs IFPA_API_KEY)
  python -m pbmdiff.run build                       build the website into dist/
"""
import argparse
import os
import datetime as dt
import json
import pathlib
import sys

from . import api, areas, digest, ifpa, issue, mail, podcasts, site, store

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
    if args.machines or store.machines_age_days() is None or store.machines_age_days() > 6:
        print(f"machine catalogue refreshed: {store.save_machines(client.machines())} machines")
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


def cmd_comps(args):
    comps = ifpa.fetch()
    if comps is None:
        print("comps skipped: no IFPA_API_KEY")
        return
    by_zone = {}
    for c in comps:
        by_zone[c["zone"]] = by_zone.get(c["zone"], 0) + 1
    print(f"{len(comps)} upcoming IFPA events in the next {ifpa.DAYS_AHEAD} days: "
          + ", ".join(f"{z or 'no zone'} {n}" for z, n in sorted(by_zone.items(), key=lambda kv: -kv[1])))


def cmd_sync(args):
    cmd_fetch(args)
    try:
        cmd_comps(args)
    except Exception as err:                # comps are a bonus; never let them stop the digest
        print(f"comps fetch failed: {err}")
    pods = podcasts.fetch()
    print(f"podcasts: {len(pods.get('episodes', []))} episodes from {len(pods.get('shows', []))} shows"
          + (f"; problems: {pods['errors']}" if pods.get("errors") else ""))
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


def cmd_issue(args):
    events = store.load()
    if args.preview:
        # A throwaway Buttondown draft of the coming issue, built from today's data, so the
        # design can be checked in a real inbox. Nothing is saved to data/issues.
        nxt = issue.latest_issue_date() + dt.timedelta(days=7)
        iss = issue.make(events, nxt)
        subject = f"[PREVIEW] {mail.subject(iss)}"
        print(f"preview of {nxt}: {subject}")
        key = os.environ.get("BUTTONDOWN_API_KEY")
        if not key:
            print("not drafted: no BUTTONDOWN_API_KEY")
            return
        created = mail.post({"subject": subject, "body": mail.html(iss), "status": "draft"}, key)
        print(f"drafted in Buttondown: {created.get('id')} (delete it there when done)")
        return
    if args.send_now:
        latest = issue.latest_issue_date().isoformat()
        if not issue.path(latest).exists():
            print(f"nothing to send: no issue for {latest}"); return
        print(mail.send_now(issue.load(latest))); return
    if args.redraft:
        latest = issue.latest_issue_date().isoformat()
        if not issue.path(latest).exists():
            print(f"nothing to redraft: no issue for {latest}")
            return
        old = issue.load(latest)
        fresh = issue.make(events, dt.date.fromisoformat(latest))
        fresh["email"] = old.get("email")              # keep the Buttondown id; refresh the content
        issue.save(fresh)
        print(f"issue {latest}: {mail.subject(fresh)}")
        print(f"copy at {mail.keep_copy(fresh)}")
        print(mail.redraft(fresh))
        return
    if args.date:
        d = dt.date.fromisoformat(args.date)
        iss = issue.load(d.isoformat()) if issue.path(d.isoformat()).exists() else issue.make(events, d)
        issue.save(iss)
    else:
        iss = issue.ensure_latest(events)
        if iss is None:
            latest = issue.latest_issue_date().isoformat()
            if not issue.path(latest).exists():
                print(f"no issue due: the last issue day, {latest}, has passed")
                return
            iss = issue.load(latest)
    print(f"issue {iss['date']}: {mail.subject(iss)}")
    print(f"copy at {mail.keep_copy(iss)}")
    print(mail.deliver(iss))


def cmd_subscribers(args):
    """List subscribers (masked) with their tags, and optionally tag one by id."""
    key = os.environ.get("BUTTONDOWN_API_KEY")
    if not key:
        print("no BUTTONDOWN_API_KEY"); return
    if args.probe:
        print(mail.probe_tags(args.probe, key)); return
    if args.tag_id and args.tag_id != "list":          # "list" just lists
        replace = args.tag.startswith("=")                 # "=nsw" replaces every tag; "nsw" adds
        tags = [t.strip() for t in args.tag.lstrip("=").split(",") if t.strip()]
        print(f"{args.tag_id}: tags now {mail.tag_subscriber(args.tag_id, tags, key, replace=replace)}")
    for s in mail.subscribers(key):
        print(f"{s['id']}  {s['email']:<24} {s['status']:<10} tags={s['tags']}")


def cmd_build(args):
    print(f"built {site.build()}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    f = sub.add_parser("fetch"); f.add_argument("--since"); f.add_argument("--backfill", type=int, default=14)
    f.add_argument("--machines", action="store_true", help="refresh the machine catalogue now")
    f.set_defaults(fn=cmd_fetch)
    d = sub.add_parser("digest"); d.add_argument("--zone", default="vic", choices=list(areas.LABELS))
    d.add_argument("--days", type=int, default=7); d.add_argument("--until"); d.set_defaults(fn=cmd_digest)
    s = sub.add_parser("sync"); s.add_argument("--since"); s.add_argument("--backfill", type=int, default=14)
    s.add_argument("--machines", action="store_true")
    s.add_argument("--days", type=int, default=7); s.set_defaults(fn=cmd_sync)
    sub.add_parser("zones").set_defaults(fn=cmd_zones)
    sub.add_parser("comps").set_defaults(fn=cmd_comps)
    i = sub.add_parser("issue"); i.add_argument("--date")
    i.add_argument("--redraft", action="store_true", help="rebuild this week's issue and rewrite its Buttondown draft")
    i.add_argument("--preview", action="store_true", help="draft next Thursday's email from today's data, without saving an issue")
    i.add_argument("--send-now", action="store_true", help="send this week's Buttondown draft to the list now")
    i.set_defaults(fn=cmd_issue)
    sub.add_parser("build").set_defaults(fn=cmd_build)
    t = sub.add_parser("subscribers"); t.add_argument("--tag-id", default="", help="subscriber id to tag"); t.add_argument("--tag", default="vic")
    t.add_argument("--probe", default="", help="subscriber id to send a tag probe to")
    t.set_defaults(fn=cmd_subscribers)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
