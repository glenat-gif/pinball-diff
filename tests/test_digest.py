"""Checks for the feed handling and the digest rules. Run with:  python -m unittest discover tests -v

The fixture is a real week of Pinball Map submissions within 250 miles of
Melbourne, fetched 2 October 2026. It happens to contain a title swap, a new
country venue, a machine turned off, and a bare confirmation, which is
everything the rules are for.
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pbmdiff import areas, digest, store  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SUBS = json.loads((FIX / "melbourne_week.json").read_text(encoding="utf-8"))["user_submissions"]


class StoreTests(unittest.TestCase):
    def test_every_real_type_is_kept_except_scores(self):
        kept = [store.normalise(s) for s in SUBS]
        self.assertTrue(all(kept))
        self.assertIsNone(store.normalise({"id": 1, "submission_type": "new_msx", "created_at": "2026-10-01T00:00:00.000-07:00"}))

    def test_dates_are_melbourne_dates(self):
        # 16:35 Pacific on 1 Oct is 10:35 on 2 Oct in Melbourne.
        self.assertEqual(store.local_date("2026-10-01T16:35:36.967-07:00"), "2026-10-02")
        self.assertEqual(store.local_date("2026-09-29T05:00:35.588-07:00"), "2026-09-29")

    def test_store_deduplicates_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(store, "EVENTS", pathlib.Path(tmp) / "events.jsonl"):
                self.assertEqual(store.add(SUBS), 8)
                self.assertEqual(store.add(SUBS), 0)
                self.assertEqual(store.add(SUBS + [{**SUBS[0], "id": 1}]), 1)
                self.assertEqual(len(store.load()), 9)


class ZoneTests(unittest.TestCase):
    def zone(self, lat, lon):
        return areas.zone_of(lat, lon)

    def test_real_week_lands_where_a_local_would_put_it(self):
        by_city = {s["city_name"]: self.zone(s["lat"], s["lon"]) for s in SUBS}
        self.assertEqual(by_city["Melbourne"], "melbourne")
        self.assertEqual(by_city["South Melbourne"], "melbourne")
        self.assertEqual(by_city["Morwell"], "gippsland")
        self.assertEqual(by_city["Albury"], "northern-victoria")

    def test_greater_melbourne_edges(self):
        for name, lat, lon in [("Werribee", -37.90, 144.66), ("Melton", -37.68, 144.58), ("Sunbury", -37.58, 144.73),
                               ("Healesville", -37.65, 145.52), ("Pakenham", -38.07, 145.48), ("Frankston", -38.14, 145.12),
                               ("Rosebud", -38.35, 144.90), ("Sorrento", -38.34, 144.74), ("Rowville", -37.93, 145.23)]:
            self.assertEqual(self.zone(lat, lon), "melbourne", name)
        self.assertEqual(self.zone(-38.15, 144.36), "geelong")            # Geelong is not Melbourne
        self.assertEqual(self.zone(-38.34, 144.32), "geelong")            # Torquay
        self.assertEqual(self.zone(-38.63, 145.72), "gippsland")          # Inverloch
        self.assertEqual(self.zone(-38.45, 145.24), "gippsland")          # Cowes
        self.assertEqual(self.zone(-37.56, 143.85), "western-victoria")   # Ballarat
        self.assertEqual(self.zone(-38.38, 142.48), "western-victoria")   # Warrnambool
        self.assertEqual(self.zone(-36.33, 141.65), "northern-victoria")  # Nhill
        self.assertEqual(self.zone(-36.76, 144.28), "northern-victoria")  # Bendigo
        self.assertEqual(self.zone(-34.19, 142.16), "northern-victoria")  # Mildura

    def test_border_towns_go_to_the_right_state(self):
        self.assertEqual(self.zone(-35.28, 149.13), "sydney")             # Canberra
        self.assertEqual(self.zone(-34.93, 138.60), "adelaide")
        self.assertEqual(self.zone(-34.17, 140.75), "adelaide")           # Renmark
        self.assertEqual(self.zone(-35.12, 147.37), "sydney")             # Wagga Wagga
        self.assertEqual(self.zone(-37.07, 149.90), "sydney")             # Eden, NSW far south coast
        self.assertEqual(self.zone(-28.00, 153.43), "brisbane")           # Gold Coast
        self.assertEqual(self.zone(-42.88, 147.33), "hobart")
        self.assertEqual(self.zone(-41.43, 147.14), "hobart")             # Launceston
        self.assertEqual(self.zone(-39.13, 146.37), "gippsland")          # Wilsons Prom
        self.assertIsNone(self.zone(None, None))

    def test_distance_matches_pinball_maps_own(self):
        morwell = next(s for s in SUBS if s["city_name"] == "Morwell")
        lat, lon = areas.FETCH["melbourne"]
        self.assertAlmostEqual(areas.miles_between(lat, lon, morwell["lat"], morwell["lon"]), morwell["distance"], delta=1)


class DigestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = [store.normalise(s) for s in SUBS]
        cls.digest = digest.build(cls.events)
        cls.items = {(i["kind"], i["location_name"]): i for i in cls.digest["items"]}

    def test_new_venue_folds_in_its_first_machine(self):
        item = self.items[("new_venue", "Morwell Hotel")]
        self.assertEqual(item["machines"], ["Ghostbusters (Pro) (Stern, 2016)"])
        self.assertNotIn(("added", "Morwell Hotel"), self.items)

    def test_swap_pairs_removal_with_addition_of_same_title(self):
        item = self.items[("swap", "Railway Hotel South Melbourne")]
        self.assertEqual(item["out"], "Cactus Canyon (Bally, 1998)")
        self.assertEqual(item["in"], "Cactus Canyon (Remake Special) (Chicago Gaming, 2021)")
        self.assertNotIn(("removed", "Railway Hotel South Melbourne"), self.items)
        self.assertNotIn(("added", "Railway Hotel South Melbourne"), self.items)

    def test_condition_notes_become_status(self):
        fortress = [i for i in self.digest["items"] if i["kind"] == "condition" and i["location_name"] == "Fortress Melbourne"]
        self.assertEqual(len(fortress), 2)
        venom = next(i for i in fortress if i["machine"].startswith("Venom"))
        self.assertEqual(venom["status"], "amber")
        self.assertEqual(venom["comment"], "Machine was turned off")

    def test_confirmations_are_counted_not_listed(self):
        self.assertEqual(self.digest["confirmations"], 1)
        self.assertFalse([i for i in self.digest["items"] if i["kind"] == "venue_confirmed"])

    def test_ranking_puts_new_venue_first(self):
        self.assertEqual(self.digest["items"][0]["kind"], "new_venue")

    def test_markdown_links_every_venue_to_its_pinball_map_listing(self):
        md = digest.to_markdown(self.digest, "Melbourne", "test")
        for i in self.digest["items"]:
            self.assertIn(f"https://pinballmap.com/map?by_location_id={i['location_id']}", md)
        self.assertIn("CC BY-SA 4.0", md)
        self.assertIn("dolphin61", md)

    def test_in_and_out_at_one_venue_is_a_rotation(self):
        base = {"date": "2026-10-01", "location_id": 2, "location_name": "Great Northern", "city": "Kempsey",
                "lat": -31.0, "lon": 152.8, "comment": "", "user": "parazio"}
        evs = [{**base, "id": 1, "type": "machine_added", "machine_id": 1, "machine": "Metallica (Premium) (Stern, 2024)"},
               {**base, "id": 2, "type": "machine_removed", "machine_id": 2, "machine": "Deadpool (Pro) (Stern, 2018)"}]
        d = digest.build(evs)
        self.assertEqual([i["kind"] for i in d["items"]], ["rotation"])
        md = digest.to_markdown(d, "x", "y")
        self.assertIn("brought in Metallica (Premium) (Stern, 2024) and moved out Deadpool (Pro) (Stern, 2018)", md)

    def test_grouped_additions_credit_contributors(self):
        extra = [{"id": 9001 + n, "type": "machine_added", "date": "2026-10-01", "location_id": 1, "location_name": "Test Bar",
                  "city": "Fitzroy", "lat": -37.8, "lon": 144.98, "machine_id": n, "machine": f"Game {n} (Stern, 2025)",
                  "comment": "", "user": "someone"} for n in range(3)]
        d = digest.build(extra)
        self.assertEqual(d["items"][0]["kind"], "added")
        self.assertEqual(d["items"][0]["by"], ["someone"])
        self.assertIn("3 new machines", digest.to_markdown(d, "x", "y"))


class TitleTests(unittest.TestCase):
    def test_editions_are_ignored(self):
        self.assertEqual(digest.base_title("Godzilla (Premium) (Stern, 2021)"), digest.base_title("Godzilla (Pro) (Stern, 2021)"))
        self.assertEqual(digest.base_title("Cactus Canyon (Remake Special) (Chicago Gaming, 2021)"), "cactus canyon")
        self.assertNotEqual(digest.base_title("Jaws (Premium)"), digest.base_title("Venom (LE)"))

    def test_status_heuristics(self):
        self.assertEqual(digest.status_of("Machine was turned off"), "amber")
        self.assertEqual(digest.status_of("right flipper weak"), "amber")
        self.assertEqual(digest.status_of("Fixed, plays great"), "green")
        self.assertEqual(digest.status_of("No issues, all working"), "green")
        self.assertEqual(digest.status_of("Not working, out of order"), "amber")
        self.assertEqual(digest.status_of("Note, machine not playable - for display only"), "amber")
        self.assertEqual(digest.status_of("Set to 3 ball"), "note")


if __name__ == "__main__":
    unittest.main()
