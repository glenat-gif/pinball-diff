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

from . import areas, issue, render, store
from .config import SITE

API = "https://api.buttondown.com/v1/emails"
LEAD = {"new_venue": "a new venue in {where}", "swap": "a swap at {venue}", "rotation": "a rotation at {venue}",
        "added": "new at {venue}", "removed": "a farewell at {venue}"}


def site_url(path=""):
    return SITE["base_url"] + path


STATE_CODE = {"vic": "VIC", "nsw": "NSW", "qld": "QLD", "sa": "SA", "wa": "WA", "tas": "TAS", "nt": "NT"}


def _headline(item, zone, local):
    """A short phrase and a score. Venue first for venues, machine first for arrivals, and the
    state after the place every time, so a reader anywhere knows where it is."""
    title = lambda n: render.split_machine(n)[0]
    st = STATE_CODE.get(zone, "")
    where = (item.get("city") or item["location_name"]) + (f", {st}" if st else "")
    venue = item["location_name"] + (f", {st}" if st else "")
    flags = item.get("flags") or {}
    weight = lambda n: sum(issue.HIGHLIGHT_WEIGHT.get(f, 0) for f in flags.get(n, []))
    flagged = sorted((n for n in flags if flags[n]), key=weight, reverse=True)   # rarest first
    k = item["kind"]
    if k == "new_venue":
        place = f"{item['location_name']} in {where}" if item.get("city") else venue
        return (f"New venue: {place}", 12 if local else 11)
    if k in ("added", "rotation", "swap"):
        names = flagged or item.get("machines") or [item.get("in")]
        name = title(names[0]) if names and names[0] else None
        if not name:
            return None
        score = (10 if local else 9) + (weight(names[0]) if flagged else 0)   # home state wins a tie, no more
        return (f"{name} lands at {venue}" if local else f"{name} lands in {where}", score)
    if k == "removed":
        return (f"{title(item['machines'][0])} leaves {venue}", 2 if local else 1)
    if k == "condition" and item.get("status") == "green":
        return (f"{title(item['machine'])} fixed at {venue}", 2 if local else 1)
    if k == "condition" and item.get("status") == "amber":
        return (f"{title(item['machine'])} needs a tech at {venue}", 1)
    return None


def headline_label(text):
    """(label, tone) for the thing a headline is about. A rotation's headline is about the machine
    that landed, so its card says Landed; the machine that left is detail for the row below."""
    if text.startswith("New venue"):
        return "New venue", "venue"
    if " lands " in text:
        return "Landed", "new"
    if " leaves " in text:
        return "Gone", "gone"
    if " fixed at " in text:
        return "Good news", "good"
    if " needs a tech " in text:
        return "Needs a tech", "trouble"
    return "Changed", "swap"


def ranked(iss):
    """The week's items as (headline, score, item), best first."""
    heads, home = [], issue.home_zone()
    for z in iss["zones"]:
        if z["zone"] not in SITE["email_zones"]:
            continue
        for item in z["items"]:
            h = _headline(item, z["zone"], z["zone"] == home)
            if h and h[1] > 0:
                item.setdefault("zone", z["zone"])
                heads.append((h[0], h[1], item))
    heads.sort(key=lambda h: -h[1])
    return heads


def subject(iss):
    """Lead with the best thing that happened, never with a count."""
    heads = [(t, sc) for t, sc, _ in ranked(iss)]
    for c in issue.email_comps(iss, issue.home_zone())[:2]:
        when = render.day(c["start"]).split(" ", 1)[0]       # Thu
        heads.append((f"{c['venue'] or c['name']} comp {when}", 4))
    heads.sort(key=lambda h: -h[1])
    if not heads:
        return "This week in Australian pinball"
    if len(heads) > 1 and heads[1][1] >= 9:          # a second arrival or venue, never a departure or a comp
        second = heads[1][0]
        second = second[0].lower() + second[1:] if second.startswith("New venue") else second
        both = f"{heads[0][0]}, and {second}"
        if len(both) <= 100:
            return both
    return heads[0][0]


def hero(iss, zone=None):
    """The item to lead the email with. Nationally, the best-ranked arrival or venue that has
    artwork. For one state, the best thing there with artwork, even a machine needing a tech."""
    for text, score, item in ranked(iss):
        if zone is None and score < 9:
            break
        if zone is not None and item.get("zone") != zone:
            continue
        if art_for(item):
            return text, item
    return None


def _tagged(zone):
    return f"'{zone}' in subscriber.tags"


def hero_branches(iss):
    """[(zone or None, condition, not-condition, (text, item))]: one hero per state that has one,
    in email order, then the national pick. Rendered as a Buttondown if/elif chain so each reader
    sees the lead for the first state they ticked, and the national lead if theirs is quiet."""
    out, earlier = [], []
    for z in SITE["email_zones"]:
        h = hero(iss, z)
        if not h:
            continue
        cond = " and ".join([_tagged(z)] + [f"'{e}' not in subscriber.tags" for e in earlier])
        anti = " or ".join([f"'{z}' not in subscriber.tags"] + [_tagged(e) for e in earlier])
        out.append((z, cond, anti, h))
        earlier.append(z)
    nat = hero(iss)
    if nat:
        cond = " and ".join(f"'{e}' not in subscriber.tags" for e in earlier) or "True"
        anti = " or ".join(_tagged(e) for e in earlier) or "False"
        out.append((None, cond, anti, nat))
    return out


def _machines(names, item=None):
    return render.join(_machine(n, item) for n in names)


def _machine(name, item=None):
    return name


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


def sections(iss):
    """(zone, items, comps) per email state in email order, then the states with nothing at all."""
    active, quiet = [], []
    for z in issue.email_zones(iss):
        comps = issue.email_comps(iss, z["zone"])
        (active if z["items"] or comps else quiet).append((z, z["items"], comps))
    return active, [z for z, _, _ in quiet]


def markdown(iss):
    active, quiet = sections(iss)
    home = areas.SHORT[issue.home_zone()]
    out = ["<!-- buttondown-editor-mode: plaintext -->",
           f"What changed in pinball across Australia, {render.span(iss['since'], iss['until'])}. "
           f"{home} first, then every other state.", ""]
    for z, items, comps in active:
        out += [f"## {z['label']}", ""]
        if items:
            out += [line(i) for i in items] + [""]
        if comps:
            out += [f"**Comps this week in {areas.SHORT[z['zone']]}**", ""] + [comp_line(c) for c in comps] + [""]
    hi = issue.highlights(iss)
    if hi:
        out += ["## Around Australia", ""] + [line(h) + f" _{areas.SHORT[h['zone']]}_" for h in hi] + [""]
    out += [f"**[Pinball near you]({site_url('/')})**: type your suburb on the site for changes and comps within 50 km.", ""]
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
TONE = {"new": "#b84c00", "venue": "#1b6f8f", "swap": "#5b3fd6", "trouble": "#c0254f", "good": "#23824a", "gone": "#7a7382", "note": "#655e6e"}


def _h_machine(name, item=None):
    title, maker = render.split_machine(name)
    tail = f' <span style="color:#655e6e">({_e(maker)})</span>' if maker else ""
    return f'<b>{_e(title)}</b>{tail}'


def notable(item):
    """The one flag worth saying about a change, for the hero and the highlight cards: a new
    release or a rare edition. The edition itself is already in the machine's name."""
    best, score = "", 0
    for flags in (item.get("flags") or {}).values():
        for f in flags:
            w = issue.HIGHLIGHT_WEIGHT.get(f, 0)
            if w > score and f != "Premium":
                best, score = f, w
    return best


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


_CATALOGUE = None


def _catalogue():
    """Pinball Map machine id (as a string) -> catalogue record with the OPDB image; loaded once."""
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = store.load_machines() or {}
    return _CATALOGUE


def art_for(item, limit=6):
    """[(machine id, image url, name, leaving, width, height)] for the machines a change mentions,
    arrivals first."""
    if not SITE.get("machine_art"):
        return []
    cat = _catalogue()
    k = item["kind"]
    if k == "swap":
        names = [(item["in"], False), (item["out"], True)]
    elif k == "condition":
        names = [(item["machine"], False)]
    else:
        gone = k == "removed"
        names = [(n, gone) for n in item.get("machines") or []] + [(n, True) for n in item.get("out") or []]
    ids = item.get("ids") or {}
    out, seen = [], set()
    for name, leaving in names:
        mid = ids.get(name)
        m = cat.get(str(mid)) if mid else None
        img = (m or {}).get("img")
        if not img or img in seen:
            continue
        seen.add(img)
        out.append((mid, img, name, leaving, int(m.get("w") or 640), int(m.get("h") or 400)))
        if len(out) == limit:
            break
    return out


def _tile(t, w, h, margin="0"):
    mid, img, name, leaving, _, _ = t
    dim = "opacity:.45;" if leaving else ""
    return (f'<a href="https://pinballmap.com/map?by_machine_id={mid}&amp;by_country=AU" title="{_e(name)}" style="text-decoration:none">'
            f'<img src="{_e(img)}" alt="{_e(name)}" width="{w}" height="{h}" '
            f'style="display:inline-block;width:{w}px;height:{h}px;object-fit:cover;border-radius:5px;margin:{margin};border:0;{dim}"></a>')


def _h_art(item, skip_first=False):
    tiles = art_for(item)[1 if skip_first else 0:]
    return f'<div>{"".join(_tile(t, 72, 45, "7px 6px 0 0") for t in tiles)}</div>' if tiles else ""


def _pill(label, colour):
    return (f'<span style="display:inline-block;font:800 10px/1.7 Arial,sans-serif;letter-spacing:1px;text-transform:uppercase;'
            f'color:{colour};border:1px solid {colour};border-radius:9px;padding:0 7px;margin-bottom:4px">{_e(label)}</span>')


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
    label, colour = render.label(item), TONE[render.tone(item)]
    tiles = art_for(item)
    if not tiles:
        return _h_row(label, colour, f"{venue}<br>{_h_what(item)}")
    left = _tile(tiles[0], 96, 60)
    body = f"{_pill(label, colour)}<br>{venue}<br>{_h_what(item)}{_h_art(item, skip_first=True)}"
    return (f'<tr><td style="padding:12px 0;border-bottom:1px solid #e2dccf;vertical-align:top;width:104px">{left}</td>'
            f'<td style="padding:12px 0 12px 10px;border-bottom:1px solid #e2dccf;vertical-align:top;font:15px/1.5 Arial,sans-serif;color:#1b1720">'
            f'{body}</td></tr>')


def _hero_pill(text):
    label, tone = headline_label(text)
    return label, TONE[tone]


def _h_hero(text, item, zone):
    """The week's lead: the backglass large on a dark panel, then the headline and the change."""
    t = art_for(item)[0]
    _, img, name, _, w, h = t
    if w / h >= 640 / 360:            # wide: fill the width
        iw, ih = 640, round(640 * h / w)
    else:                             # square or tall: fill the height
        iw, ih = round(360 * w / h), 360
    city = render.where(item)
    venue = f'<a href="{_e(item["link"])}" style="color:#1b1720;font-weight:700">{_e(item["location_name"])}</a>'
    venue += f' <span style="color:#655e6e">{_e(city)}</span>' if city else ""
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-top:18px">'
            f'<tr><td align="center" style="background:#120e18;border-radius:10px;padding:16px 0">'
            f'<a href="https://pinballmap.com/map?by_machine_id={t[0]}&amp;by_country=AU" style="text-decoration:none">'
            f'<img src="{_e(img)}" alt="{_e(name)}" width="{iw}" height="{ih}" '
            f'style="display:block;width:{iw}px;max-width:100%;height:auto;border:0;border-radius:6px"></a></td></tr></table>'
            f'<div style="margin:12px 0 0">{_pill(*_hero_pill(text))} '
            f'<span style="font:800 10px/1.7 Arial,sans-serif;letter-spacing:1px;text-transform:uppercase;color:#655e6e">&nbsp;{_e(areas.SHORT[zone])}'
            f'{" &middot; " + _e(notable(item)) if notable(item) else ""}</span>'
            f'<div style="font:800 22px/1.25 Arial,sans-serif;margin-top:4px">'
            f'<a href="{_e(item["link"])}" style="color:#1b1720;text-decoration:none">{_e(text)}</a></div>'
            f'<div style="font:15px/1.5 Arial,sans-serif;color:#1b1720;margin-top:6px">'
            f'{"" if item["kind"] == "new_venue" else venue + "<br>"}{_h_what(item)}</div></div>')


def _h_comp(c):
    """One tight line per comp: name, then where, format and the event page in muted type."""
    where = ", ".join(x for x in (c["venue"], c["city"]) if x)
    bits = [_e(x) for x in (where, c.get("format")) if x]
    if c["website"]:
        bits.append(f'<a href="{_e(c["website"])}" style="color:#5b3fd6">Event page</a>')
    body = (f'<a href="{_e(c["link"])}" style="color:#1b1720;font-weight:700">{_e(c["name"])}</a> '
            f'<span style="color:#655e6e;font-size:13px">{" · ".join(bits)}</span>')
    return (f'<tr><td style="padding:7px 0;border-bottom:1px solid #eee9df;vertical-align:top;width:104px">'
            f'<span style="font:800 11px/1.8 Arial,sans-serif;letter-spacing:1px;text-transform:uppercase;color:#b84c00">'
            f'{_e(render.comp_when(c))}</span></td>'
            f'<td style="padding:7px 0 7px 10px;border-bottom:1px solid #eee9df;vertical-align:top;font:14px/1.45 Arial,sans-serif;color:#1b1720">'
            f'{body}</td></tr>')


def _h_sub(title):
    return (f'<tr><td colspan="2" style="padding:14px 0 2px;font:800 11px/1.8 Arial,sans-serif;letter-spacing:1px;'
            f'text-transform:uppercase;color:#655e6e">{_e(title)}</td></tr>')


def _h_section(title, rows):
    return (f'<h2 style="font:700 18px/1.3 Arial,sans-serif;color:#1b1720;margin:28px 0 4px;padding-bottom:6px;'
            f'border-bottom:2px solid #1b1720">{_e(title)}</h2>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%">{"".join(rows)}</table>')


def html(iss):
    """The email as its own page: the backbox header, then the week."""
    zones = issue.email_zones(iss)
    active, quiet = sections(iss)
    branches = hero_branches(iss)
    parts = []
    if branches:
        chain = ""
        for i, (zone, cond, _, (text, item)) in enumerate(branches):
            zone_of = item["zone"]
            chain += ("{% if " if i == 0 else "{% elif ") + cond + " %}" + _h_hero(text, item, zone_of)
        parts.append(chain + "{% endif %}")
    shown = {}                                   # item -> the conditions under which a reader did NOT see it as the hero
    for _, _, anti, (_, item) in branches:
        shown.setdefault(id(item), []).append(anti)
    for z, items, comps in active:
        rows = []
        for i in items:
            row = _h_item(i)
            for anti in shown.get(id(i), []):    # nested ifs: Django templates have no parentheses
                row = "{% if " + anti + " %}" + row + "{% endif %}"
            rows.append(row)
        if not rows and not comps:
            continue
        if comps:
            rows.append(_h_sub(f"Comps this week in {areas.SHORT[z['zone']]}"))
            rows += [_h_comp(c) for c in comps]
        parts.append(_h_section(z["label"], rows))
    if quiet:
        parts.append(f'<p style="font:15px/1.5 Arial,sans-serif;color:#655e6e;margin:18px 0 0">Quiet on the map in '
                     f'{_e(render.join(areas.SHORT[z["zone"]] for z in quiet))}: nothing changed this week.</p>')
    hi = issue.highlights(iss)
    if hi:
        parts.append(_h_section("Around Australia", [_h_item(h, areas.SHORT[h["zone"]]) for h in hi]))
    parts.append(
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:22px auto 0"><tr><td style="background:#ff7a1a;border-radius:6px">'
        f'<a href="{_e(site_url("/"))}" style="display:inline-block;padding:11px 20px;font:700 15px Arial,sans-serif;color:#1b0c00;text-decoration:none">'
        f'<span style="color:#1b0c00">Pinball near you &rarr;</span></a></td></tr></table>'
        f'<p style="font:13px/1.5 Arial,sans-serif;color:#655e6e;text-align:center;margin:8px 0 0">'
        f'Type your suburb on the site for changes and comps within 50 km.</p>')
    eps = iss.get("episodes") or []
    if eps:
        rows = [_h_row("Episode", "#b84c00", f'<span style="color:#655e6e">{_e(ep["show_name"])}</span><br>'
                       f'<a href="{_e(ep["link"])}" style="color:#1b1720;font-weight:700">{_e(ep["title"])}</a>') for ep in eps]
        parts.append(_h_section("On the podcasts", rows))
    span = render.span(iss["since"], iss["until"])
    n = render.count_changes(zones)
    # The wordmark is an image so dark-mode mail apps cannot invert it; under it, one quiet line.
    head = (f'<a href="{_e(site_url("/"))}" style="display:block"><img src="{_e(site_url("/email-head.png"))}" width="640" height="117" '
            f'alt="PINBALL THIS WEEK" style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:10px"></a>'
            f'<div style="font:14px/1.5 Arial,sans-serif;color:#655e6e;margin:10px 0 0">{_e(span)} &middot; '
            f'{n} change{"" if n == 1 else "s"} across Australia</div>')
    foot = (f'<p style="font:13px/1.5 Arial,sans-serif;color:#655e6e;margin:30px 0 0;padding-top:14px;border-top:1px solid #e2dccf">'
            f'Every venue links to its Pinball Map listing. If something is wrong, or you played something new, '
            f'update it there and it will be in next week\'s email.<br>'
            f'Data from <a href="https://pinballmap.com" style="color:#655e6e">Pinball Map</a>, CC BY-SA 4.0. '
            f'Comps from the IFPA calendar. '
            + ('Machine artwork from the <a href="https://opdb.org" style="color:#655e6e">Open Pinball Database</a>. ' if SITE.get("machine_art") else "") +
            f'<a href="{_e(site_url("/issues/"))}" style="color:#655e6e">Past emails</a> &middot; '
            f'<a href="{_e(site_url("/about/"))}" style="color:#655e6e">About</a></p>')
    return ('<!-- buttondown-editor-mode: fancy -->'
            f'<div style="max-width:640px;margin:0 auto;padding:8px 12px;background:#f6f3ec">{head}{"".join(parts)}{foot}</div>')


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
