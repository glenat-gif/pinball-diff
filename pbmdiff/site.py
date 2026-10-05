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

from . import areas, digest, issue, render, store
from .config import ROOT, SITE

DIST = ROOT / "dist"
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

def machine(name, item=None):
    title, maker = render.split_machine(name)
    tail = f' <span class="mk">({e(maker)})</span>' if maker else ""
    flags = (item or {}).get("flags", {}).get(name, [])
    pills = "".join(f' <span class="pill">{e(f)}</span>' for f in flags)
    return f'<span class="m">{e(title)}</span>{tail}{pills}'


def machines(names, item=None):
    return render.join(machine(n, item) for n in names)


def what(item):
    k = item["kind"]
    if k == "new_venue":
        return f"New to the map with {machines(item['machines'], item)}." if item["machines"] else "New to the map."
    if k == "swap":
        return f"Swapped {machine(item['out'])} for {machine(item['in'], item)}."
    if k == "rotation":
        return (f'<span class="io"><b>In</b>{machines(item["machines"], item)}</span>'
                f'<span class="io"><b>Out</b>{machines(item["out"])}</span>')
    if k == "added":
        return f"Added {machines(item['machines'], item)}."
    if k == "removed":
        return f"Removed {machines(item['machines'])}."
    return f'{machine(item["machine"])}<blockquote class="said">{e(item["comment"])}</blockquote>'


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


def signup():
    user = SITE.get("buttondown_username")
    vic = [(z, areas.LABELS[z]) for z in SITE["email_zones"]]
    if not user:
        return ('<div class="signup"><h2>The weekly email</h2>'
                '<p class="soon">Sign-ups open soon. Every Thursday, the week\'s changes for Victoria, '
                'in time to plan the weekend.</p></div>')
    picks = "".join(f'<label><input type="checkbox" name="tag" value="{e(k)}" checked> {e(short(k))}</label>'
                    for k, l in vic)
    picks += '<label><input type="checkbox" name="tag" value="other-states"> Other states, when they start</label>'
    return (f'<form class="signup" action="https://buttondown.com/api/emails/embed-subscribe/{e(user)}" method="post">'
            '<h2>The weekly email</h2>'
            '<p>Every Thursday, the week\'s changes for Victoria, in time to plan the weekend. '
            'Free. One click to leave.</p>'
            '<div class="row"><label class="sr" for="em" hidden>Email address</label>'
            '<input id="em" type="email" name="email" required placeholder="you@example.com" autocomplete="email">'
            '<button type="submit">Subscribe</button></div>'
            f'<fieldset><legend>Which parts do you care about?</legend><div class="zones-pick">{picks}</div></fieldset>'
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
<link rel="stylesheet" href="{u('/style.css')}">
</head>
<body>
<header class="box"><div class="wrap">
<nav class="topnav" aria-label="Site"><a class="home" href="{u('/')}">{e(SITE['name'])}</a>
<a href="{u('/machines/')}"{cur('machines')}>Machines</a><a href="{u('/issues/')}"{cur('issues')}>Past emails</a><a href="{u('/about/')}"{cur('about')}>About</a></nav>
{box_extra}
</div></header>
<main><div class="wrap">
{nav}
{body}
</div></main>
<footer class="foot"><div class="wrap">
<p>Every venue links to its listing on <a href="https://pinballmap.com">Pinball Map</a>. If something is wrong, or you played something new, update it there. That is where this comes from.</p>
<p>Data from Pinball Map, CC BY-SA 4.0. Built from what Australian players submit; thanks to every one of them.</p>
</div></footer>
</body>
</html>
"""


# ---------- pages ----------

def home(weeks, counts, built_on):
    total = render.count_changes(weeks)
    active = [z for z in weeks if z["items"]]
    quiet = [z for z in weeks if not z["items"]]
    short_span = render.short_span(weeks[0]["since"], weeks[0]["until"])
    box = (f'<h1 class="wordmark"><a href="{u("/")}">{e(SITE["name"])}</a></h1>'
           f'<p class="lede">{e(SITE["tagline"])}'
           f'<small>New venues, machines landing and leaving, and what is playing badly. '
           f'Updated every morning from <a href="https://pinballmap.com">Pinball Map</a>.</small></p>'
           f'<p class="score"><b>{total}</b> change{"s" if total != 1 else ""} · {e(short_span)}</p>'
           f"{signup()}")
    blocks = "".join(zone_block(z, when=False, more=True) for z in active)
    if quiet:
        names = render.join(f'<a href="{u("/zone/" + z["zone"] + "/")}">{e(short(z["label"]))}</a>' for z in quiet)
        blocks += f'<p class="allquiet"><strong>Quiet on the map this week:</strong> {names}.</p>'
    return page("", blocks, path="/", description=SITE["tagline"], box_extra=box,
                nav=chips("home", counts), current="home")


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
    body = "".join(zone_block(z, when=False) for z in active)
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


MACHINE_DAYS = 90


def _edition(name):
    title, _ = render.split_machine(name)
    m = __import__("re").search(r"\(([^()]*)\)\s*$", title)
    return m.group(1) if m else "Standard"


def _plain_title(name):
    title, _ = render.split_machine(name)
    return __import__("re").sub(r"\s*\([^()]*\)\s*$", "", title).strip()


def machine_groups(events, until):
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=MACHINE_DAYS - 1)).isoformat()
    groups = {}
    for ev in store.between(events, since, until):
        if ev["type"] not in ("machine_added", "machine_removed") or not ev["machine"]:
            continue
        key = digest.base_title(ev["machine"])
        g = groups.setdefault(key, {"title": _plain_title(ev["machine"]), "maker": render.split_machine(ev["machine"])[1],
                                    "machine_id": ev["machine_id"], "events": [], "editions": set()})
        g["editions"].add(_edition(ev["machine"]))
        g["events"].append(ev)
    for g in groups.values():
        g["events"].sort(key=lambda ev: (ev["date"], ev["id"]), reverse=True)
        g["machine_id"] = g["events"][0]["machine_id"] or g["machine_id"]
        g["latest"] = g["events"][0]["date"]
    return sorted(groups.values(), key=lambda g: (g["latest"], len(g["events"])), reverse=True)


def machines_page(events, until):
    groups = machine_groups(events, until)
    cards = []
    for g in groups:
        rows = []
        for ev in g["events"][:8]:
            tone = "new" if ev["type"] == "machine_added" else "gone"
            flags = [f for f in digest.flags(ev["machine"]) if f == "New release"] if ev["type"] == "machine_added" else []
            pills = "".join(f' <span class="pill">{e(f)}</span>' for f in flags)
            rare = " rare" if ev["type"] == "machine_added" and any(f != "New release" for f in digest.flags(ev["machine"])) else ""
            zone = areas.zone_of(ev["lat"], ev["lon"])
            where = f' <span class="city">{e(ev["city"])}{", " + e(short(zone)) if zone else ""}</span>'
            link = f"https://pinballmap.com/map?by_location_id={ev['location_id']}"
            rows.append(f'<li><span class="tag {tone}">{"In" if tone == "new" else "Out"}</span><div>'
                        f'<span class="ed{rare}">{e(_edition(ev["machine"]))}</span>{pills} '
                        f'{"at" if tone == "new" else "from"} '
                        f'<a href="{e(link)}" title="See or update this listing at Pinball Map">{e(ev["location_name"])}</a>{where}'
                        f'<span class="d">{e(render.day(ev["date"]))}</span></div></li>')
        now = f"https://pinballmap.com/map?by_machine_id={g['machine_id']}" if g["machine_id"] else "https://pinballmap.com"
        eds = " · ".join(sorted(g["editions"], key=lambda x: (x != "Standard", x)))
        cards.append(f'<article class="title-card" data-name="{e(g["title"].lower())} {e(g["maker"].lower())}">'
                     f'<h2>{e(g["title"])} <span class="mk">{e(g["maker"])}</span></h2>'
                     f'<p class="eds">Editions seen moving: {e(eds)}</p>'
                     f'<ul class="moves">{"".join(rows)}</ul>'
                     f'<p class="now"><a href="{e(now)}">Where it is now, on Pinball Map</a></p></article>')
    body = ('<div class="finder"><label for="q">Find a machine</label>'
            '<input id="q" type="search" placeholder="Godzilla, Pokémon, Twilight Zone" autocomplete="off"></div>'
            f'<p class="count" id="count">{len(groups)} titles moved in the last {MACHINE_DAYS} days.</p>'
            + "".join(cards) +
            '<p class="quiet" id="none" hidden>Nothing by that name has moved lately. Pinball Map can tell you where it is now.</p>'
            '<script>(function(){var q=document.getElementById("q"),c=[].slice.call(document.querySelectorAll(".title-card")),'
            'n=document.getElementById("none"),k=document.getElementById("count");q.addEventListener("input",function(){'
            'var t=q.value.trim().toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,""),s=0;c.forEach(function(x){'
            'var hit=!t||x.dataset.name.normalize("NFD").replace(/[\u0300-\u036f]/g,"").indexOf(t)>-1;x.hidden=!hit;if(hit)s++;});'
            'n.hidden=s>0;k.textContent=s+" title"+(s==1?"":"s")+(t?" match.":" moved lately.");});})();</script>')
    box = ('<p class="wordmark" style="font-size:clamp(1.6rem,6vw,2.6rem)">Machines</p>'
           '<p class="lede">Every machine that landed somewhere or left, across Australia, in the last three months. '
           'Pro, Premium and LE together, so you can see which edition went where.'
           '<small>For where a machine is right now, each title links to Pinball Map.</small></p>')
    return page("Machines", body, path="/machines/", description="Which pinball machines have landed and left around Australia lately.",
                box_extra=box, current="machines")


def about_page():
    body = f"""<div class="prose">
<h2>What this is</h2>
<p>A weekly list of what changed on Pinball Map in Australia: new venues, machines landing and leaving, swaps, and notes from players about machines that are playing badly or have been fixed. It exists so that people hear about the new game at the pub down the road, and so a Rowville player knows whether it is worth the drive to Campbellfield on Saturday.</p>
<h2>What it is not</h2>
<p>It is not a map and it will not help you find somewhere to play. <a href="https://pinballmap.com">Pinball Map</a> does that, and does it well. Every venue here links straight to its Pinball Map listing.</p>
<h2>Where it comes from</h2>
<p>Every change here was submitted to Pinball Map by a player. Once a day this site asks Pinball Map what changed around Australia, sorts it by area, and tidies it: a machine removed and a new edition of the same game added becomes a swap, and a new venue and its first machines become one line. Nothing is added by hand.</p>
<p>That means it is only as good as what people submit. If you played somewhere and the lineup was different, or a machine was off, update the listing on Pinball Map. It will be here the next morning and in Thursday's email.</p>
<h2>The areas</h2>
<p>Victoria is split five ways: Greater Melbourne, Geelong and the Surf Coast, Gippsland, Northern Victoria, and Western Victoria. Each other state is one area for now. If you want yours split, say so.</p>
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
    weeks = [issue.week(events, z, until) for z in issue.zone_order()]
    counts = {w["zone"]: len(w["items"]) for w in weeks}
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy(ROOT / "static" / "style.css", DIST / "style.css")
    write("/", home(weeks, counts, on))
    for z in issue.zone_order():
        write(f"/zone/{z}/", zone_page(z, events, until, counts))
    dates = issue.published_dates()
    for d in dates:
        write(f"/issues/{d}/", issue_page(issue.load(d)))
    write("/issues/", issues_page(dates))
    write("/machines/", machines_page(events, until))
    write("/about/", about_page())
    write("/feed.xml", feed(dates))
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    return DIST
