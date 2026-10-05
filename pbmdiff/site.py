"""Build the public website into dist/.

  /                       this week, every zone, Victoria first
  /zone/<key>/            one zone, the last four weeks
  /issues/                every email issue
  /issues/<date>/         one issue, as sent
  /about/                 what this is and where the data comes from
  /feed.xml               the issues as an Atom feed

Every venue links to its Pinball Map listing. Nothing here helps anyone find
somewhere to play; it says what changed, and sends people to Pinball Map to
look and to update.
"""
import datetime as dt
import html
import json
import pathlib
import shutil

from . import areas, digest, ifpa, issue, podcasts, render, store
from .config import ROOT, SITE

DIST = ROOT / "dist"
CSS_VERSION = __import__("hashlib").sha1((ROOT / "static" / "style.css").read_bytes()).hexdigest()[:8]
e = html.escape
FONTS = ("https://fonts.googleapis.com/css2?family=Doto:wght@900"
         "&family=Instrument+Sans:wght@400;600;700&display=swap")
FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Ccircle cx='16' cy='16' r='13' fill='%23ff7a1a'/%3E%3Ccircle cx='11.5' cy='11.5' r='3.5' "
           "fill='%23fff' fill-opacity='.75'/%3E%3C/svg%3E")


def u(path):
    return SITE["base_path"] + path


def absolute(path):
    return SITE["base_url"] + path


# ---------- pieces ----------

# machine id and full name -> the machine's page slug; filled in by build() before any page is written
MACHINE_PAGES = {"ids": {}, "names": {}}
# Pinball Map venue id -> [(machine name, image, slug)] for machines that landed there in the last year
# and have not left since; filled in by build()
VENUE_ARRIVALS = {}


def venue_arrivals(events, catalogue, until, days=365):
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=days)).isoformat()
    last = {}
    for ev in sorted(events.values(), key=lambda ev: (ev["date"], ev["id"])):
        if ev["type"] in ("machine_added", "machine_removed") and ev.get("machine_id") and ev.get("location_id"):
            last[(ev["location_id"], ev["machine_id"])] = ev
    out = {}
    for (vid, mid), ev in last.items():
        if ev["type"] != "machine_added" or ev["date"] < since:
            continue
        img = (catalogue.get(str(mid)) or {}).get("img")
        if img:
            out.setdefault(vid, []).append((ev["date"], ev["machine"], img, MACHINE_PAGES["ids"].get(mid)))
    return {vid: [x[1:] for x in sorted(v, reverse=True)[:4]] for vid, v in out.items()}


def machine_page_for(name, item=None):
    mid = ((item or {}).get("ids") or {}).get(name)
    slug = MACHINE_PAGES["ids"].get(mid) if mid else None
    return slug or MACHINE_PAGES["names"].get(name)


def machine(name, item=None):
    title, maker = render.split_machine(name)
    tail = f' <span class="mk">({e(maker)})</span>' if maker else ""
    flags = (item or {}).get("flags", {}).get(name, [])
    pills = "".join(f' <span class="pill">{e(f)}</span>' for f in flags)
    slug = machine_page_for(name, item)
    label = (f'<a class="m" href="{u("/machines/" + slug + "/")}">{e(title)}</a>' if slug
             else f'<span class="m">{e(title)}</span>')
    return f'{label}{tail}{pills}'


def machines(names, item=None):
    return render.join(machine(n, item) for n in names)


def what(item):
    k = item["kind"]
    if k == "new_venue":
        return f"New to the map with {machines(item['machines'], item)}." if item["machines"] else "New to the map."
    if k == "swap":
        return f"Swapped {machine(item['out'], item)} for {machine(item['in'], item)}."
    if k == "rotation":
        return (f'<span class="io"><b>In</b>{machines(item["machines"], item)}</span>'
                f'<span class="io"><b>Out</b>{machines(item["out"], item)}</span>')
    if k == "added":
        return f"Added {machines(item['machines'], item)}."
    if k == "removed":
        return f"Removed {machines(item['machines'], item)}."
    return f'{machine(item["machine"], item)}<blockquote class="said">{e(item["comment"])}</blockquote>'


def change(item):
    city = render.where(item)
    city_html = f' <span class="city">{e(city)}</span>' if city else ""
    by = item.get("by") or []
    credit = f" · via {e(render.join(by))}" if by else ""
    return (f'<li class="change"><span class="tag {render.tone(item)}">{e(render.label(item))}</span>'
            f'<div><div class="venue"><a href="{e(item["link"])}" '
            f'title="See or update this listing at Pinball Map">{e(item["location_name"])}</a>{city_html}</div>'
            f'<div class="what">{what(item)}</div></div>'
            f'<div class="meta">{e(render.day(item["date"]))}{credit}</div></li>')


def zone_block(z, heading_link=True, when=True, more=False):
    title = (f'<a href="{u("/zone/" + z["zone"] + "/")}">{e(z["label"])}</a>' if heading_link else e(z["label"]))
    when_html = f'<span class="when">{e(render.span(z["since"], z["until"]))}</span>' if when else ""
    if z["items"]:
        body = '<ul class="changes">' + "".join(change(i) for i in z["items"]) + "</ul>"
    else:
        body = '<p class="quiet">Nothing changed on the map.</p>'
    n = z["confirmations"]
    conf = (f'<p class="confirmed">Lineups confirmed unchanged at {n} venue{"s" if n != 1 else ""}.</p>' if n else "")
    more_html = (f'<p class="more"><a href="{u("/zone/" + z["zone"] + "/")}">Earlier weeks in {e(short(z["zone"]))}</a></p>'
                 if more else "")
    return (f'<section class="zone" id="{e(z["zone"])}"><header><h2>{title}</h2>{when_html}</header>'
            f"{body}{conf}{more_html}</section>")


def comp_row(c, show_zone=True):
    kind = render.comp_kind(c)
    kind_html = f' <span class="pill">{e(kind)}</span>' if kind else ""
    sub = f' <span class="city">{e(c["event"])}</span>' if c["event"] else ""
    venue = e(c["venue"])
    if c.get("pbm_id"):
        venue = (f'<a href="https://pinballmap.com/map?by_location_id={c["pbm_id"]}" '
                 f'title="See the machines here on Pinball Map">{venue}</a>')
    where = ", ".join(x for x in (venue, e(c["city"])) if x)
    st = c["zone"] or "other"
    zone = f' <span class="st st-{e(st)}">{e(short(c["zone"]) if c["zone"] else "Elsewhere")}</span>' if show_zone else ""
    more = f' · <a href="{e(c["website"])}">Event page</a>' if c["website"] else ""
    fmt = f'<span class="d">{e(c["format"])}</span>' if c["format"] else ""
    strip = ""
    landed = VENUE_ARRIVALS.get(c.get("pbm_id")) if SITE.get("machine_art") else None
    if landed:
        tiles = "".join(
            (f'<a href="{u("/machines/" + slug + "/")}" title="{e(name)}">' if slug else f'<span title="{e(name)}">')
            + f'<img src="{e(img)}" alt="{e(name)}" width="64" height="40" loading="lazy" decoding="async">'
            + ("</a>" if slug else "</span>") for name, img, slug in landed)
        strip = f'<div class="landed"><span class="lbl">Landed here lately</span><div class="tiles">{tiles}</div></div>'
    photo = (f'<img class="cphoto" src="{e(c["photo"])}" alt="" width="72" height="72" loading="lazy">'
             if c.get("photo") else "")
    return (f'<li class="comp{" has-photo" if photo else ""}" data-state="{e(st)}">'
            f'<span class="when">{e(render.comp_when(c))}</span>{photo}<div>'
            f'<a class="cname" href="{e(c["link"])}">{e(c["name"])}</a>{kind_html}{sub}'
            f'<div class="cwhere">{where}{zone}{more}</div>{fmt}{strip}</div></li>')


def comps_block(comps, since, until, title, empty, link=True):
    rows = "".join(comp_row(c, show_zone=False) for c in comps)
    body = f'<ul class="comps">{rows}</ul>' if comps else f'<p class="quiet">{e(empty)}</p>'
    more = (f'<p class="more"><a href="{u("/comps/")}">The comps calendar for Australia, and how to add it '
            f'to your own calendar</a></p>' if link else "")
    return (f'<section class="zone comps-zone"><header><h2>{e(title)}</h2>'
            f'<span class="when">{e(render.short_span(since, until))}</span></header>{body}{more}</section>')


STATE_ORDER = ["vic", "nsw", "qld", "sa", "wa", "tas", "nt"]


def _month_grid(year, month, comps_by_day, today):
    import calendar
    cal = calendar.Calendar(firstweekday=0)
    rows = []
    for week in cal.monthdatescalendar(year, month):
        cells = []
        for d in week:
            iso = d.isoformat()
            if d.month != month:
                cells.append('<td class="out"></td>')
                continue
            todays = comps_by_day.get(iso, [])
            cls = " past" if d < today else (" today" if d == today else "")
            marks = "".join(f'<a class="ev st-{e(c["zone"] or "other")}" data-state="{e(c["zone"] or "other")}" '
                            f'href="#d-{iso}" title="{e(c["name"])}"><span>{e(c["name"])}</span></a>' for c in todays)
            extra = '<span class="more-ev"></span>' if todays else ""
            num = (f'<a class="num" href="#d-{iso}">{d.day}</a>' if todays else f'<span class="num">{d.day}</span>')
            cells.append(f'<td class="day{cls}{" has" if todays else ""}">{num}<div class="evs">{marks}{extra}</div></td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f'<th scope="col"><span class="long">{n}</span><span class="short">{n[0]}</span></th>'
                   for n in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))
    title = dt.date(year, month, 1).strftime("%B %Y")
    return (f'<section class="month"><h2>{title}</h2><table class="cal"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>')


def comps_page(comps, on):
    until = on + dt.timedelta(days=ifpa.DAYS_AHEAD)
    by_day, counts = {}, {}
    for c in comps:
        d0 = max(dt.date.fromisoformat(c["start"]), on)
        d1 = min(dt.date.fromisoformat(c["end"] or c["start"]), d0 + dt.timedelta(days=3))
        d = d0
        while d <= d1:                          # multi-day events mark each day, up to four
            by_day.setdefault(d.isoformat(), []).append(c)
            d += dt.timedelta(days=1)
        counts[c["zone"] or "other"] = counts.get(c["zone"] or "other", 0) + 1
    months, y, m = [], on.year, on.month
    while (y, m) <= (until.year, until.month):
        months.append(_month_grid(y, m, by_day, on))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    states = [z for z in STATE_ORDER if counts.get(z)]
    chips = (f'<button type="button" data-pick="" aria-pressed="true">All <span class="n">{len(comps)}</span></button>'
             + "".join(f'<button type="button" data-pick="{z}" aria-pressed="false"><i class="sw st-{z}"></i>'
                       f'{e(short(z))} <span class="n">{counts[z]}</span></button>' for z in states))
    days = []
    for iso in sorted(by_day):
        cs = by_day[iso]
        if iso != max(cs[0]["start"], on.isoformat()) and all(iso != max(c["start"], on.isoformat()) for c in cs):
            continue                              # continuing days show in the grid, not as list headings
        starting = [c for c in cs if max(c["start"], on.isoformat()) == iso]
        days.append(f'<section class="dayblock" id="d-{iso}"><h3>{e(render.long_day(iso).rsplit(" ", 1)[0])}</h3>'
                    f'<ul class="comps">{"".join(comp_row(c) for c in starting)}</ul></section>')
    base = SITE["base_url"]
    feed_links = "".join(f'<li><a class="sub st-{z}-b" href="webcal://{e(base.split("://", 1)[1])}/comps/{z}.ics">'
                         f'<i class="sw st-{z}"></i>{e(areas.LABELS[z])}</a></li>' for z in states)
    feeds = (f'<section class="feeds"><h2>Put the comps in your own calendar</h2>'
             '<p>Subscribe once and every IFPA comp in your state shows up in your phone\'s calendar, '
             'kept up to date each day. Tap your state:</p>'
             f'<ul class="feedlist">{feed_links}<li><a class="sub" href="webcal://{e(base.split("://", 1)[1])}/comps/all.ics">'
             'All of Australia</a></li></ul>'
             '<details><summary>Using Google Calendar on a computer?</summary><p>In Google Calendar choose '
             '<b>Other calendars</b>, then <b>From URL</b>, and paste your state\'s address:</p><ul class="urls">'
             + "".join(f'<li><code>{e(base)}/comps/{z}.ics</code></li>' for z in states + ["all"]) +
             '</ul></details></section>')
    if not comps:
        body = ('<p class="quiet">No upcoming IFPA events are listed yet. '
                'They appear here as directors add them to the IFPA calendar.</p>')
    else:
        body = (f'<div class="state-pick" role="group" aria-label="Show comps in">{chips}</div>'
                f'<div class="months dots">{"".join(months)}</div>'
                f'<div class="agenda">{"".join(days)}</div>'
                '<p class="quiet" id="none-here" hidden>No IFPA comps listed here in the next two months.</p>'
                f'{feeds}'
                '<script>(function(){var bs=[].slice.call(document.querySelectorAll("[data-pick]"));'
                'function pick(s){bs.forEach(function(b){b.setAttribute("aria-pressed",String(b.dataset.pick===s))});'
                'document.querySelectorAll(".comp[data-state],.ev[data-state]").forEach(function(x){x.hidden=!!s&&x.dataset.state!==s});'
                'var any=false;document.querySelectorAll(".dayblock").forEach(function(d){var v=!!d.querySelector(".comp:not([hidden])");d.hidden=!v;any=any||v});'
                'document.getElementById("none-here").hidden=any;'
                'document.querySelector(".months").classList.toggle("dots",!s);'
                'cap();try{localStorage.setItem("comps-state",s)}catch(e){}}'
                'function cap(){var lim=matchMedia("(max-width:700px)").matches||document.querySelector(".months.dots")?6:4;'
                'document.querySelectorAll("td.day").forEach(function(td){var v=[].slice.call(td.querySelectorAll(".ev:not([hidden])"));'
                'v.forEach(function(x,i){x.classList.toggle("over",i>=lim)});var m=td.querySelector(".more-ev");'
                'if(m)m.textContent=v.length>lim?"+"+(v.length-lim):"";td.classList.toggle("has",v.length>0)})}'
                'cap();addEventListener("resize",cap);'
                'bs.forEach(function(b){b.addEventListener("click",function(){pick(b.dataset.pick)})});'
                'var q=(location.search.match(/state=(\\w+)/)||[])[1],s0=q;if(s0===undefined){try{s0=localStorage.getItem("comps-state")}catch(e){}}'
                'if(s0&&bs.some(function(b){return b.dataset.pick===s0}))pick(s0);})();</script>')
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">Comps</p>'
           f'<p class="lede">Every IFPA-sanctioned tournament and league in Australia, from today to {e(render.day(until.isoformat()))}.'
           '<small>From the IFPA calendar, updated every morning, with venues matched to Pinball Map so you can see '
           'what you will be playing on. Running a comp that is not here? Add it to the IFPA calendar and it appears the next day.</small></p>')
    return page("Comps", body, path="/comps/", description="Upcoming pinball tournaments and leagues across Australia, by month and state.",
                box_extra=box, current="comps")


def _mins(m):
    if not m:
        return ""
    return f"{m // 60} hr {m % 60} min" if m >= 60 else f"{m} min"


def episode_row(ep, shows, show_name=True):
    show = shows.get(ep["show"], {})
    who = f'<span class="show">{e(show.get("name", ""))}</span>' if show_name else ""
    meta = " · ".join(x for x in (render.day(ep["date"]), _mins(ep.get("minutes"))) if x)
    summary = f'<p class="sum">{e(ep["summary"])}</p>' if ep.get("summary") else ""
    img = ep.get("image") or show.get("image")
    art = (f'<a class="eart" href="{e(ep["link"])}" tabindex="-1" aria-hidden="true">'
           f'<img src="{e(img)}" alt="" width="72" height="72" loading="lazy" decoding="async"></a>' if img else "")
    return (f'<li class="ep{" has-art" if art else ""}" data-show="{e(ep["show"])}">{art}<div>{who}'
            f'<a class="etitle" href="{e(ep["link"])}">{e(ep["title"])}</a>'
            f'<span class="d">{e(meta)}</span>{summary}</div></li>')


def podcasts_page(data):
    shows = {sh["key"]: sh for sh in data.get("shows", [])}
    cards = []
    for sh in data.get("shows", []):
        n = sum(1 for ep in data.get("episodes", []) if ep["show"] == sh["key"])
        follow = [f'<a href="{e(sh["link"])}">Website</a>' if sh.get("link") else "",
                  f'<a href="{e(sh["apple"])}">Apple Podcasts</a>' if sh.get("apple") else "",
                  f'<a href="{e(sh["spotify"])}">Spotify</a>' if sh.get("spotify") else "",
                  f'<a href="{e(sh["feed"])}">RSS</a>']
        img = (f'<img src="{e(sh["image"])}" alt="" width="120" height="120" loading="lazy">' if sh.get("image") else "")
        cards.append(f'<article class="show-card">{img}<div><h2>{e(sh["name"])}</h2>'
                     f'<p>{e(sh.get("about", ""))}</p><p class="follow">{" · ".join(x for x in follow if x)}'
                     f'<span class="n"> · {n} episodes</span></p></div></article>')
    picks = ""
    if len(shows) > 1:
        picks = ('<div class="ed-pick" role="group" aria-label="Show"><span class="lbl">Show</span>'
                 '<button type="button" data-sh="" aria-pressed="true">Both</button>'
                 + "".join(f'<button type="button" data-sh="{e(k)}" aria-pressed="false">{e(v["name"])}</button>'
                           for k, v in shows.items()) + "</div>")
    eps = "".join(episode_row(ep, shows) for ep in data.get("episodes", []))
    script = ('<script>(function(){var b=[].slice.call(document.querySelectorAll("button[data-sh]"));'
              'b.forEach(function(x){x.addEventListener("click",function(){var s=x.dataset.sh;'
              'b.forEach(function(y){y.setAttribute("aria-pressed",String(y===x))});'
              'document.querySelectorAll(".ep").forEach(function(li){li.hidden=!!s&&li.dataset.show!==s})})})})();</script>'
              if picks else "")
    body = (f'<div class="shows">{"".join(cards)}</div>'
            f'<h2 class="eps-h">Latest episodes</h2>{picks}<ul class="eps">{eps}</ul>{script}'
            if shows else '<p class="quiet">No podcasts yet.</p>')
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">Podcasts</p>'
           '<p class="lede">Australian pinball, talked about by Australians.'
           '<small>Every episode links to the show itself, so the hosts get your listen. '
           'Making an Australian pinball podcast that is not here? Say so and it will be added.</small></p>')
    return page("Podcasts", body, path="/podcasts/", description="Australian pinball podcasts and their latest episodes.",
                box_extra=box, current="podcasts")


def signup():
    user = SITE.get("buttondown_username")
    if not user:
        return ('<div class="signup"><h2>The weekly email</h2>'
                '<p class="soon">Sign-ups open soon. Every Thursday, the week\'s changes for Victoria, '
                'in time to plan the weekend.</p></div>')
    picks = ('<label><input type="checkbox" name="tag" value="vic" checked> Victoria</label>'
             + "".join(f'<label><input type="checkbox" name="tag" value="{k}"> {e(areas.SHORT[k])}</label>'
                       for k, _ in areas.STATES))
    return (f'<form class="signup" action="https://buttondown.com/api/emails/embed-subscribe/{e(user)}" method="post">'
            '<h2>The weekly email</h2>'
            '<p>Every Thursday, the week\'s changes for Victoria, in time to plan the weekend. '
            'Free. One click to leave.</p>'
            '<div class="row"><label class="sr" for="em" hidden>Email address</label>'
            '<input id="em" type="email" name="email" required placeholder="you@example.com" autocomplete="email">'
            '<button type="submit">Subscribe</button></div>'
            f'<fieldset><legend>Which states? The email covers Victoria for now, and others will follow.</legend>'
            f'<div class="zones-pick">{picks}</div></fieldset>'
            '<input type="hidden" name="embed" value="1"></form>')


def short(label):
    """Chip-sized name for a zone, given its key or its label."""
    if label in areas.SHORT:
        return areas.SHORT[label]
    for key, full in areas.LABELS.items():
        if full == label:
            return areas.SHORT[key]
    return label.split(":")[0]


def chips(current, counts):
    here = ' aria-current="page"'
    links = [f'<a href="{u("/")}"{here if current == "home" else ""}>This week</a>']
    for z in issue.zone_order():
        n = counts.get(z, 0)
        if n == 0 and z not in SITE["email_zones"] and current != z:
            continue                              # quiet zones elsewhere stay off the strip
        cur = ' aria-current="page"' if current == z else ""
        links.append(f'<a href="{u("/zone/" + z + "/")}"{cur}>{e(short(z))}'
                     f'<span class="n">{n}</span></a>')
    return '<nav class="chips" aria-label="Zones">' + "".join(links) + "</nav>"


def page(title, body, *, path, description, box_extra="", nav="", current=None):
    full = f"{title} · {SITE['name']}" if title else SITE["name"]
    cur = lambda key: ' aria-current="page"' if current == key else ""
    return f"""<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full)}</title>
<meta name="description" content="{e(description)}">
<meta property="og:title" content="{e(full)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(absolute(path))}">
<link rel="canonical" href="{e(absolute(path))}">
<link rel="alternate" type="application/atom+xml" title="{e(SITE['name'])}" href="{u('/feed.xml')}">
<link rel="icon" href="{FAVICON}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="{u('/style.css')}?v={CSS_VERSION}">
</head>
<body>
<header class="box"><div class="wrap">
<nav class="topnav" aria-label="Site"><a class="home" href="{u('/')}">{e(SITE['name'])}</a>
<a href="{u('/comps/')}"{cur('comps')}>Comps</a><a href="{u('/machines/')}"{cur('machines')}>Machines</a><a href="{u('/podcasts/')}"{cur('podcasts')}>Podcasts</a><a href="{u('/issues/')}"{cur('issues')}>Emails</a><a href="{u('/about/')}"{cur('about')}>About</a></nav>
{box_extra}
</div></header>
<main><div class="wrap">
{nav}
{body}
</div></main>
<footer class="foot"><div class="wrap">
<p>Every venue links to its listing on <a href="https://pinballmap.com">Pinball Map</a>. If something is wrong, or you played something new, update it there. That is where this comes from.</p>
<p>Data from Pinball Map, CC BY-SA 4.0. Built from what Australian players submit; thanks to every one of them.</p>
<p>Comps from the <a href="https://www.ifpapinball.com">IFPA</a> calendar. Machine artwork from the <a href="https://opdb.org">Open Pinball Database</a>.</p>
</div></footer>
</body>
</html>
"""


# ---------- pages ----------

NEAR_DAYS = 60


def near_data(events, comps, on):
    """Everything the near-me box needs, rendered once here so the page has one renderer."""
    until = (on - dt.timedelta(days=1)).isoformat()
    since = (on - dt.timedelta(days=NEAR_DAYS - 1)).isoformat()
    recent = [ev for ev in store.between(events, since, until) if ev.get("lat") is not None]
    items = []
    for i in digest.build(recent)["items"]:
        if i.get("lat") is None:
            continue
        items.append({"d": i["date"], "lat": round(i["lat"], 4), "lon": round(i["lon"], 4),
                      "k": i["kind"], "html": change(i)})
    soon = ifpa.between(comps, on.isoformat(), (on + dt.timedelta(days=30)).isoformat())
    comp_rows = [{"d": c["start"], "e": c["end"] or c["start"], "lat": round(c["lat"], 4), "lon": round(c["lon"], 4),
                  "html": comp_row(c)} for c in soon if c.get("lat") is not None]
    # a geocoder made only of places that have pinball: every suburb Pinball Map has recorded a venue in
    seen = {}
    for ev in events.values():
        if ev.get("city") and ev.get("lat") is not None:
            key = ev["city"].strip().lower()
            cur = seen.get(key)
            if cur is None or ev["date"] > cur[3]:
                seen[key] = (ev["city"].strip(), round(ev["lat"], 3), round(ev["lon"], 3), ev["date"],
                             areas.zone_of(ev["lat"], ev["lon"]) or "")
    places = sorted(([v[0], v[1], v[2], v[4]] for v in seen.values()), key=lambda x: x[0].lower())
    return {"built": on.isoformat(), "since": since, "items": items, "comps": comp_rows, "places": places}


def near_box():
    return ('<section class="near" id="near" hidden>'
            '<header><h2 id="near-title">Near you</h2><button type="button" class="near-change" id="near-change">Change</button></header>'
            '<div class="near-controls">'
            '<label>Within <select id="near-km"><option value="10">10 km</option><option value="25">25 km</option>'
            '<option value="50" selected>50 km</option><option value="100">100 km</option><option value="250">250 km</option></select></label>'
            '<label>Last <select id="near-days"><option value="7">week</option><option value="30" selected>month</option>'
            '<option value="60">two months</option></select></label></div>'
            '<div id="near-body"></div></section>'
            '<section class="near-ask" id="near-ask">'
            '<h2>What changed near you?</h2>'
            '<p>Pick your suburb, or use your location. Nothing leaves your browser; this page just does the sums.</p>'
            '<form class="row" id="near-form" autocomplete="off">'
            '<input type="text" id="near-q" list="near-places" placeholder="Suburb or town" aria-label="Suburb or town">'
            '<datalist id="near-places"></datalist>'
            '<button type="submit">Show</button>'
            '<button type="button" class="ghost" id="near-geo">Use my location</button></form>'
            '<p class="near-note" id="near-note" hidden></p></section>')


NEAR_SCRIPT = r"""<script>(function(){
var ask=document.getElementById("near-ask"),box=document.getElementById("near"),body=document.getElementById("near-body"),
title=document.getElementById("near-title"),note=document.getElementById("near-note"),q=document.getElementById("near-q"),
km=document.getElementById("near-km"),days=document.getElementById("near-days"),data=null,here=null;
function load(cb){if(data)return cb();fetch(NEAR_URL).then(function(r){return r.json()}).then(function(d){data=d;
var dl=document.getElementById("near-places");d.places.forEach(function(p){var o=document.createElement("option");o.value=p[0];dl.appendChild(o)});cb()})}
function dist(a,b,c,d){var R=6371,x=(c-a)*Math.PI/180,y=(d-b)*Math.PI/180,s=Math.sin(x/2)*Math.sin(x/2)+Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(y/2)*Math.sin(y/2);return 2*R*Math.asin(Math.sqrt(s))}
function fmt(d){var t=new Date(d+"T00:00:00");return t.toLocaleDateString("en-AU",{weekday:"short",day:"numeric",month:"short"})}
function show(){if(!here||!data)return;var r=+km.value,n=+days.value,cut=new Date(Date.now()-n*864e5).toISOString().slice(0,10);
var items=data.items.filter(function(i){return i.d>=cut&&dist(here.lat,here.lon,i.lat,i.lon)<=r});
var comps=data.comps.filter(function(c){return dist(here.lat,here.lon,c.lat,c.lon)<=r});
title.textContent=(here.name?"Near "+here.name:"Near you")+" · "+r+" km";
var h="";if(comps.length)h+='<h3>Comps in the next 30 days</h3><ul class="comps">'+comps.map(function(c){return c.html}).join("")+"</ul>";
h+='<h3>Changes in the last '+(n==7?"week":n==30?"month":"two months")+"</h3>";
h+=items.length?'<ul class="changes">'+items.map(function(i){return i.html}).join("")+"</ul>":'<p class="quiet">Nothing has changed on the map within '+r+' km. Try a wider circle, or a longer stretch.</p>';
if(here.osm)h+='<p class="credit-osm">Suburb found with <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>.</p>';
body.innerHTML=h;box.hidden=false;ask.hidden=true;try{localStorage.setItem("near",JSON.stringify(here))}catch(e){}}
function pick(name){var key=name.trim().toLowerCase();if(!key)return;var p=data.places.filter(function(x){return x[0].toLowerCase()===key})[0]||
data.places.filter(function(x){return x[0].toLowerCase().indexOf(key)===0})[0];
if(p){here={name:p[0],lat:p[1],lon:p[2]};show();return}
note.hidden=false;note.textContent="Looking up "+name.trim()+"\u2026";
fetch("https://nominatim.openstreetmap.org/search?countrycodes=au&format=jsonv2&limit=1&q="+encodeURIComponent(name.trim()),{headers:{"Accept":"application/json"}})
.then(function(r){return r.json()}).then(function(rows){if(!rows.length)throw 0;var r=rows[0];
here={name:name.trim().replace(/\b\w/g,function(c){return c.toUpperCase()}),lat:+r.lat,lon:+r.lon,osm:true};note.hidden=true;show()})
.catch(function(){note.hidden=false;note.textContent="Could not find that suburb. Try the nearest town, or use your location."})}
document.getElementById("near-form").addEventListener("submit",function(ev){ev.preventDefault();load(function(){pick(q.value)})});
document.getElementById("near-geo").addEventListener("click",function(){if(!navigator.geolocation){note.hidden=false;note.textContent="Your browser does not share location. Type a suburb instead.";return}
navigator.geolocation.getCurrentPosition(function(pos){load(function(){here={name:"",lat:pos.coords.latitude,lon:pos.coords.longitude};show()})},
function(){note.hidden=false;note.textContent="Location was not shared. Type a suburb instead."},{timeout:8000})});
document.getElementById("near-change").addEventListener("click",function(){box.hidden=true;ask.hidden=false;q.focus();try{localStorage.removeItem("near")}catch(e){}});
km.addEventListener("change",show);days.addEventListener("change",show);
var saved=null;try{saved=JSON.parse(localStorage.getItem("near")||"null")}catch(e){}
if(saved&&saved.lat){here=saved;load(show)}
})();</script>"""


def home(weeks, counts, built_on, comps=()):
    total = render.count_changes(weeks)
    active = [z for z in weeks if z["items"]]
    quiet = [z for z in weeks if not z["items"]]
    short_span = render.short_span(weeks[0]["since"], weeks[0]["until"])
    box = (f'<h1 class="wordmark"><a href="{u("/")}">{e(SITE["name"])}</a></h1>'
           f'<p class="lede">{e(SITE["tagline"])}'
           f'<small>New venues, machines landing and leaving, and which machines need a tech. '
           f'Updated every morning from <a href="https://pinballmap.com">Pinball Map</a>.</small></p>'
           f'<p class="score"><b>{total}</b> change{"s" if total != 1 else ""} · {e(short_span)}</p>'
           f'<p class="dmd" id="dmd" aria-hidden="true" hidden></p>'
           f"{signup()}")
    soon_until = (built_on + dt.timedelta(days=7)).isoformat()
    soon = ifpa.between(list(comps), built_on.isoformat(), soon_until, set(SITE["email_zones"]))
    blocks = near_box()
    blocks += comps_block(soon, built_on.isoformat(), soon_until, "Comps in Victoria this week",
                          "No IFPA comps listed in Victoria in the next seven days.") if comps else ""
    pods = podcasts.load()
    fresh = podcasts.between(pods, (built_on - dt.timedelta(days=14)).isoformat(), built_on.isoformat())
    if fresh:
        shows = {sh["key"]: sh for sh in pods.get("shows", [])}
        blocks += (f'<section class="zone pods-zone"><header><h2>New on the podcasts</h2></header>'
                   f'<ul class="eps">{"".join(episode_row(ep, shows) for ep in fresh)}</ul>'
                   f'<p class="more"><a href="{u("/podcasts/")}">Every Australian pinball podcast</a></p></section>')
    blocks += "".join(zone_block(z, when=False, more=True) for z in active)
    if quiet:
        names = render.join(f'<a href="{u("/zone/" + z["zone"] + "/")}">{e(short(z["label"]))}</a>' for z in quiet)
        blocks += f'<p class="allquiet"><strong>Quiet on the map this week:</strong> {names}.</p>'
    blocks += f'<script>var NEAR_URL={json.dumps(u("/near.json"))};</script>' + NEAR_SCRIPT
    lines = []
    for z in active:
        for i in z["items"]:
            lines.append(attract_line(i, z["zone"]))
    attract = f'<script>var ATTRACT={json.dumps(lines[:40], ensure_ascii=False)};</script>' + ATTRACT_SCRIPT
    return page("", blocks, path="/", description=SITE["tagline"], box_extra=box + attract,
                nav=chips("home", counts), current="home")


def attract_line(i, zone):
    """One DMD line per change: terse, upper case, the way a backbox would say it."""
    where = (i["location_name"] + (", " + i["city"] if render.where(i) else "")).upper()
    k = i["kind"]
    if k == "new_venue":
        return f"NEW VENUE  {where}"
    if k == "swap":
        return f"{render.split_machine(i['in'])[0].upper()}  LANDS AT  {where}"
    if k == "rotation" or k == "added":
        return f"{render.split_machine(i['machines'][0])[0].upper()}  LANDS AT  {where}"
    if k == "removed":
        return f"{render.split_machine(i['machines'][0])[0].upper()}  LEAVES  {where}"
    status = {"amber": "NEEDS A TECH", "green": "FIXED", "note": "NOTE"}[i["status"]]
    return f"{render.split_machine(i['machine'])[0].upper()}  {status}  {where}"


ATTRACT_SCRIPT = r"""<script>(function(){
if(!ATTRACT.length||matchMedia("(prefers-reduced-motion: reduce)").matches)return;
var el=document.getElementById("dmd"),timer=null,tick=null,i=0,on=false;
function type(text,done){el.textContent="";var j=0;clearInterval(tick);tick=setInterval(function(){
el.textContent=text.slice(0,++j)+(j<text.length?"█":"");if(j>=text.length){clearInterval(tick);setTimeout(done,2600)}},28)}
function loop(){if(!on)return;type(ATTRACT[i%ATTRACT.length],function(){i++;loop()})}
function start(){if(on)return;on=true;el.hidden=false;document.body.classList.add("attract");loop()}
function stop(){clearTimeout(timer);if(on){on=false;clearInterval(tick);el.hidden=true;document.body.classList.remove("attract")}
timer=setTimeout(start,9000)}
["mousemove","keydown","scroll","touchstart","click"].forEach(function(e){addEventListener(e,stop,{passive:true})});
stop();
})();</script>"""


def zone_page(z, events, until, counts):
    weeks = []
    end = dt.date.fromisoformat(until)
    for n in range(4):
        weeks.append(issue.week(events, z, (end - dt.timedelta(days=7 * n)).isoformat()))
    label = areas.LABELS[z]
    box = (f'<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">{e(short(z))}</p>'
           f'<p class="lede">{e(label) + ". " if label != short(z) else ""}The last four weeks of changes on Pinball Map.</p>')
    body = "".join(zone_block({**w, "label": "Week to " + render.day(w["until"])}, heading_link=False) for w in weeks)
    return page(short(z), body, path=f"/zone/{z}/", description=f"What changed on Pinball Map in {label}.",
                box_extra=box, nav=chips(z, counts), current=z)


def issue_page(iss):
    zones = issue.email_zones(iss)
    n = render.count_changes(zones)
    box = (f'<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">{e(render.long_day(iss["date"]))}</p>'
           f'<p class="lede">The email for {e(render.span(iss["since"], iss["until"]))}. '
           f'{n} change{"s" if n != 1 else ""} across Victoria.</p>')
    active = [z for z in zones if z["items"]]
    quiet = [z for z in zones if not z["items"]]
    ic = issue.email_comps(iss)
    body = comps_block(ic, iss["date"], iss.get("comps_until", iss["date"]), "Comps coming up",
                       "No IFPA comps listed in Victoria.", link=False) if ic else ""
    body += "".join(zone_block(z, when=False) for z in active)
    if quiet:
        body += (f'<p class="allquiet"><strong>Quiet on the map:</strong> '
                 f'{render.join(e(short(z["label"])) for z in quiet)}.</p>')
    return page(render.long_day(iss["date"]), body, path=f"/issues/{iss['date']}/",
                description=f"{SITE['name']} for {render.long_day(iss['date'])}.", box_extra=box, current="issues")


def issues_page(dates):
    rows = []
    for d in dates:
        iss = issue.load(d)
        n = render.count_changes(issue.email_zones(iss))
        rows.append(f'<li><a href="{u("/issues/" + d + "/")}">{e(render.long_day(d))}</a>'
                    f'<span class="n">{n} change{"s" if n != 1 else ""}</span></li>')
    body = ('<div class="prose">' + ('<ul class="issues">' + "".join(rows) + "</ul>" if rows else
            '<p class="muted">The first email goes out on the next Thursday.</p>') + "</div>")
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">Past emails</p>'
           '<p class="lede">Every Thursday email, as it went out.</p>')
    return page("Past emails", body, path="/issues/", description="Every past email.", box_extra=box, current="issues")


import re as _re


def _edition(name):
    title, _ = render.split_machine(name)
    m = _re.search(r"\(([^()]*)\)\s*$", title)
    return m.group(1) if m else "Standard"


def _plain_title(name):
    title, _ = render.split_machine(name)
    return _re.sub(r"\s*\([^()]*\)\s*$", "", title).strip()


def slug(text):
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return _re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "machine"


def machine_groups(events, until, catalogue=None):
    """Every title that has ever landed or left, editions together, newest first.

    Editions are tied together by Pinball Map's own machine groups, so Stern's
    Godzilla Pro, Premium and LE share a page while Sega's 1998 Godzilla gets
    its own. Machines with no group stand alone; without a catalogue, the
    name is the fallback.
    """
    catalogue = catalogue or {}
    groups = {}
    for ev in events.values():
        if ev["type"] not in ("machine_added", "machine_removed") or not ev["machine"] or ev["date"] > until:
            continue
        base = digest.base_title(ev["machine"])
        if not base:
            continue
        info = catalogue.get(str(ev.get("machine_id"))) or {}
        key = f"g{info['group']}" if info.get("group") else (f"m{ev['machine_id']}" if info else f"t{base}")
        g = groups.setdefault(key, {"titles": {}, "events": [], "editions": set(), "makers": set(),
                                    "group_id": info.get("group")})
        plain = _plain_title(ev["machine"])
        g["titles"][plain] = g["titles"].get(plain, 0) + 1
        g["editions"].add(_edition(ev["machine"]))
        if ev.get("machine_id"):
            g.setdefault("edition_ids", {}).setdefault(_edition(ev["machine"]), ev["machine_id"])
        maker = render.split_machine(ev["machine"])[1]
        if maker:
            g["makers"].add(maker)
        g["events"].append(ev)
    for g in groups.values():
        # the shortest common name: "Cactus Canyon", not "Cactus Canyon Continued"
        g["title"] = min(g["titles"], key=lambda t: (len(t), -g["titles"][t]))
        g["events"].sort(key=lambda ev: (ev["date"], ev["id"]), reverse=True)
        g["machine_id"] = next((ev["machine_id"] for ev in g["events"] if ev["machine_id"]), None)
        g["latest"], g["first"] = g["events"][0]["date"], g["events"][-1]["date"]
        g["ins"] = sum(1 for ev in g["events"] if ev["type"] == "machine_added")
    ordered = sorted(groups.values(), key=lambda g: (g["latest"], len(g["events"])), reverse=True)
    names = {}
    for g in ordered:
        names.setdefault(slug(g["title"]), []).append(g)
    for base, gs in names.items():
        for g in gs:
            if len(gs) == 1:
                g["slug"] = base
            else:                                  # same name, different machines: say whose and when
                maker = sorted(g["makers"])[0] if g["makers"] else ""
                g["slug"] = slug(f"{g['title']} {maker}")
        seen = {}
        for g in gs:
            seen[g["slug"]] = seen.get(g["slug"], 0) + 1
            if seen[g["slug"]] > 1:
                g["slug"] = f"{g['slug']}-{seen[g['slug']]}"
    return ordered


def _editions_text(g):
    return " · ".join(sorted(g["editions"], key=lambda x: (x != "Standard", x)))


def _makers_text(g):
    makers = sorted({m.split(",")[0].strip() for m in g["makers"]})
    return ", ".join(makers)


def _move_row(ev):
    tone = "new" if ev["type"] == "machine_added" else "gone"
    pills = ""                       # on a title page "new release" would repeat on every row
    rare = " rare" if tone == "new" and any(f != "New release" for f in digest.flags(ev["machine"])) else ""
    zone = areas.zone_of(ev["lat"], ev["lon"])
    where = f' <span class="city">{e(ev["city"])}{", " + e(short(zone)) if zone else ""}</span>'
    link = f"https://pinballmap.com/map?by_location_id={ev['location_id']}"
    return (f'<li data-ed="{e(_edition(ev["machine"]))}" data-state="{e(zone or "other")}">'
            f'<span class="tag {tone}">{"In" if tone == "new" else "Out"}</span><div>'
            f'<span class="ed{rare}">{e(_edition(ev["machine"]))}</span>{pills} '
            f'{"at" if tone == "new" else "from"} '
            f'<a href="{e(link)}" title="See or update this listing at Pinball Map">{e(ev["location_name"])}</a>{where}'
            f'<span class="d">{e(render.day(ev["date"]))}</span></div></li>')


def _art(g, catalogue):
    """(edition, image url, width, height) for each edition we have art for, Pro and Standard first."""
    if not SITE.get("machine_art") or not catalogue:
        return []
    order = {"Standard": 0, "Pro": 1, "Premium": 2, "LE": 3}
    out = []
    for ed, mid in sorted((g.get("edition_ids") or {}).items(), key=lambda kv: (order.get(kv[0], 4), kv[0])):
        m = catalogue.get(str(mid)) or {}
        if m.get("img"):
            out.append((ed, m["img"], m.get("w") or 640, m.get("h") or 400))
    return out


def _now_link(g):
    """Pinball Map filtered to Australia: every edition when the machine has a group."""
    if g.get("group_id"):
        return f"https://pinballmap.com/map?by_machine_group_id={g['group_id']}&by_country=AU"
    if g["machine_id"]:
        return f"https://pinballmap.com/map?by_machine_id={g['machine_id']}&by_country=AU"
    return "https://pinballmap.com/map?by_country=AU"


def machines_page(groups, catalogue=None):
    rows = []
    for g in groups:
        n = len(g["events"])
        art = _art(g, catalogue)
        thumb = (f'<img class="thumb" src="{e(art[0][1])}" alt="" width="96" height="{round(96 * art[0][3] / art[0][2])}" '
                 f'loading="lazy" decoding="async">' if art else "")
        rows.append(f'<li class="title-row{" has-art" if art else ""}" data-name="{e(g["title"].lower())} {e(_makers_text(g).lower())}">{thumb}'
                    f'<a href="{u("/machines/" + g["slug"] + "/")}"><span class="t">{e(g["title"])}</span></a>'
                    f'<span class="mk">{e(_makers_text(g))}</span>'
                    f'<span class="sub">{e(_editions_text(g))} · {n} move{"s" if n != 1 else ""} · '
                    f'last {e(render.month(g["latest"]))}</span></li>')
    first = min((g["first"] for g in groups), default=None)
    since = f" since {render.month(first)}" if first else ""
    body = ('<div class="finder"><label for="q">Find a machine</label>'
            '<input id="q" type="search" placeholder="Godzilla, Pokémon, Twilight Zone" autocomplete="off"></div>'
            f'<p class="count" id="count">{len(groups)} titles have landed or left{e(since)}. Most recent first.</p>'
            f'<ul class="title-list">{"".join(rows)}</ul>'
            '<p class="quiet" id="none" hidden>Nothing by that name has moved on Pinball Map in Australia. '
            '<a href="https://pinballmap.com">Pinball Map</a> can tell you where it is now.</p>'
            '<script>(function(){var f=function(x){return x.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"")};'
            'var q=document.getElementById("q"),c=[].slice.call(document.querySelectorAll(".title-row")),'
            'n=document.getElementById("none"),k=document.getElementById("count"),k0=k.textContent;'
            'c.forEach(function(x){x._n=f(x.dataset.name)});q.addEventListener("input",function(){'
            'var t=f(q.value.trim()),s=0;c.forEach(function(x){var h=!t||x._n.indexOf(t)>-1;x.hidden=!h;if(h)s++;});'
            'n.hidden=s>0;k.textContent=t?s+" title"+(s==1?"":"s")+" match.":k0;});})();</script>')
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">Machines</p>'
           '<p class="lede">Every machine that has landed somewhere or left, across Australia, as recorded on Pinball Map. '
           'Pro, Premium and LE together, so you can follow where each edition went.'
           '<small>For where a machine is right now, each title links to Pinball Map.</small></p>')
    return page("Machines", body, path="/machines/", description="Which pinball machines have landed and left around Australia.",
                box_extra=box, current="machines")


def title_page(g, catalogue=None):
    by_year = {}
    for ev in g["events"]:
        by_year.setdefault(ev["date"][:4], []).append(ev)
    years = "".join(f'<section class="year"><h2>{y}</h2><ul class="moves">{"".join(_move_row(ev) for ev in evs)}</ul></section>'
                    for y, evs in by_year.items())
    n = len(g["events"])
    box = (f'<p class="wordmark" style="font-size:clamp(1.5rem,6vw,2.6rem)">{e(g["title"])}</p>'
           f'<p class="lede">{e(_makers_text(g))}. Editions seen: {e(_editions_text(g))}.'
           f'<small>{n} move{"s" if n != 1 else ""} in Australia on Pinball Map, '
           f'{g["ins"]} in and {n - g["ins"]} out, from {e(render.month(g["first"]))} to {e(render.month(g["latest"]))}.</small></p>'
           f'<p><a class="cta" href="{e(_now_link(g))}">Where it is now, on Pinball Map</a></p>')
    art = _art(g, catalogue)
    counts = {}
    for ev in g["events"]:
        counts[_edition(ev["machine"])] = counts.get(_edition(ev["machine"]), 0) + 1
    order = {"Standard": 0, "Pro": 1, "Premium": 2, "LE": 3}
    eds = sorted(counts, key=lambda x: (order.get(x, 4), x))
    gallery = ""
    if art:
        figs = "".join(f'<button type="button" class="art-pick" data-ed="{e(ed)}" aria-pressed="false" '
                       f'title="Show only the {e(ed)}"><img src="{e(src)}" alt="{e(g["title"])} {e(ed)} artwork" '
                       f'width="{w}" height="{h}" loading="lazy" decoding="async"><span class="cap">{e(ed)}</span></button>'
                       for ed, src, w, h in art)
        gallery = f'<div class="art">{figs}</div>'
    st_counts = {}
    for ev in g["events"]:
        z = areas.zone_of(ev["lat"], ev["lon"]) or "other"
        st_counts[z] = st_counts.get(z, 0) + 1
    states = [z for z in STATE_ORDER if st_counts.get(z)]
    picker = ""
    if len(eds) > 1:
        picker += ('<div class="ed-pick" role="group" aria-label="Edition"><span class="lbl">Edition</span>'
                   f'<button type="button" data-ed="" aria-pressed="true">All <span class="n">{len(g["events"])}</span></button>'
                   + "".join(f'<button type="button" data-ed="{e(ed)}" aria-pressed="false">{e(ed)} '
                             f'<span class="n">{counts[ed]}</span></button>' for ed in eds) + "</div>")
    if len(states) > 1:
        picker += ('<div class="ed-pick" role="group" aria-label="State"><span class="lbl">State</span>'
                   f'<button type="button" data-st="" aria-pressed="true">All</button>'
                   + "".join(f'<button type="button" data-st="{z}" aria-pressed="false"><i class="sw st-{z}"></i>'
                             f'{e(short(z))} <span class="n">{st_counts[z]}</span></button>' for z in states) + "</div>")
    script = ""
    if picker:
        script = ('<p class="quiet" id="none-here" hidden>No moves for that combination.</p>'
                  '<script>(function(){var ed="",st="";var eb=[].slice.call(document.querySelectorAll("button[data-ed]")),'
                  'sb=[].slice.call(document.querySelectorAll("button[data-st]"));'
                  'function show(){eb.forEach(function(x){x.setAttribute("aria-pressed",String(x.dataset.ed===ed))});'
                  'sb.forEach(function(x){x.setAttribute("aria-pressed",String(x.dataset.st===st))});'
                  'var any=false;document.querySelectorAll(".moves li").forEach(function(li){'
                  'li.hidden=(!!ed&&li.dataset.ed!==ed)||(!!st&&li.dataset.state!==st);any=any||!li.hidden});'
                  'document.querySelectorAll(".year").forEach(function(y){y.hidden=!y.querySelector("li:not([hidden])")});'
                  'document.getElementById("none-here").hidden=any}'
                  'eb.forEach(function(x){x.addEventListener("click",function(){'
                  'ed=(x.getAttribute("aria-pressed")=="true"&&x.dataset.ed)?"":x.dataset.ed;show()})});'
                  'sb.forEach(function(x){x.addEventListener("click",function(){'
                  'st=(x.getAttribute("aria-pressed")=="true"&&x.dataset.st)?"":x.dataset.st;'
                  'try{localStorage.setItem("comps-state",st)}catch(e){}show()})});'
                  'var s0="";try{s0=localStorage.getItem("comps-state")||""}catch(e){}'
                  'if(s0&&sb.some(function(x){return x.dataset.st===s0})){st=s0;show()}})();</script>')
    body = f'<p class="more"><a href="{u("/machines/")}">All machines</a></p>{gallery}{picker}{years}{script}'
    return page(g["title"], body, path=f"/machines/{g['slug']}/",
                description=f"Where {g['title']} has landed and left in Australia, edition by edition.",
                box_extra=box, current="machines")


def about_page():
    body = f"""<div class="prose">
<h2>What this is</h2>
<p>A weekly list of what changed on Pinball Map in Australia: new venues, machines landing and leaving, swaps, and notes from players about machines that need a tech or have been fixed. It exists so that people hear about the new game at the pub down the road, and so a Rowville player knows whether it is worth the drive to Campbellfield on Saturday.</p>
<h2>What it is not</h2>
<p>It is not a map and it will not help you find somewhere to play. <a href="https://pinballmap.com">Pinball Map</a> does that, and does it well. Every venue here links straight to its Pinball Map listing.</p>
<h2>Where it comes from</h2>
<p>Every change here was submitted to Pinball Map by a player. Once a day this site asks Pinball Map what changed around Australia, sorts it by area, and tidies it: a machine removed and a new edition of the same game added becomes a swap, and a new venue and its first machines become one line. Nothing is added by hand.</p>
<p>That means it is only as good as what people submit. If you played somewhere and the lineup was different, or a machine was off, update the listing on Pinball Map. It will be here the next morning and in Thursday's email.</p>
<h2>The states</h2>
<p>Changes are grouped by state, and every line names its suburb or town. The email covers Victoria for now; the other states are on the website, and the email will follow as each one gets busy enough to fill a week.</p>
<h2>Who</h2>
<p class="muted">Made by a Melbourne player. Contact: <a href="mailto:{e(SITE['contact'])}">{e(SITE['contact'])}</a>. The code is open on <a href="https://github.com/glenat-gif/pinball-diff">GitHub</a>. Data from Pinball Map under CC BY-SA 4.0.</p>
</div>"""
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">About</p>'
           f'<p class="lede">{e(SITE["tagline"])}</p>')
    return page("About", body, path="/about/", description="What this is and where the data comes from.",
                box_extra=box, current="about")


def feed(dates):
    entries = []
    for d in dates[:20]:
        iss = issue.load(d)
        n = render.count_changes(issue.email_zones(iss))
        url = absolute(f"/issues/{d}/")
        entries.append(f"<entry><title>{e(render.long_day(d))}: {n} changes</title><link href=\"{e(url)}\"/>"
                       f"<id>{e(url)}</id><updated>{d}T07:00:00+10:00</updated>"
                       f"<summary>What changed on Pinball Map in Victoria, {e(render.span(iss['since'], iss['until']))}.</summary></entry>")
    updated = f"{dates[0]}T07:00:00+10:00" if dates else "2026-10-01T07:00:00+10:00"
    return (f'<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{e(SITE['name'])}</title><link href=\"{e(absolute('/'))}\"/><id>{e(absolute('/'))}</id>"
            f"<updated>{updated}</updated>{''.join(entries)}</feed>\n")


def write(rel, text):
    path = DIST / rel.lstrip("/")
    if rel.endswith("/"):
        path = path / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build(on=None):
    on = on or issue.today()
    until = (on - dt.timedelta(days=1)).isoformat()
    events = store.load()
    catalogue = store.load_machines()
    groups = machine_groups(events, until, catalogue)
    MACHINE_PAGES["ids"].clear(); MACHINE_PAGES["names"].clear()
    for g in groups:
        for ev in g["events"]:
            if ev.get("machine_id"):
                MACHINE_PAGES["ids"][ev["machine_id"]] = g["slug"]
            MACHINE_PAGES["names"].setdefault(ev["machine"], g["slug"])
    VENUE_ARRIVALS.clear()
    VENUE_ARRIVALS.update(venue_arrivals(events, catalogue, until))
    weeks = [issue.week(events, z, until) for z in issue.zone_order()]
    counts = {w["zone"]: len(w["items"]) for w in weeks}
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    comps = ifpa.enrich(ifpa.load(), ifpa.venues_from_events(events))
    write("/", home(weeks, counts, on, comps))
    write("/near.json", json.dumps(near_data(events, comps, on), ensure_ascii=False, separators=(",", ":")))
    upcoming = ifpa.between(comps, on.isoformat(), "9999-12-31")
    write("/comps/", comps_page(upcoming, on))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for z in STATE_ORDER:
        write(f"/comps/{z}.ics", ifpa.ics([c for c in upcoming if c["zone"] == z],
                                          f"Pinball comps: {areas.LABELS[z]}", stamp))
    write("/comps/all.ics", ifpa.ics(upcoming, "Pinball comps: Australia", stamp))
    for z in issue.zone_order():
        write(f"/zone/{z}/", zone_page(z, events, until, counts))
    dates = issue.published_dates()
    for d in dates:
        write(f"/issues/{d}/", issue_page(issue.load(d)))
    write("/issues/", issues_page(dates))
    write("/machines/", machines_page(groups, catalogue))
    for g in groups:
        write(f"/machines/{g['slug']}/", title_page(g, catalogue))
    write("/podcasts/", podcasts_page(podcasts.load()))
    write("/about/", about_page())
    write("/feed.xml", feed(dates))
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    return DIST
