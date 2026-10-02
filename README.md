# pinball-diff

A daily change digest for Pinball Map's Victorian listings. Pinball Map says
where the machines are. This says what changed: new venues, machines landing,
machines leaving, title swaps, and condition notes, as a short list a person
would read on a Tuesday and drive somewhere on Saturday because of.

It is not a map and not a venue finder. Every venue in the digest links to its
Pinball Map listing, which is where people should go to look and to update.
That keeps it inside Pinball Map's data use agreement (see `pinballmap.com/llms.txt`),
and it is the right thing for the scene anyway.

## How it works

1. Once a day, fetch the region's machine list and venue list. Two bulk requests.
2. Save that as today's snapshot in `data/snapshots/<region>/<date>.json`.
3. Compare it with the previous snapshot. The differences are raw events.
4. Clean the events into digest items with a few rules:
   a new venue and its first machines are one line; a removal and an addition
   of the same title at one venue is a swap; additions group per venue;
   condition notes become amber or green; bare confirmations are counted,
   not listed.
5. Write `data/digests/<region>/<date>.md` and `.json`. The Markdown is the
   email body. The JSON is for whatever comes next.

No dependencies beyond Python 3.11.

## Try it without a token

```
python -m pbmdiff.run demo
```

Runs the whole pipeline on two bundled fixture days built to mirror real
activity-feed rows for Victoria.

## Run it for real

1. Make a Pinball Map account and request an API token at
   https://pinballmap.com/api_token. Approval is manual. Say what this is:
   a daily Victorian change digest that links every venue back to Pinball Map.
2. `export PINBALLMAP_API_TOKEN=...`
3. Find the region name. Australian regions are named after cities, and
   Victoria is most likely `melbourne`:
   ```
   python -m pbmdiff.run regions melb
   ```
4. Take the first snapshot, then another the next day:
   ```
   python -m pbmdiff.run sync --region melbourne
   ```
   The first run only saves. Every later run writes a digest.
5. Rebuild a digest for any span of stored snapshots, offline:
   ```
   python -m pbmdiff.run digest --region melbourne --since 2026-10-01 --until 2026-10-08
   ```

`.github/workflows/daily.yml` runs the sync once a day and commits the
snapshot and digest back, so the history lives in git. It needs the token as
a repository secret named `PINBALLMAP_API_TOKEN`.

## Tests

```
python -m unittest discover tests -v
```

## Being a good citizen

Three requests a day, token in a header, never in a browser. Cache everything.
Credit contributors by username in the digest; the Victorian record rests on a
handful of volunteers and this should make their work visible, not invisible.
Pinball Map data is CC BY-SA 4.0.

## What is deliberately not here yet

The region user_submissions feed, which would add usernames to additions and
removals; the comp calendar from IFPA; dealer "landing soon" intake by email;
and any sending of the digest. The diff has to be right first.
