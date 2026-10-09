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

from . import areas, issue, render
from .config import SITE

API = "https://api.buttondown.com/v1/emails"
LEAD = {"new_venue": "a new venue in {where}", "swap": "a swap at {venue}", "rotation": "a rotation at {venue}",
        "added": "new at {venue}", "removed": "a farewell at {venue}"}


def site_url(path=""):
    return SITE["base_url"] + path


def _headline(item, zone, local):
    """A short phrase and a score. Venue first for venues, machine first for arrivals."""
    title = lambda n: render.split_machine(n)[0]
    where = item.get("city") or item["location_name"]
    flags = item.get("flags") or {}
    weight = lambda n: sum(issue.HIGHLIGHT_WEIGHT.get(f, 0) for f in flags.get(n, []))
    flagged = sorted((n for n in flags if flags[n]), key=weight, reverse=True)   # rarest first
    k = item["kind"]
    if k == "new_venue":
        first = f", with {title(item['machines'][0])}" if item.get("machines") else ""
        return (f"New venue: {item['location_name']}{first}", 12 if local else 5)
    if k in ("added", "rotation", "swap"):
        names = flagged or item.get("machines") or [item.get("in")]
        name = title(names[0]) if names and names[0] else None
        if not name:
            return None
        score = (10 if local else 3) + (weight(names[0]) if flagged else 0)   # local always leads
        return (f"{name} lands at {item['location_name']}" if local else f"{name} lands in {where}", score)
    if k == "removed":
        return (f"{title(item['machines'][0])} leaves {item['location_name']}", 2 if local else 0)
    if k == "condition" and item.get("status") == "green":
        return (f"{title(item['machine'])} fixed at {item['location_name']}", 2 if local else 0)
    return None


def subject(iss):
    """Lead with the best thing that happened, never with a count."""
    heads = []
    for z in iss["zones"]:
        local = z["zone"] in SITE["email_zones"]
        for item in z["items"]:
            h = _headline(item, z["zone"], local)
            if h and h[1] > 0:
                heads.append(h)
    comps = issue.email_comps(iss)
    for c in comps[:2]:
        when = render.day(c["start"]).split(" ", 1)[0]       # Thu
        heads.append((f"{c['venue'] or c['name']} comp {when}", 4))
    heads.sort(key=lambda h: -h[1])
    if not heads:
        return "This week in Australian pinball"
    if len(heads) > 1 and heads[1][1] > 3:          # a plain interstate arrival is not a headline
        second = heads[1][0]
        second = second[0].lower() + second[1:] if second.startswith("New venue") else second
        return f"{heads[0][0]}, and {second}"
    return heads[0][0]


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
    hi = issue.highlights(iss)
    if hi:
        out += ["## Around Australia", ""] + [line(h) + f" _{areas.SHORT[h['zone']]}_" for h in hi] + [""]
    eps = iss.get("episodes") or []
    if eps:
        out += ["## On the podcasts", ""] + [f"- **{ep['show_name']}:** [{ep['title']}]({ep['link']})" for ep in eps] + [""]
    if quiet:
        out += [f"Quiet on the map: {render.join(render.SHORT_NAMES.get(z['zone'], z['label']) for z in quiet)}.", ""]
    out += ["---", "",
            "Every venue links to its Pinball Map listing. If something is wrong, or you played something new, "
            "update it there and it will be in next week's email.", "",
            f"Data from [Pinball Map](https://pinballmap.com), CC BY-SA 4.0. "
            f"[Past emails]({site_url('/issues/')}) · [About]({site_url('/about/')})", ""]
    return "\n".join(out)


import html as _html
_e = _html.escape
TONE = {"new": "#b84c00", "swap": "#5b3fd6", "trouble": "#c0254f", "good": "#23824a", "gone": "#7a7382"}


def _h_machine(name, item=None):
    title, maker = render.split_machine(name)
    flags = (item or {}).get("flags", {}).get(name, [])
    pills = "".join(f' <span style="font:700 10px/1.6 Arial,sans-serif;color:#b84c00;border:1px solid #b84c00;'
                    f'border-radius:9px;padding:0 6px;white-space:nowrap">{_e(f).upper()}</span>' for f in flags)
    tail = f' <span style="color:#655e6e">({_e(maker)})</span>' if maker else ""
    return f'<b>{_e(title)}</b>{tail}{pills}'


def _h_what(item):
    k = item["kind"]
    j = lambda names: render.join(_h_machine(n, item) for n in names)
    if k == "new_venue":
        return f"New to the map with {j(item['machines'])}." if item["machines"] else "New to the map."
    if k == "swap":
        return f"Swapped {_h_machine(item['out'])} for {_h_machine(item['in'], item)}."
    if k == "rotation":
        return f"In: {j(item['machines'])}. Out: {j(item['out'])}."
    if k == "added":
        return f"Added {j(item['machines'])}."
    if k == "removed":
        return f"Removed {j(item['machines'])}."
    return (f'{_h_machine(item["machine"])}<br><span style="color:#444;font-style:italic;border-left:3px solid #e2dccf;'
            f'padding-left:8px;display:inline-block;margin-top:4px">{_e(item["comment"])}</span>')


def _h_row(label, colour, body, meta=""):
    meta_html = f'<div style="color:#655e6e;font-size:13px;margin-top:3px">{meta}</div>' if meta else ""
    return (f'<tr><td style="padding:12px 0;border-bottom:1px solid #e2dccf;vertical-align:top;width:104px">'
            f'<span style="font:800 11px/1.8 Arial,sans-serif;letter-spacing:1px;text-transform:uppercase;color:{colour}">'
            f'&#9679; {_e(label)}</span></td>'
            f'<td style="padding:12px 0 12px 10px;border-bottom:1px solid #e2dccf;vertical-align:top;font:15px/1.5 Arial,sans-serif;color:#1b1720">'
            f'{body}{meta_html}</td></tr>')


def _h_item(item, state=""):
    city = render.where(item)
    venue = f'<a href="{_e(item["link"])}" style="color:#1b1720;font-weight:700">{_e(item["location_name"])}</a>'
    venue += f' <span style="color:#655e6e">{_e(city)}</span>' if city else ""
    venue += f' <span style="color:#b84c00;font-size:12px;font-weight:700">&nbsp;{_e(state)}</span>' if state else ""
    by = item.get("by") or []
    meta = _e(render.day(item["date"])) + (f" · via {_e(render.join(by))}" if by else "")
    return _h_row(render.label(item), TONE[render.tone(item)], f"{venue}<br>{_h_what(item)}", meta)


def _h_comp(c):
    where = ", ".join(x for x in (c["venue"], c["city"]) if x)
    more = f' · <a href="{_e(c["website"])}" style="color:#5b3fd6">Event page</a>' if c["website"] else ""
    fmt = f'<div style="color:#655e6e;font-size:13px">{_e(c["format"])}</div>' if c.get("format") else ""
    body = (f'<a href="{_e(c["link"])}" style="color:#1b1720;font-weight:700">{_e(c["name"])}</a><br>'
            f'<span style="color:#655e6e">{_e(where)}</span>{more}{fmt}')
    return _h_row(render.comp_when(c), "#b84c00", body)


def _h_section(title, rows):
    return (f'<h2 style="font:700 18px/1.3 Arial,sans-serif;color:#1b1720;margin:28px 0 4px;padding-bottom:6px;'
            f'border-bottom:2px solid #1b1720">{_e(title)}</h2>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{"".join(rows)}</table>')


def html(iss):
    """The email as its own page: the backbox header, then the week."""
    zones = issue.email_zones(iss)
    active = [z for z in zones if z["items"]]
    quiet = [z for z in zones if not z["items"]]
    parts = []
    comps = issue.email_comps(iss)
    if comps:
        parts.append(_h_section("Comps coming up", [_h_comp(c) for c in comps]))
    for z in active:
        parts.append(_h_section(z["label"], [_h_item(i) for i in z["items"]]))
    if quiet:
        parts.append(f'<p style="font:15px/1.5 Arial,sans-serif;color:#655e6e;margin:18px 0 0">Quiet on the map in '
                     f'{_e(render.join(areas.SHORT[z["zone"]] for z in quiet))}: nothing changed this week.</p>')
    hi = issue.highlights(iss)
    if hi:
        parts.append(_h_section("Around Australia", [_h_item(h, areas.SHORT[h["zone"]]) for h in hi]))
    eps = iss.get("episodes") or []
    if eps:
        rows = [_h_row("Episode", "#b84c00", f'<span style="color:#655e6e">{_e(ep["show_name"])}</span><br>'
                       f'<a href="{_e(ep["link"])}" style="color:#1b1720;font-weight:700">{_e(ep["title"])}</a>') for ep in eps]
        parts.append(_h_section("On the podcasts", rows))
    span = render.span(iss["since"], iss["until"])
    n = render.count_changes(zones)
    head = (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background:#120e18;border-radius:10px">'
            f'<tr><td style="padding:26px 24px 22px">'
            f'<div style="font:900 30px/1 \'Courier New\',Courier,monospace;letter-spacing:2px;color:#ff7a1a">PINBALL THIS WEEK</div>'
            f'<div style="font:15px/1.5 Arial,sans-serif;color:#f4efe6;margin-top:12px">What changed on Pinball Map in Victoria, {_e(span)}.</div>'
            f'<div style="font:700 13px/1.6 \'Courier New\',Courier,monospace;letter-spacing:1px;color:#ff7a1a;margin-top:10px">'
            f'VICTORIA &middot; {_e(span.upper())} &middot; '
            f'<a href="{_e(site_url("/"))}" style="color:#ff7a1a">EVERY STATE ON THE WEBSITE</a></div>'
            f'</td></tr></table>')
    foot = (f'<p style="font:13px/1.5 Arial,sans-serif;color:#655e6e;margin:30px 0 0;padding-top:14px;border-top:1px solid #e2dccf">'
            f'Every venue links to its Pinball Map listing. If something is wrong, or you played something new, '
            f'update it there and it will be in next week\'s email.<br>'
            f'Data from <a href="https://pinballmap.com" style="color:#655e6e">Pinball Map</a>, CC BY-SA 4.0. '
            f'Comps from the IFPA calendar. '
            f'<a href="{_e(site_url("/issues/"))}" style="color:#655e6e">Past emails</a> &middot; '
            f'<a href="{_e(site_url("/about/"))}" style="color:#655e6e">About</a></p>')
    return ('<!-- buttondown-editor-mode: fancy -->'
            f'<div style="max-width:600px;margin:0 auto;padding:8px 12px;background:#f6f3ec">{head}{"".join(parts)}{foot}</div>')


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


def patch(email_id, payload, key, opener=urllib.request.urlopen):
    req = urllib.request.Request(f"{API}/{email_id}", data=json.dumps(payload).encode("utf-8"), method="PATCH",
                                 headers={"Authorization": f"Token {key}", "Content-Type": "application/json",
                                          "User-Agent": "pinball-diff/0.3"})
    with opener(req, timeout=60) as resp:
        return json.load(resp)


def redraft(iss, key=None, opener=urllib.request.urlopen):
    """Rewrite this issue's Buttondown draft with the current subject and design. Drafts only."""
    key = key or os.environ.get("BUTTONDOWN_API_KEY")
    em = iss.get("email") or {}
    if em.get("status") != "draft" or not em.get("id"):
        return f"not redrafted: email is {em.get('status') or 'not created'}"
    if not key:
        return "not redrafted: no BUTTONDOWN_API_KEY"
    patch(em["id"], {"subject": subject(iss), "body": html(iss)}, key, opener)
    iss["email"]["redrafted_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    issue.save(iss)
    return f"redrafted in Buttondown: {em['id']}"


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
        made = post({"subject": subject(iss), "body": html(iss), "status": status}, key, opener)
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Buttondown refused the email ({err.code}): {err.read()[:400]!r}")
    iss["email"] = {"status": status, "id": made.get("id"),
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    issue.save(iss)
    return f"{'sent' if status == 'about_to_send' else 'drafted'} in Buttondown: {made.get('id')}"
