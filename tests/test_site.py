"""Checks for the website and the email. Run with:  python -m unittest discover tests -v

Builds the whole site and an issue from the real fixture week into a
temporary folder, with the network replaced by a fake Buttondown.
"""
import datetime as dt
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pbmdiff import ifpa, issue, mail, render, site, store  # noqa: E402

SUBS = json.loads((ROOT / "tests" / "fixtures" / "melbourne_week.json").read_text(encoding="utf-8"))["user_submissions"]
ON = dt.date(2026, 10, 1)            # a Thursday; the fixture week ends the day before


class Built(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.patches = [mock.patch.object(store, "EVENTS", t / "events.jsonl"),
                        mock.patch.object(issue, "ISSUES", t / "issues"),
                        mock.patch.object(site, "DIST", t / "dist"),
                        mock.patch.object(issue, "today", lambda: ON),
                        mock.patch.object(ifpa, "COMPS", t / "comps.json")]   # never read the real calendar
        for p in self.patches:
            p.start()
        store.add(SUBS)
        self.events = store.load()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class SiteTests(Built):
    def test_every_page_builds_and_links_every_venue_to_pinball_map(self):
        dist = site.build(on=dt.date(2026, 10, 3))
        home = (dist / "index.html").read_text()
        for s in SUBS:
            if s["submission_type"] != "confirm_location":
                self.assertIn(f"https://pinballmap.com/map?by_location_id={s['location_id']}", home)
        for page in ["about/index.html", "issues/index.html", "zone/vic/index.html",
                     "zone/nsw/index.html", "feed.xml", "style.css", ".nojekyll"]:
            self.assertTrue((dist / page).exists(), page)

    def test_links_carry_the_pages_base_path(self):
        home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertRegex(home, r'href="/pinball-diff/style\.css\?v=[0-9a-f]{8}"')
        self.assertIn('href="/pinball-diff/zone/vic/"', home)
        self.assertNotIn('href="/zone/', home)

    def test_text_from_players_is_escaped(self):
        evil = dict(SUBS[5], id=999999, comment="<script>alert(1)</script>")
        store.add([evil])
        home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertNotIn("<script>alert", home)
        self.assertIn("&lt;script&gt;", home)

    def test_signup_waits_until_there_is_a_buttondown_account(self):
        with mock.patch.dict(site.SITE, {"buttondown_username": ""}):
            home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertIn("Sign-ups open soon", home)
        with mock.patch.dict(site.SITE, {"buttondown_username": "pinballthisweek"}):
            home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertIn('action="https://buttondown.com/api/emails/embed-subscribe/pinballthisweek"', home)
        self.assertIn('name="tag" value="vic" checked', home)


class MachineTests(Built):
    def test_machines_index_and_title_pages(self):
        dist = site.build(on=dt.date(2026, 10, 3))
        index = (dist / "machines" / "index.html").read_text()
        self.assertEqual(index.count('<span class="t">Cactus Canyon</span>'), 1)   # original and remake together
        self.assertIn('href="/pinball-diff/machines/cactus-canyon/"', index)
        page = (dist / "machines" / "cactus-canyon" / "index.html").read_text()
        self.assertIn("Remake Special", page)
        self.assertIn('class="tag new">In<', page)
        self.assertIn('class="tag gone">Out<', page)
        self.assertRegex(page, r"https://pinballmap\.com/map\?by_machine_(group_)?id=\d+&amp;by_country=AU")
        self.assertIn("<h2>2026</h2>", page)

    def test_machine_art_only_when_switched_on(self):
        from pbmdiff import digest
        cat = {str(s["machine_id"]): {"img": "https://img.opdb.org/x-medium.jpg", "w": 640, "h": 400,
                                      "group": digest.base_title(s["machine_name"])}
               for s in SUBS if s.get("machine_id")}
        with mock.patch.object(store, "load_machines", lambda: cat):
            with mock.patch.dict(site.SITE, {"machine_art": False}):
                page = (site.build(on=dt.date(2026, 10, 3)) / "machines" / "cactus-canyon" / "index.html").read_text()
            self.assertNotIn("img.opdb.org", page)
            with mock.patch.dict(site.SITE, {"machine_art": True}):
                dist = site.build(on=dt.date(2026, 10, 3))
            page = (dist / "machines" / "cactus-canyon" / "index.html").read_text()
            self.assertIn('src="https://img.opdb.org/x-medium.jpg"', page)
            self.assertIn("Open Pinball Database", page)
            self.assertIn('class="thumb"', (dist / "machines" / "index.html").read_text())

    def test_same_name_different_machines_get_separate_pages(self):
        evs = {}
        for i, (mid, name) in enumerate([(774, "Godzilla (Sega, 1998)"), (3415, "Godzilla (Pro) (Stern, 2021)"),
                                         (3417, "Godzilla (LE) (Stern, 2021)")]):
            evs[i] = {"id": i, "type": "machine_added", "date": "2026-01-0" + str(i + 1), "machine": name,
                      "machine_id": mid, "location_id": 1, "location_name": "X", "city": "", "lat": -37.8, "lon": 145.0}
        cat = {"774": {"group": None}, "3415": {"group": 88}, "3417": {"group": 88}}
        groups = site.machine_groups(evs, "2026-12-31", cat)
        self.assertEqual(len(groups), 2)
        stern = next(g for g in groups if "LE" in g["editions"])
        self.assertEqual(stern["editions"], {"Pro", "LE"})
        self.assertEqual(sorted(g["slug"] for g in groups), ["godzilla-sega-1998", "godzilla-stern-2021"])

    def test_machine_names_in_the_week_link_to_their_pages(self):
        home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertIn('<a class="m" href="/pinball-diff/machines/cactus-canyon/">Cactus Canyon</a>', home)
        self.assertIn('<a class="m" href="/pinball-diff/machines/ghostbusters/">Ghostbusters (Pro)</a>', home)
        self.assertIn('<span class="m">Venom (LE)</span>', home)     # only condition notes, so no page

    def test_title_rows_carry_edition_and_state(self):
        page = (site.build(on=dt.date(2026, 10, 3)) / "machines" / "cactus-canyon" / "index.html").read_text()
        self.assertIn('data-ed="Remake Special" data-state="vic"', page)

    def test_near_data_and_attract_lines(self):
        import json as _json
        dist = site.build(on=dt.date(2026, 10, 3))
        near = _json.loads((dist / "near.json").read_text())
        self.assertTrue(all({"d", "lat", "lon", "k", "html"} <= set(i) for i in near["items"]))
        self.assertIn(["Morwell", -38.239, 146.41, "vic"], near["places"])
        home = (dist / "index.html").read_text()
        self.assertIn("var ATTRACT=", home)
        self.assertIn("NEW VENUE  MORWELL HOTEL", home)
        self.assertIn("CACTUS CANYON (REMAKE SPECIAL)  LANDS AT  RAILWAY HOTEL SOUTH MELBOURNE", home)
        self.assertIn("VENOM (LE)  NEEDS A TECH  FORTRESS MELBOURNE", home)
        self.assertIn('id="near-form"', home)

    def test_slugs_drop_accents(self):
        self.assertEqual(site.slug("Pokémon"), "pokemon")
        self.assertEqual(site.slug("Elvira's House of Horrors"), "elvira-s-house-of-horrors")

    def test_flags_mark_rarer_editions_and_new_games(self):
        from pbmdiff import digest
        self.assertEqual(digest.flags("Venom (LE) (Stern, 2023)", 2026), ["Limited Edition"])
        self.assertEqual(digest.flags("Pokemon (Premium) (Stern, 2026)", 2026), ["Premium", "New release"])
        self.assertEqual(digest.flags("Attack from Mars (Bally, 1995)", 2026), [])


class IssueTests(Built):
    def test_issue_is_made_once_on_the_issue_day(self):
        made = issue.ensure_latest(self.events, on=ON)
        self.assertEqual(made["date"], "2026-10-01")
        self.assertEqual((made["since"], made["until"]), ("2026-09-24", "2026-09-30"))
        self.assertIsNone(issue.ensure_latest(self.events, on=ON + dt.timedelta(days=2)))
        self.assertEqual(issue.latest_issue_date(ON + dt.timedelta(days=6)), ON)

    def test_no_stale_issue_is_made(self):
        self.assertIsNone(issue.ensure_latest(self.events, on=ON + dt.timedelta(days=4)))
        self.assertEqual(issue.all_dates(), [])

    def test_archive_lists_only_issues_that_reached_buttondown(self):
        iss = issue.ensure_latest(self.events, on=ON)
        self.assertEqual(issue.published_dates(), [])
        iss["email"] = {"status": "skipped"}
        issue.save(iss)
        self.assertEqual(issue.published_dates(), [])
        iss["email"] = {"status": "draft", "id": "em_1"}
        issue.save(iss)
        self.assertEqual(issue.published_dates(), ["2026-10-01"])

    def test_email_covers_victoria_only_and_reads_cleanly(self):
        iss = issue.ensure_latest(self.events, on=ON)
        md = mail.markdown(iss)
        self.assertIn("## Victoria", md)
        self.assertIn("Railway Hotel South Melbourne", md)
        self.assertIn("Albury", md)                          # Northern Victoria
        self.assertNotIn("Morwell", md)                      # added after the issue week closed
        self.assertIn("CC BY-SA 4.0", md)
        self.assertTrue(md.startswith("<!-- buttondown-editor-mode: plaintext -->"))
        self.assertNotIn("\n---\n", md.split("\n", 1)[0])   # Buttondown rejects a body that opens with ---
        self.assertEqual(mail.subject(iss), "4 changes in Victoria: a swap at Railway Hotel South Melbourne")


class DeliverTests(Built):
    def fake(self, seen):
        def opener(req, timeout):
            seen.append((req.full_url, req.headers, json.loads(req.data)))
            return io.BytesIO(b'{"id": "em_123"}')
        return opener

    def test_drafts_once_and_never_twice(self):
        iss = issue.ensure_latest(self.events, on=ON)
        seen = []
        self.assertIn("drafted", mail.deliver(iss, key="k", opener=self.fake(seen)))
        self.assertEqual(seen[0][0], "https://api.buttondown.com/v1/emails")
        self.assertEqual(seen[0][1]["Authorization"], "Token k")
        self.assertEqual(seen[0][2]["status"], "draft")
        again = issue.load("2026-10-01")
        self.assertIn("already handled", mail.deliver(again, key="k", opener=self.fake(seen)))
        self.assertEqual(len(seen), 1)

    def test_send_mode_sends(self):
        iss = issue.ensure_latest(self.events, on=ON)
        seen = []
        with mock.patch.dict(mail.SITE, {"email_mode": "send"}):
            mail.deliver(iss, key="k", opener=self.fake(seen))
        self.assertEqual(seen[0][2]["status"], "about_to_send")

    def test_without_a_key_nothing_is_sent_or_recorded(self):
        iss = issue.ensure_latest(self.events, on=ON)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIn("no BUTTONDOWN_API_KEY", mail.deliver(iss))
        self.assertIsNone(issue.load("2026-10-01")["email"])

    def test_quiet_week_and_stale_issue_send_nothing(self):
        quiet = issue.make({}, ON)
        issue.save(quiet)
        self.assertIn("quiet", mail.deliver(quiet, key="k", opener=self.fake([])))
        old = issue.make(self.events, ON - dt.timedelta(days=7))
        issue.save(old)
        self.assertIn("too old", mail.deliver(old, key="k", opener=self.fake([])))


class RenderTests(unittest.TestCase):
    def test_machine_names_split_into_title_and_maker(self):
        self.assertEqual(render.split_machine("Venom (LE) (Stern, 2023)"), ("Venom (LE)", "Stern, 2023"))
        self.assertEqual(render.split_machine("Mystery Game"), ("Mystery Game", ""))


if __name__ == "__main__":
    unittest.main()
