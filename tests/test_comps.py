"""Checks for the IFPA comp calendar. Run with:  python -m unittest discover tests -v

The fake responses follow the field names in IFPA's published API spec.
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pbmdiff import ifpa, issue, mail, site, store  # noqa: E402

TODAY = dt.date(2026, 10, 8)


def t(i, name, start, lat, lon, city, **kw):
    return {"tournament_id": i, "tournament_name": name, "event_name": "Main Tournament", "event_type": "Tournament",
            "location_name": kw.get("venue", "Venue"), "city": city, "stateprov": "VIC", "country_code": "AU",
            "event_start_date": start + "T00:00:00.000Z", "event_end_date": kw.get("end", start) + "T00:00:00.000Z",
            "latitude": str(lat), "longitude": str(lon), "private_flag": "Y" if kw.get("private") else "N",
            "ranking_system": kw.get("rank", "MAIN"), "qualifying_format": "Match Play", "finals_format": "Strike Knockout",
            "director_name": "Someone", "website": kw.get("site", "")}


EVENTS = {"Tournament": [t(1, "Parlour Monthly", "2026-10-10", -37.64, 144.95, "Campbellfield", venue="The Pinball Parlour"),
                         t(2, "Secret Squirrel", "2026-10-11", -37.81, 144.96, "Melbourne", private=True),
                         t(3, "NSW Open", "2026-10-17", -33.94, 151.14, "Arncliffe", end="2026-10-18"),
                         t(4, "Women's Night", "2026-10-12", -37.81, 144.96, "Melbourne", rank="WOMEN")],
          "League": [dict(t(5, "Thursday League", "2026-10-01", -38.15, 144.36, "Geelong", end="2026-12-10"),
                          event_type="League")]}


def fake_get(path, key, **params):
    rows = EVENTS["Tournament"] + EVENTS["League"]          # IFPA ignores the type filter
    return {"total_results": len(rows), "tournaments": rows}


class FlagTests(unittest.TestCase):
    def test_flags_in_any_form(self):
        for v in (True, "Y", "y", "1", 1, "true"):
            self.assertTrue(ifpa._yes(v), v)
        for v in (False, "N", "n", "0", 0, None, ""):
            self.assertFalse(ifpa._yes(v), v)


class VenueTests(unittest.TestCase):
    def test_venue_from_the_address_when_ifpa_leaves_it_blank(self):
        row = {"location_name": None, "address1": " Beetaloo Street",
               "raw_address": "Belconnen Bowling Club, Beetaloo St, Hawker, ACT, Australia"}
        self.assertEqual(ifpa._venue(row), "Belconnen Bowling Club")
        self.assertEqual(ifpa._venue({"location_name": None, "address1": "12 Smith St",
                                      "raw_address": "12 Smith St, Fitzroy, VIC"}), "")
        self.assertEqual(ifpa._venue({"location_name": "The Pinball Parlour"}), "The Pinball Parlour")

    def test_blank_formats_are_dropped(self):
        self.assertEqual(ifpa._format({"qualifying_format": "None", "finals_format": "Match Play"}), "Match Play")
        self.assertEqual(ifpa._format({"qualifying_format": "Not Set", "finals_format": "Strike Knockout"}), "Strike Knockout")


class CompTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tp = pathlib.Path(self.tmp.name)
        self.patches = [mock.patch.object(ifpa, "COMPS", tp / "comps.json"),
                        mock.patch.object(store, "EVENTS", tp / "events.jsonl"),
                        mock.patch.object(issue, "ISSUES", tp / "issues"),
                        mock.patch.object(site, "DIST", tp / "dist"),
                        mock.patch.object(issue, "today", lambda: TODAY)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_no_key_means_no_fetch(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(ifpa.fetch(today=TODAY, get=fake_get))
        self.assertEqual(ifpa.load(), [])

    def test_fetch_keeps_public_events_filed_by_zone(self):
        comps = ifpa.fetch(key="k", today=TODAY, get=fake_get, sleep=lambda s: None)
        self.assertEqual([c["id"] for c in comps], [5, 1, 4, 3])        # by start date; the private one is gone
        by_id = {c["id"]: c for c in ifpa.load()}
        self.assertEqual(by_id[1]["zone"], "vic")
        self.assertEqual(by_id[5]["zone"], "vic")
        self.assertEqual(by_id[3]["zone"], "nsw")
        self.assertTrue(by_id[4]["women"])
        self.assertEqual(by_id[1]["link"], "https://www.ifpapinball.com/tournaments/view.php?t=1")
        self.assertEqual(by_id[1]["format"], "Match Play / Strike Knockout")

    def test_between_includes_leagues_already_running(self):
        comps = ifpa.fetch(key="k", today=TODAY, get=fake_get, sleep=lambda s: None)
        week = ifpa.between(comps, "2026-10-08", "2026-10-15", {"vic"})
        self.assertEqual(sorted(c["id"] for c in week), [1, 4, 5])

    def test_site_and_email_show_comps(self):
        ifpa.fetch(key="k", today=TODAY, get=fake_get, sleep=lambda s: None)
        dist = site.build(on=TODAY)
        home = (dist / "index.html").read_text()
        self.assertIn("Comps in Victoria this week", home)
        self.assertIn("Parlour Monthly", home)
        self.assertNotIn("NSW Open", home)                              # not Victoria
        self.assertNotIn("Secret Squirrel", home)
        page = (dist / "comps" / "index.html").read_text()
        self.assertIn("NSW Open", page)
        self.assertIn("Thursday League", page)
        iss = issue.make({}, TODAY)
        md = mail.markdown(iss)
        self.assertIn("## Comps coming up", md)
        self.assertIn("[Parlour Monthly](https://www.ifpapinball.com/tournaments/view.php?t=1)", md)
        self.assertNotIn("NSW Open", md)
        self.assertIn("League", md)

    def test_a_week_with_comps_but_no_changes_still_sends(self):
        ifpa.fetch(key="k", today=TODAY, get=fake_get, sleep=lambda s: None)
        iss = issue.make({}, TODAY)
        issue.save(iss)
        import io
        sent = []
        opener = lambda req, timeout: sent.append(1) or io.BytesIO(b'{"id": "em_1"}')
        self.assertIn("drafted", mail.deliver(iss, key="k", opener=opener))
        self.assertEqual(mail.subject(iss), "3 comps coming up in Victoria")


if __name__ == "__main__":
    unittest.main()


class EnrichAndFeedTests(unittest.TestCase):
    def test_comps_take_the_pinball_map_venue_they_sit_on(self):
        venues = {101: ("The Saloon Barcade", -38.0283, 145.1092), 102: ("Somewhere Far", -38.2, 145.3)}
        comps = [{"id": 1, "venue": "", "lat": -38.02832, "lon": 145.10921, "name": "X"},     # a few metres away
                 {"id": 2, "venue": "Hall", "lat": -38.10, "lon": 145.20, "name": "Y"}]        # kilometres away
        out = ifpa.enrich(comps, venues)
        self.assertEqual((out[0]["venue"], out[0]["pbm_id"]), ("The Saloon Barcade", 101))
        self.assertEqual(out[1]["venue"], "Hall")
        self.assertNotIn("pbm_id", out[1])
        self.assertEqual(comps[0]["venue"], "")                       # the input is not changed

    def test_calendar_feed_is_valid_all_day_ical(self):
        c = {"id": 9, "name": "Monthly, with commas; and semis", "start": "2026-10-08", "end": "2026-10-09",
             "venue": "The Saloon Barcade", "city": "Edithvale", "state": "VIC", "format": "Match Play",
             "link": "https://www.ifpapinball.com/tournaments/view.php?t=9", "website": ""}
        text = ifpa.ics([c], "Pinball comps: Victoria", "20261005T000000Z")
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n"))
        self.assertIn("DTSTART;VALUE=DATE:20261008", text)
        self.assertIn("DTEND;VALUE=DATE:20261010", text)                 # all-day end is exclusive
        self.assertIn("SUMMARY:Monthly\\, with commas\; and semis", text)
        self.assertIn("UID:ifpa-9@pinballthisweek", text)
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))
