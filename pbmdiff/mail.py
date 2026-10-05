"""The Thursday email.

The issue becomes Markdown, which Buttondown turns into a clean email with
its own unsubscribe link and sender address, as the Spam Act requires. A copy
is kept beside the issue in data/issues/<date>.md, so every email is readable
in the repository whether or not it was sent.

  email_mode "draft"  the issue waits in Buttondown for a person to read and send
  email_mode "send"   it goes straight out

A week with nothing in the email zones sends nothing. An issue that already
has an email recorded is never sent twice.
"""
import datetime as dt
import json
import os
import urllib.error
import urllib.request

from . import issue, render
from .config import SITE

API = "https://api.buttondown.com/v1/emails"
LEAD = {"new_venue": "a new venue in {where}", "swap": "a swap at {venue}", "rotation": "a rotation at {venue}",
        "added": "new at {venue}", "removed": "a farewell at {venue}"}


def site_url(path=""):
    return SITE["base_url"] + path


def subject(iss):
    zones = issue.email_zones(iss)
    n = render.count_changes(zones)
    items = sorted((i for z in zones for i in z["items"]), key=lambda i: i["rank"])
    lead = ""
    if items and items[0]["kind"] in LEAD:
        top = items[0]
        lead = ": " + LEAD[top["kind"]].format(where=render.where(top) or top["location_name"], venue=top["location_name"])
    if n == 0:
        k = len(issue.email_comps(iss))
        return f"{k} comp{'s' if k != 1 else ''} coming up in Victoria"
    return f"{n} change{'s' if n != 1 else ''} in Victoria{lead}"


def _machines(names, item=None):
    return render.join(_machine(n, item) for n in names)


def _machine(name, item=None):
    flags = (item or {}).get("flags", {}).get(name, [])
    return name + (f" **[{', '.join(flags)}]**" if flags else "")


def line(item):
    city = render.where(item)
    venue = f"[{item['location_name']}]({item['link']})" + (f", {city}" if city else "")
    k = item["kind"]
    if k == "new_venue":
        what = f"New to the map with {_machines(item['machines'], item)}." if item["machines"] else "New to the map."
    elif k == "swap":
        what = f"Swapped {item['out']} for {_machine(item['in'], item)}."
    elif k == "rotation":
        what = f"In: {_machines(item['machines'], item)}. Out: {_machines(item['out'])}."
    elif k == "added":
        what = f"Added {_machines(item['machines'], item)}."
    elif k == "removed":
        what = f"Removed {_machines(item['machines'])}."
    else:
        what = f"{item['machine']}: “{item['comment']}”"
    by = item.get("by") or []
    meta = render.day(item["date"]) + (f", via {render.join(by)}" if by else "")
    return f"- **{render.label(item)}.** {venue}. {what} _{meta}_"


def comp_line(c):
    kind = render.comp_kind(c)
    where = ", ".join(x for x in (c["venue"], c["city"]) if x)
    extra = f" {kind}." if kind else ""
    page = f" [Event page]({c['website']})." if c["website"] else ""
    return f"- **{render.comp_when(c)}.** [{c['name']}]({c['link']}), {where}.{extra}{page}"


def markdown(iss):
    zones = issue.email_zones(iss)
    active = [z for z in zones if z["items"]]
    quiet = [z for z in zones if not z["items"]]
    out = ["<!-- buttondown-editor-mode: plaintext -->",
           f"What changed on Pinball Map in Victoria, {render.span(iss['since'], iss['until'])}. "
           f"Every state is on [the website]({site_url('/')}).", ""]
    comps = issue.email_comps(iss)
    if comps:
        out += ["## Comps coming up", ""] + [comp_line(c) for c in comps] + [""]
    for z in active:
        out += [f"## {z['label']}", ""] + [line(i) for i in z["items"]] + [""]
    if quiet:
        out += [f"Quiet on the map: {render.join(render.SHORT_NAMES.get(z['zone'], z['label']) for z in quiet)}.", ""]
    out += ["---", "",
            "Every venue links to its Pinball Map listing. If something is wrong, or you played something new, "
            "update it there and it will be in next week's email.", "",
            f"Data from [Pinball Map](https://pinballmap.com), CC BY-SA 4.0. "
            f"[Past emails]({site_url('/issues/')}) · [About]({site_url('/about/')})", ""]
    return "\n".join(out)


def keep_copy(iss):
    path = issue.ISSUES / f"{iss['date']}.md"
    path.write_text(f"Subject: {subject(iss)}\n\n{markdown(iss)}", encoding="utf-8")
    return path


def post(payload, key, opener=urllib.request.urlopen):
    req = urllib.request.Request(API, data=json.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Token {key}", "Content-Type": "application/json",
        "User-Agent": "pinball-diff/0.3"})
    with opener(req, timeout=60) as resp:
        return json.load(resp)


def deliver(iss, key=None, opener=urllib.request.urlopen):
    """Create the email in Buttondown if it is due. Returns a short status line."""
    if iss.get("email"):
        return f"already handled: {iss['email'].get('status')}"
    age = (issue.today() - dt.date.fromisoformat(iss["date"])).days
    if age > 2:
        iss["email"] = {"status": "skipped", "reason": f"found {age} days after its date; too late to send"}
        issue.save(iss)
        return "skipped: too old to send"
    if render.count_changes(issue.email_zones(iss)) == 0 and not issue.email_comps(iss):
        iss["email"] = {"status": "skipped", "reason": "nothing changed in the email zones"}
        issue.save(iss)
        return "skipped: a quiet week"
    key = key or os.environ.get("BUTTONDOWN_API_KEY")
    if not key:
        return "not sent: no BUTTONDOWN_API_KEY; the copy in data/issues is ready to read"
    mode = SITE.get("email_mode", "draft")
    status = "about_to_send" if mode == "send" else "draft"
    try:
        made = post({"subject": subject(iss), "body": markdown(iss), "status": status}, key, opener)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Buttondown refused the email ({err.code}): {err.read()[:400]!r}")
    iss["email"] = {"status": status, "id": made.get("id"),
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    issue.save(iss)
    return f"{'sent' if status == 'about_to_send' else 'drafted'} in Buttondown: {made.get('id')}"
