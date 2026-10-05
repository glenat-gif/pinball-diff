"""Settings that belong to the publication rather than the code: its name,
where it lives, which zones the email covers, and whether the email goes out
on its own or waits as a draft. Kept in site.json at the repository root.

  base_path        "/pinball-diff" on GitHub Pages; "" once on a custom domain
  email_mode       "draft" leaves each issue in Buttondown for a person to send;
                   "send" sends it straight away
  machine_art      true shows each machine's art from OPDB (the Open Pinball
                   Database), linked as Pinball Map links it. Off until OPDB
                   confirms reuse is fine.
  issue_weekday    0 is Monday. 3 is Thursday, so the email lands in time to
                   plan the weekend. An issue covers the seven days before it.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
