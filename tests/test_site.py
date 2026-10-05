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
from pbmdiff import issue, mail, render, site, store  # noqa: E402

SUBS = json.loads((ROOT / "tests" / "fixtures" / "melbourne_week.json").read_text(encoding="utf-8"))["user_submissions"]
ON = dt.date(2026, 10, 1)            # a Thursday; the fixture week ends the day before


class Built(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.tmp.name)
        self.patches = [mock.patch.object(store, "EVENTS", t / "events.jsonl"),
                        mock.patch.object(issue, "ISSUES", t / "issues"),
                        mock.patch.object(site, "DIST", t / "dist"),
                        mock.patch.object(issue, "today", lambda: ON)]
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
        for page in ["about/index.html", "issues/index.html", "zone/melbourne/index.html",
                     "zone/gippsland/index.html", "feed.xml", "style.css", ".nojekyll"]:
            self.assertTrue((dist / page).exists(), page)

    def test_links_carry_the_pages_base_path(self):
        home = (site.build(on=dt.date(2026, 10, 3)) / "index.html").read_text()
        self.assertIn('href="/pinball-diff/style.css"', home)
        self.assertIn('href="/pinball-diff/zone/melbourne/"', home)
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
        self.assertIn('name="tag" value="melbourne"', home)


class MachineTests(Built):
    def test_machines_page_groups_editions_and_links_pinball_maps_search(self):
        dist = site.build(on=dt.date(2026, 10, 3))
        page = (dist / "machines" / "index.html").read_text()
        self.assertIn("Cactus Canyon", page)
        self.assertEqual(page.count("<h2>Cactus Canyon"), 1)     # original and remake are one title
        self.assertIn("Remake Special", page)
        self.assertIn("https://pinballmap.com/map?by_machine_id=", page)
        self.assertIn('class="tag new">In<', page)
        self.assertIn('class="tag gone">Out<', page)

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

    def test_email_covers_victoria_only_and_reads_cleanly(self):
        iss = issue.ensure_latest(self.events, on=ON)
        md = mail.markdown(iss)
        self.assertIn("## Greater Melbourne", md)
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
