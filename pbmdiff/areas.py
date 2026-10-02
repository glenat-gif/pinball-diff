"""Where to look.

Pinball Map has no Australian regions beyond nsw, brisbane and west-oz, and
will not add more. The submissions feed can instead be asked for everything
within 250 miles of a point, so Australia is covered by a handful of circles
around the places people actually play. Overlaps are fine: events are
deduplicated by their Pinball Map id.

A digest is built per area, from the events that fall inside its circle.
"""
import math

MILES = 250

AREAS = {
    # name: (label, lat, lon)
    "melbourne":    ("Melbourne and regional Victoria", -37.8136, 144.9631),
    "sydney":       ("Sydney, Canberra and the Hunter", -33.8688, 151.2093),
    "brisbane":     ("Brisbane, Gold Coast and Sunshine Coast", -27.4698, 153.0251),
    "perth":        ("Perth and the south west", -31.9523, 115.8613),
    "adelaide":     ("Adelaide and South Australia", -34.9285, 138.6007),
    "hobart":       ("Tasmania", -42.8821, 147.3272),
    "darwin":       ("Darwin and the Top End", -12.4634, 130.8456),
    "cairns":       ("Far North Queensland", -16.9186, 145.7781),
    "townsville":   ("Townsville and Mackay", -19.2590, 146.8169),
    "rockhampton":  ("Central Queensland", -23.3791, 150.5100),
    "alice":        ("Central Australia", -23.6980, 133.8807),
}


def miles_between(lat1, lon1, lat2, lon2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def inside(area, lat, lon):
    _, alat, alon = AREAS[area]
    return lat is not None and lon is not None and miles_between(alat, alon, lat, lon) <= MILES
