# NYC High School Soccer — data pipeline

Everything behind [nychssoccer.com](https://nychssoccer.com) lives here.
Netlify deploys `main` automatically, so any push publishes.

## Files
- `index.html` — the built page (current season embedded inline, past seasons fetched from `data/`)
- `app.template.html` — the page source; `__PSAL_DATA__` is replaced at build time
- `data/sYYYY.json` — one file per PSAL season (2002–2027 = fall 2001–fall 2026)
- `data/history.json` — every school's season-by-season record, division winners, titles
- `tools/psal_refresh.py` — pulls a season from PSAL, then runs the two scripts below
- `convert.py` — turns a raw PSAL pull into `data/sYYYY.json`
- `build2.py` — builds `index.html` + `data/history.json` from the season files
- `shorten.py` — the abbreviated-school-name rules

## Where the data comes from
PSAL exposes a JSON service at `https://www.psal.org/SportDisplay.svc/`. The calls used:

| Call | Gives |
|---|---|
| `GetFullScheduleBySport?csport='012'&season=2027` | every fixture for a sport + season |
| `getTeamScheduleAny?csports='012'&season=2027&schoolid='03300'&format=''` | per-school results, and whether a result has been posted |
| `Get_Score_Soccer?gameid=…&csports='012'&filter=1` | half-by-half scores |
| `Get_Score_Soccer2?gameid=…&csports='012'&filter=2` | per-player box score (goals, assists, saves, shots, goals allowed) |
| `Get_DisplayGameInfo?gameid=…&csport='012'` | venue, address, referees, trainer |
| `GetSportLeague?csports='012'&season='2027'` | divisions for that season |
| `getTeamStandings012_021?csports='012'&season=2027&league=187` | standings for one division (`lcode` from the call above) |

Sport codes: `012` boys varsity, `021` girls varsity. Season `2027` = fall 2026.

**Getting past the login redirect.** A request with no cookies is answered with a
302 to `Login.aspx`. A plain `GET https://www.psal.org/` into a cookie jar hands
out `PSAL_COOKIE` and `DOE-DC-Persist`, which is enough — there is no account and
no browser involved. `tools/psal_refresh.py` does this on startup.

**Two things that are easy to get wrong:**
- School codes are five digits *with leading zeros* (`08269`), but the schedule
  returns them as integers. Without zero-padding, every Manhattan and Bronx
  school silently drops out — about 30% of games.
- A drawn game comes back from `getTeamScheduleAny` as `cwinner: "TIE "`, not
  null. Test "is `cwinner` set" to tell played from unplayed; a score-based test
  throws away 0-0 draws. `Get_Score_Soccer` returns `0.00` for unplayed games, so
  it can never decide this on its own.

## Refreshing
`.github/workflows/refresh.yml` runs hourly from 4pm to 11pm New York time, plus
once at 8am for anything filed overnight. It pulls PSAL, rebuilds, and commits
only when the data changed. It refuses to publish if the number of posted results
ever drops, since that means a bad pull rather than real data.

Run it by hand from the Actions tab, or:

```
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/repos/deroyperaza/nyc-hs-soccer/actions/workflows/refresh.yml/dispatches \
  -d '{"ref":"main","inputs":{"mode":"fetch","season":"2027"}}'
```

`--mode discover` dumps a sample of every endpoint instead, which is how the
field names above were established.

## Notes
- The home-screen icon must be a **large** `apple-touch-icon` (1024×1024). Given a
  180px source iOS draws the mark at half size on a white tile instead of filling
  it. Serve one large icon with no `sizes` attribute and let iOS downscale.
- Followed teams live in `localStorage`, and are mirrored into the URL as `?f=`.
  iOS gives each home-screen tile its own storage and wipes it when the tile is
  removed, so the URL is what lets a re-added tile remember them.

## Rosters and player pages

`Get_Score_Soccer2` returns **every player on a game sheet**, including rows
where every stat is zero. That is the roster. The original archive pull kept
only rows carrying a stat, which dropped roughly 40% of every game back to
2002 -- the app could say who scored but not who played. `tools/psal_rosters.py`
backfills the rest into `data/r<season>.json`, and the hourly refresh keeps the
live season's file current (incrementally: one call per new game).

Those files are separate from `data/s<season>.json` on purpose. The season file
is what the page boots with, so it stays lean; a roster is fetched only when
someone opens a roster fold or a player page.

### Identity

PSAL's `cid` is a roster-entry id: stable for a player across one season, and
**reissued every year**. Zohran Mamdani is 141514, then 161866, then 180413. So
it separates two same-named players on different teams within a season, but it
cannot join a career. Careers are joined by **name at the same school**, which
is deliberately conservative -- a transfer shows up as two pages rather than
risking two different kids merged into one.

The slug spells that rule out: `/player/<name>-<school-slug>/<sport>`. The app
derives it from a roster row with no lookup table, and `build_players.py` uses
the same school slugs `build2.py` writes to `data/slugs.json`, so the two can
never drift.

### Shards, and why the live season is left out

Careers live in `data/p/<xxx>.json`, 1024 shards keyed by FNV-1a of
`<sport>/<slug>` -- one small fetch per player page, no index to load up front.
`build_players.py` **excludes the current season**: the app already holds it in
its boot payload and stitches those games on itself (`liveRows`). Without that,
every hourly refresh would rewrite all 1024 shards and add ~70MB of blobs to
the repo each time.

### Not indexed

The data is PSAL's and public, but a per-child profile page is an aggregation
PSAL does not publish, and most of these players are minors. `robots.txt`
disallows `/player/`, Netlify sends `X-Robots-Tag: noindex` for those paths, and
the page swaps its robots meta tag while a player sheet is open. Pages stay
linkable and deep-linkable; they just do not turn up in search.
