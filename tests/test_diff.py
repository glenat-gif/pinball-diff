"""Checks for the diff and the digest rules. Run with:  python -m unittest discover tests -v

The fixtures are two synthetic days for Victoria, built to mirror real
activity-feed rows: a title swap at one venue, a new country venue, a machine
turned off, a repair, a venue that vanished, and bare confirmations.
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pbmdiff import diff, digest, snapshot  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class DiffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = snapshot.normalise(fx("lmx_day1.json"), fx("locations_day1.json"), "2026-09-28")
        cls.new = snapshot.normalise(fx("lmx_day2.json"), fx("locations_day2.json"), "2026-10-01")
        cls.events = diff.diff(cls.old, cls.new)
        cls.digest = digest.build(cls.events, cls.old, cls.new)
        cls.items = {(i["kind"], i["location_name"]): i for i in cls.digest["items"]}

    def kinds(self):
        return sorted(e["type"] for e in self.events)

    def test_raw_events_are_complete(self):
        self.assertEqual(self.kinds(), ["condition", "condition", "machine_added", "machine_added", "machine_added",
                                        "machine_added", "machine_removed", "machine_removed", "venue_added",
                                        "venue_confirmed", "venue_confirmed", "venue_removed"])

    def test_unchanged_venue_produces_nothing(self):
        self.assertFalse([e for e in self.events if e["location_name"] == "The Pinball Parlour" and e["type"] != "venue_confirmed"])

    def test_new_venue_folds_in_its_first_machine(self):
        item = self.items[("new_venue", "Morwell Hotel")]
        self.assertEqual(item["machines"], ["Ghostbusters (Pro) (Stern, 2016)"])
        self.assertNotIn(("added", "Morwell Hotel"), self.items)

    def test_swap_pairs_removal_with_addition_of_same_title(self):
        item = self.items[("swap", "Railway Hotel South Melbourne")]
        self.assertEqual(item["out"], "Cactus Canyon (Bally, 1998)")
        self.assertEqual(item["in"], "Cactus Canyon (Remake Special) (Chicago Gaming, 2021)")
        self.assertNotIn(("removed", "Railway Hotel South Melbourne"), self.items)

    def test_additions_group_per_venue(self):
        item = self.items[("added", "Pinball Paradise")]
        self.assertEqual(len(item["machines"]), 2)

    def test_condition_notes_become_status(self):
        venom = self.items[("condition", "Pinball Paradise")]
        self.assertEqual(venom["status"], "amber")
        self.assertEqual(venom["comment"], "Machine was turned off")
        addams = self.items[("condition", "Edithvale Hotel")]
        self.assertEqual(addams["status"], "green")

    def test_old_condition_notes_are_not_repeated(self):
        comments = [e["comment"] for e in self.events if e["type"] == "condition"]
        self.assertNotIn("Plays great, freshly waxed", comments)
        self.assertNotIn("Left flipper weak, Thing hand not grabbing", comments)

    def test_vanished_venue_lists_what_it_had(self):
        item = self.items[("venue_gone", "Bar X")]
        self.assertEqual(item["machines"], ["Iron Maiden (Pro)"])
        self.assertNotIn(("removed", "Bar X"), self.items)

    def test_confirmations_are_counted_not_listed(self):
        self.assertEqual(self.digest["confirmations"], 2)
        self.assertFalse([i for i in self.digest["items"] if i["kind"] == "venue_confirmed"])

    def test_ranking_puts_new_venue_first_and_good_news_last(self):
        kinds = [i["kind"] for i in self.digest["items"]]
        self.assertEqual(kinds[0], "new_venue")
        self.assertEqual(kinds[-1], "condition")
        self.assertEqual(self.digest["items"][-1]["status"], "green")

    def test_markdown_links_every_venue_to_its_pinball_map_listing(self):
        md = digest.to_markdown(self.digest, "victoria", "2026-10-01")
        for i in self.digest["items"]:
            self.assertIn(f"https://pinballmap.com/map?by_location_id={i['location_id']}", md)
        self.assertIn("CC BY-SA 4.0", md)


class TitleTests(unittest.TestCase):
    def test_editions_are_ignored(self):
        self.assertEqual(digest.base_title("Godzilla (Premium)"), digest.base_title("Godzilla (Pro)"))
        self.assertEqual(digest.base_title("Cactus Canyon (Remake Special)"), "cactus canyon")
        self.assertNotEqual(digest.base_title("Jaws (Premium)"), digest.base_title("Venom (LE)"))

    def test_status_heuristics(self):
        self.assertEqual(digest.status_of("Machine was turned off"), "amber")
        self.assertEqual(digest.status_of("right flipper weak"), "amber")
        self.assertEqual(digest.status_of("Fixed, plays great"), "green")
        self.assertEqual(digest.status_of("No issues, all working"), "green")
        self.assertEqual(digest.status_of("Not working, out of order"), "amber")
        self.assertEqual(digest.status_of("Set to 3 ball"), "note")


class SnapshotTests(unittest.TestCase):
    def test_flat_and_nested_shapes_both_parse(self):
        nested = [{"id": 1, "location_id": 9, "machine_id": 5, "location": {"id": 9, "name": "A"},
                   "machine": {"id": 5, "name": "Jaws (Pro)", "manufacturer": "Stern", "year": 2024}}]
        flat = [{"id": 1, "location_id": 9, "machine_id": 5, "machine_name": "Jaws (Pro)", "location_name": "A"}]
        for shape in (nested, flat):
            snap = snapshot.normalise(shape, [{"id": 9, "name": "A", "city": "Melbourne"}], "2026-01-01")
            self.assertEqual(snap["machines"]["1"]["name"], "Jaws (Pro)")
            self.assertEqual(snap["machines"]["1"]["location_name"], "A")


if __name__ == "__main__":
    unittest.main()
