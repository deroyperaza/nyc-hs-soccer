# nychssoccer.com

An unofficial, mobile-first record of PSAL high school soccer in New York City —
every game, every box score and every player PSAL has filed since 2002, for boys
and girls varsity.

Live at **https://nychssoccer.com**. Built by Deroy Peraza. PSAL posts the
official record; this is a reader for it.

## What it is, technically

A single static HTML file and a tree of JSON, deployed to Netlify from this
repo. There is no server and no database. A GitHub Actions job pulls from
PSAL's undocumented JSON service every twenty minutes during the season,
rebuilds whatever changed and commits it; Netlify redeploys on the push.

```
PSAL SportDisplay.svc
        │
        │  tools/psal_refresh.py        scores, schedules, standings  →  data/s<season>.json
        │  tools/psal_rosters.py        who dressed, per game         →  data/r<season>.json
        │  tools/psal_players.py        profiles, identity            →  data/pr<sport>.json
        ▼
   convert.py ─→ build_players.py ─→ build2.py
                        │                 │
                        │                 └─ app.template.html + this season → index.html
                        │
                        ├─ data/p/<xxx>.json   career payloads, 1024 shards
                        ├─ data/n/<pre>.json   name index for search
                        └─ data/pu<season>.json  shirt number, grade, position by cid
```

The app boots with the current season inlined in the page and fetches
everything else on demand, so a cold load is one request and a player page is
one more.

## Map

| Path | What it is |
|---|---|
| `app.template.html` | The entire app. `__PSAL_DATA__` is replaced at build time. |
| `index.html` | Built artifact — do not edit, it is overwritten every refresh. |
| `build2.py` | Builds `index.html`, `data/history.json`, slugs and titles. |
| `build_players.py` | Builds career shards, the name index and `pu<season>.json`. |
| `convert.py` | Raw PSAL pulls → `data/s<season>.json`. |
| `tools/psal_refresh.py` | The entry point CI calls. All modes live here. |
| `tools/psal_rosters.py` | Full participation lists per game. |
| `tools/psal_players.py` | Player profiles and PSAL's cross-season identity. |
| `tools/cf_analytics.py` | Cloudflare traffic → `analytics/latest.md`. |
| `tools/psal_probe.py`, `psal_photos_probe.py`, `cf_audit.py` | Read-only investigations. They write to `probe/` and change nothing. |
| `data/name_fixes.json` | Manual name corrections. PSAL's own spelling is not always right. |
| `docs/` | How the feed works, how the data is shaped, how to operate it. |

## Running it by hand

Everything goes through one script:

```bash
python3 tools/psal_refresh.py --mode fetch    --season 2027   # the hourly job
python3 tools/psal_refresh.py --mode rosters  --season all    # backfill participation
python3 tools/psal_refresh.py --mode players  --season all    # backfill profiles
python3 tools/psal_refresh.py --mode analytics                # traffic report
python3 tools/psal_refresh.py --mode probe                    # look, don't touch
```

Only `fetch` is meant to run on a schedule. The backfills are one-shots that
checkpoint to git as they go, so a killed run resumes rather than restarts.

**PSAL is not reachable from a laptop on a restricted network, or from a
sandboxed container.** Both are blocked by egress policy. In practice every
pull runs in CI, which is also why `docs/operations.md` spends so long on
getting answers out of a job whose logs cannot be read.

## Things that live nowhere else

**The home-screen icon must be a large `apple-touch-icon` (1024×1024).** Given a
180px source, iOS draws the mark at half size on a white tile instead of
filling it. Serve one large icon with no `sizes` attribute and let iOS
downscale.

**Followed teams live in `localStorage` and are mirrored into the URL as `?f=`**
(players as `?p=`). iOS gives each home-screen tile its own storage sandbox and
wipes it when the tile is removed, so the URL is what lets a re-added tile — or
a second device — remember them. There are no accounts.

**The refresh refuses to publish if the number of posted results ever drops.**
That means a bad pull rather than real data. `sanity()` in `psal_refresh.py`.

## Read next

- [`docs/psal-api.md`](docs/psal-api.md) — the undocumented service, endpoint by endpoint, and what each field is actually worth
- [`docs/data.md`](docs/data.md) — every file in `data/`, and how a career is assembled
- [`docs/operations.md`](docs/operations.md) — CI, analytics, and the traps that have cost real time
