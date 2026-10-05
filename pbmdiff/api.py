"""Thin client for the Pinball Map API.

Follows https://pinballmap.com/llms.txt and the advice Pinball Map gave when
approving the token: the token goes in a header and never leaves the server,
the only read is the submissions feed within a radius of a point, and the
caller stores what it fetches instead of asking again. One request per area
per day is the whole budget.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://pinballmap.com/api/v1/"
USER_AGENT = "pinball-diff/0.2 (change digest for Australia; github.com/glenat-gif/pinball-diff)"
TOKEN_HELP = ("Set PINBALLMAP_API_TOKEN. Request a token at https://pinballmap.com/api_token "
              "(needs a Pinball Map login; approval is manual).")
MAX_MILES = 250                      # the endpoint's own ceiling
PAGE = 50                            # the endpoint's largest page
MAX_PAGES = 200                      # a guard, far above a year of any area
PAUSE = 1.0                          # seconds between pages; well under the shared limit


class PinballMap:
    def __init__(self, token=None, sleep=time.sleep):
        self.token = token or os.environ.get("PINBALLMAP_API_TOKEN")
        if not self.token:
            raise SystemExit(TOKEN_HELP)
        self.sleep = sleep

    def get(self, path, **params):
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={
            "X-Api-Token": self.token, "User-Agent": USER_AGENT, "Accept": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as err:
                if err.code == 401:
                    raise SystemExit("Pinball Map rejected the API token. " + TOKEN_HELP)
                if err.code in (429, 500, 502, 503, 504) and attempt < 2:
                    self.sleep(30 * (attempt + 1))     # the limit is shared; back off properly
                    continue
                raise
        raise RuntimeError("unreachable")

    def submissions_within(self, lat, lon, miles, since):
        """Everything submitted within `miles` of a point since a YYYY-MM-DD date.

        Without paging the feed silently stops at the newest 200, so this always
        pages, 50 at a time (the endpoint's maximum), until the last page.
        """
        out, page = [], 1
        while True:
            data = self.get("user_submissions/list_within_range.json", lat=lat, lon=lon,
                            max_distance=min(miles, MAX_MILES), min_date_of_submission=since,
                            limit=PAGE, page=page)
            out += data.get("user_submissions", [])
            nxt = (data.get("pagy") or {}).get("next")
            if not nxt or page >= MAX_PAGES:
                return out
            page = nxt
            self.sleep(PAUSE)


    def machines(self):
        """The whole machine catalogue: names, editions and OPDB image links. One request."""
        data = self.get("machines.json")
        return data.get("machines", data if isinstance(data, list) else [])
