"""Thin client for the Pinball Map API.

Follows https://pinballmap.com/llms.txt: every request carries the API token in
a header, the token never leaves the server, bulk endpoints only, and the
caller stores what it fetches instead of asking again. Three requests a day is
the whole budget this project needs.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://pinballmap.com/api/v1/"
USER_AGENT = "pinball-diff/0.1 (daily change digest for Victoria; see README)"
TOKEN_HELP = ("Set PINBALLMAP_API_TOKEN. Request a token at https://pinballmap.com/api_token "
              "(needs a Pinball Map login; approval is manual).")


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
                    self.sleep(30 * (attempt + 1))     # be a polite client; the limit is shared
                    continue
                raise
        raise RuntimeError("unreachable")

    # The three bulk reads a daily sync needs.
    def region_machines(self, region):
        return self.get(f"region/{region}/location_machine_xrefs.json").get("location_machine_xrefs", [])

    def region_locations(self, region):
        return self.get(f"region/{region}/locations.json").get("locations", [])

    def region_submissions(self, region, limit=500):
        data = self.get(f"region/{region}/user_submissions.json", limit=limit)
        return data.get("user_submissions", data if isinstance(data, list) else [])

    def regions(self):
        return self.get("regions.json").get("regions", [])
