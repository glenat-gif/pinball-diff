"""Where to look, and how to slice what comes back.

Two layers. FETCH is coverage: Pinball Map has no Australian regions beyond
nsw, brisbane and west-oz, so the submissions feed is asked for everything
within 250 miles of each of eleven points. Overlaps are fine; events are
deduplicated by id.

ZONES is how the digests are cut: one per state. The scene is small enough
that a Victorian week is four or five lines, and every line names its town,
so a Gippsland player still sees Morwell. Victoria is drawn from the Murray,
so Albury, which plays as one town with Wodonga, counts as Victoria.
"""
import math

MILES = 250

FETCH = {
    # name: (lat, lon)
    "melbourne":   (-37.8136, 144.9631),
    "sydney":      (-33.8688, 151.2093),
    "brisbane":    (-27.4698, 153.0251),
    "perth":       (-31.9523, 115.8613),
    "adelaide":    (-34.9285, 138.6007),
    "hobart":      (-42.8821, 147.3272),
    "darwin":      (-12.4634, 130.8456),
    "cairns":      (-16.9186, 145.7781),
    "townsville":  (-19.2590, 146.8169),
    "rockhampton": (-23.3791, 150.5100),
    "alice":       (-23.6980, 133.8807),
}


def km_between(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def miles_between(lat1, lon1, lat2, lon2):
    return km_between(lat1, lon1, lat2, lon2) / 1.609344


def within(lat0, lon0, km):
    return lambda lat, lon: km_between(lat0, lon0, lat, lon) <= km


def in_victoria(lat, lon):
    """Victoria, with the Murray approximated as a staircase. Albury counts; it is one town."""
    if not (140.96 <= lon <= 150.0) or lat < -39.3:      # Wilsons Prom is the bottom; Tasmania is not Victoria
        return False
    if lon < 143.0:
        return lat <= -34.1
    if lon < 145.0:
        return lat <= -35.3
    if lon < 147.0:
        return lat <= -35.9
    return lat <= -36.5 - (lon - 147.0) * 0.33      # the straight line to Cape Howe


ZONES = [
    # key, label, test(lat, lon). Order matters: first match wins.
    ("vic", "Victoria", in_victoria),
]
# Outside Victoria each venue goes to the state of the nearest centre, so
# Townsville is not swallowed by Cairns, and Darwin and Alice are both NT.
OTHER = [
    ("nsw", -33.8688, 151.2093),       # Sydney
    ("qld", -27.4698, 153.0251),       # Brisbane
    ("qld", -16.9186, 145.7781),       # Cairns
    ("qld", -19.2590, 146.8169),       # Townsville
    ("qld", -23.3791, 150.5100),       # Rockhampton
    ("wa", -31.9523, 115.8613),        # Perth
    ("sa", -34.9285, 138.6007),        # Adelaide
    ("tas", -42.8821, 147.3272),       # Hobart
    ("nt", -12.4634, 130.8456),        # Darwin
    ("nt", -23.6980, 133.8807),        # Alice Springs
]
OTHER_KM = 900
STATES = [("nsw", "New South Wales and the ACT"), ("qld", "Queensland"), ("sa", "South Australia"),
          ("wa", "Western Australia"), ("tas", "Tasmania"), ("nt", "Northern Territory")]
ZONES += [(key, label, (lambda k: lambda lat, lon: _nearest_other(lat, lon) == k)(key)) for key, label in STATES]
LABELS = {key: label for key, label, _ in ZONES}
SHORT = {"vic": "Victoria", "nsw": "NSW and ACT", "qld": "Queensland", "sa": "SA", "wa": "WA",
         "tas": "Tasmania", "nt": "NT"}


def _nearest_other(lat, lon):
    best = min(OTHER, key=lambda z: km_between(z[1], z[2], lat, lon))
    return best[0] if km_between(best[1], best[2], lat, lon) <= OTHER_KM else None


def zone_of(lat, lon):
    if lat is None or lon is None:
        return None
    for key, _, test in ZONES:
        if test(lat, lon):
            return key
    return None
