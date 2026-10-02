# pinball-diff

A change digest for Pinball Map's Australian listings. Pinball Map says where
the machines are. This says what changed: new venues, machines landing,
machines leaving, title swaps, and condition notes, as a short list a person
would read on a Tuesday and drive somewhere on Saturday because of.

It is not a map and not a venue finder. Every venue in the digest links to its
Pinball Map listing, which is where people should go to look and to update.
That keeps it inside Pinball Map's data use agreement, and it is the right
thing for the scene anyway.

## How it works

Pinball Map has no Australian regions beyond `nsw`, `brisbane` and `west-oz`
and will not add more, and its bulk machine endpoint is deprecated. On the
maintainers' advice the source is the submissions feed within a radius of a
point, which is Pinball Map doing the diff for us.

1. Once a day, ask for everything submitted within 250 miles of each of
   eleven points that between them cover where Australians play. One
   request per area, eleven a day.
2. Merge the rows into `data/events.jsonl`, deduplicated by Pinball Map id,
   with dates converted to Melbourne time.
3. Put every event in exactly one digest zone. Victoria is sliced into
   Greater Melbourne, Geelong and the Surf Coast, Gippsland, the north and
   the west, because Melbourne is Greater Melbourne, not Morwell. Other
   states are one zone each until someone there wants them sliced.
4. Build a digest per zone with a few rules: a new venue and its first machines are one line; a removal and an
   addition of the same title at one venue is a swap; additions group per
   venue and credit the contributor; condition notes become amber or green;
   bare confirmations are counted, not listed.
5. Write `data/digests/<zone>/<date>.md` and `.json`. The Markdown is the
   email body. The JSON is for whatever comes next.

The fetch circles and zones are in `pbmdiff/areas.py`. The rules are in `pbmdiff/digest.py`.
No dependencies beyond Python 3.11.

## Try it without a token

```
python -m pbmdiff.run demo
```

Runs the rules over a real week of Melbourne submissions kept as a fixture.

## Run it for real

1. `export PINBALLMAP_API_TOKEN=...` (request at https://pinballmap.com/api_token).
2. `python -m pbmdiff.run fetch` pulls the last fortnight for every area on
   the first run, and from then on reaches back two days past the last fetch.
3. `python -m pbmdiff.run digest --zone gippsland --days 7` writes last
   week's digest for one zone from the store, no network needed.
4. `python -m pbmdiff.run sync` does both, for every zone.
5. `python -m pbmdiff.run zones` shows how the store splits across zones
   and lists anything that landed in none.

`.github/workflows/daily.yml` runs the sync once a day and commits the
events and digests back, so the history lives in git. It needs the token as
a repository secret named `PINBALLMAP_API_TOKEN`.

## Tests

```
python -m unittest discover tests -v
```

## Being a good citizen

Eleven requests a day, token in a header, never in a browser. Everything is
served from the local store. Contributors are credited by username; the
Australian record rests on a handful of volunteers and this should make
their work visible. Pinball Map data is CC BY-SA 4.0.

## Not here yet

Venues deleted from the map (a separate feed endpoint); the IFPA comp
calendar; dealer "landing soon" intake by email; and any sending of the
digest. The digest has to be right first.
