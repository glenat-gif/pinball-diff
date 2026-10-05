"""Checks for the podcast feeds. Run with:  python -m unittest discover tests -v"""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pbmdiff import podcasts  # noqa: E402

FEED = b"""<?xml version="1.0"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
<title>Pinball Oz Wide Podcast</title><link>https://example.com/show</link>
<description>&lt;p&gt;JAZ and MAT here!&lt;/p&gt;</description><itunes:image href="https://example.com/logo.jpg"/>
<item><title>PINBALL OZ WIDE - EPISODE 24 : THE GAMES WE HATE TO LOVE</title>
<link>https://example.com/ep24</link><pubDate>Thu, 01 Oct 2026 05:15:00 GMT</pubDate>
<description>&lt;p&gt;In this month's episode we are joined by George &amp;amp; Sonia.&lt;/p&gt;</description>
<itunes:duration>02:06:34</itunes:duration></item>
<item><title>Newcastle Pinfest 15</title><link>https://example.com/pinfest</link>
<pubDate>Sat, 26 Sep 2026 01:00:00 +1000</pubDate><itunes:duration>3204</itunes:duration></item>
</channel></rss>"""
SHOW = {"key": "oz", "name": "Pinball Oz Wide", "feed": "https://example.com/rss", "strip": "PINBALL OZ WIDE - "}


class PodcastTests(unittest.TestCase):
    def test_feed_is_read_tidily(self):
        info, eps = podcasts.parse(FEED, SHOW)
        self.assertEqual(info["about"], "JAZ and MAT here!")
        self.assertEqual(info["image"], "https://example.com/logo.jpg")
        self.assertEqual(eps[0]["title"], "Episode 24: The Games We Hate to Love")
        self.assertEqual(eps[0]["date"], "2026-10-01")                 # 05:15 GMT is 3:15 pm in Melbourne
        self.assertEqual(eps[0]["minutes"], 127)
        self.assertEqual(eps[0]["summary"], "In this month's episode we are joined by George & Sonia.")
        self.assertEqual((eps[1]["title"], eps[1]["minutes"]), ("Newcastle Pinfest 15", 53))

    def test_a_broken_feed_keeps_yesterdays_copy(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(podcasts, "PODCASTS", pathlib.Path(tmp) / "p.json"), \
                mock.patch.dict(podcasts.SITE, {"podcasts": [SHOW]}):
            good = podcasts.fetch(get=lambda url: FEED)
            self.assertEqual(len(good["episodes"]), 2)
            def boom(url):
                raise OSError("feed down")
            again = podcasts.fetch(get=boom)
            self.assertEqual(len(again["episodes"]), 2)


if __name__ == "__main__":
    unittest.main()
