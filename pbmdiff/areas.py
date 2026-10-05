"""Where to look, and how to slice what comes back.

Two layers. FETCH is coverage: Pinball Map has no Australian regions beyond
nsw, brisbane and west-oz, so the submissions feed is asked for everything
within 250 miles of each of eleven points. Overlaps are fine; events are
deduplicated by id.

ZONES is how the digests are cut. Every event lands in exactly one zone, the
first in the list whose test it passes. Victoria is sliced because
Melbourne is Greater Melbourne, not Morwell: a Rowville player and a
Gippsland player want different lists. Other states are one zone each for
now and can be sliced the same way when someone there asks.

Greater Melbourne is approximated as 60 km around the CBD plus the
Mornington Peninsula. That takes in Werribee, Melton, Sunbury, Whittlesea,
Healesville, Pakenham and Frankston, and leaves out Geelong.
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


GREATER_MELBOURNE = within(-37.8136, 144.9631, 60)
MORNINGTON = within(-38.33, 144.95, 25)
GEELONG = within(-38.1499, 144.3617, 45)

ZONES = [
    # key, label, test(lat, lon). Order matters: first match wins.
    ("melbourne", "Greater Melbourne", lambda lat, lon: GREATER_MELBOURNE(lat, lon) or MORNINGTON(lat, lon)),
    ("geelong", "Geelong, the Bellarine and the Surf Coast", GEELONG),
    ("gippsland", "Gippsland", lambda lat, lon: in_victoria(lat, lon) and lon >= 145.2 and lat <= -37.2),
    ("northern-victoria", "Northern Victoria: Bendigo, Shepparton, the north east and the Mallee",
     lambda lat, lon: in_victoria(lat, lon) and lat > -37.2),
    ("western-victoria", "Western Victoria: Ballarat, the south west and the Wimmera",
     lambda lat, lon: in_victoria(lat, lon)),
]
# Outside Victoria each venue goes to the nearest of these centres, so
# Townsville is not swallowed by Cairns just because Cairns is listed first.
OTHER = [
    ("sydney", "Sydney, Canberra and the Hunter", -33.8688, 151.2093),
    ("brisbane", "Brisbane, Gold Coast and Sunshine Coast", -27.4698, 153.0251),
    ("perth", "Perth and the south west", -31.9523, 115.8613),
    ("adelaide", "Adelaide and South Australia", -34.9285, 138.6007),
    ("hobart", "Tasmania", -42.8821, 147.3272),
    ("darwin", "Darwin and the Top End", -12.4634, 130.8456),
    ("cairns", "Far North Queensland", -16.9186, 145.7781),
    ("townsville", "Townsville and the north", -19.2590, 146.8169),
    ("rockhampton", "Mackay and Central Queensland", -23.3791, 150.5100),
    ("alice", "Central Australia", -23.6980, 133.8807),
]
OTHER_KM = 900
ZONES += [(key, label, (lambda k: lambda lat, lon: _nearest_other(lat, lon) == k)(key)) for key, label, _, _ in OTHER]
LABELS = {key: label for key, label, _ in ZONES}
SHORT = {"melbourne": "Greater Melbourne", "geelong": "Geelong", "gippsland": "Gippsland",
         "northern-victoria": "Northern Vic", "western-victoria": "Western Vic", "sydney": "NSW and ACT",
         "brisbane": "South east Qld", "perth": "WA", "adelaide": "SA", "hobart": "Tasmania",
         "darwin": "Top End", "cairns": "Far North Qld", "townsville": "North Qld",
         "rockhampton": "Central Qld", "alice": "Central Australia"}


def _nearest_other(lat, lon):
    best = min(OTHER, key=lambda z: km_between(z[2], z[3], lat, lon))
    return best[0] if km_between(best[2], best[3], lat, lon) <= OTHER_KM else None


def zone_of(lat, lon):
    if lat is None or lon is None:
        return None
    for key, _, test in ZONES:
        if test(lat, lon):
            return key
    return None
