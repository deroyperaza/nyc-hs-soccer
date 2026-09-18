# The data, and how a career gets assembled

Everything the app reads lives in `data/`. Nothing in here is hand-maintained
except `name_fixes.json`.

## Files

| File | Holds | Rebuilt by |
|---|---|---|
| `s<season>.json` | Games, teams, standings, box-score rows. The current season is inlined into `index.html`; the rest are fetched on demand. | `convert.py` |
| `r<season>.json` | Every player who dressed, per game: `[schoolCode, nameIndex, cid, goals, assists, saves, shots, gallowed]`. Separate from `s` so the app stays lean. | `tools/psal_rosters.py` |
| `pr012.json`, `pr021.json` | PSAL's player profiles. `P` maps a person to their seasons; `X` maps **any** cid to that person. | `tools/psal_players.py` |
| `pu<season>.json` | `{cid: [uniform, grade, position]}` — what a roster row needs to draw a shirt and a grade, keyed the way roster rows are. | `build_players.py` |
| `p/<xxx>.json` | Career payloads, 1024 shards, FNV-1a of the player key. ~55KB each, 55MB total. | `build_players.py` |
| `n/<pre>.json` | Name index for search: `[name, slug, sport, schoolCode, firstYear, lastYear, uniform?, grade?]`. 164,858 rows across 3,995 prefix files, 2.7KB average. | `build_players.py` |
| `history.json` | Season-by-season ratings and championships. | `build2.py` |
| `slugs.json`, `titles.json` | School code → slug, and code → display name. | `build2.py` |
| `name_fixes.json` | Manual corrections, e.g. `MOMDANI → MAMDANI`. Applied *after* the profile name, because PSAL's own spelling is not always right. | hand |

School display names come from `shorten.py`, which holds the abbreviation rules,
and `build2.py` writes the resulting slug map to `slugs.json`. `build_players.py`
reads that same map rather than keeping a second copy, so the two cannot drift.

Scale, as of September 2026: 26 archived seasons (2002–2027), **1,021,747
appearances**, **62,168 careers**.

## Identity

A career is PSAL's own grouping of cids, taken from `GetPlayerDetails`
(see [`psal-api.md`](psal-api.md)). All 62,168 use it; none fall back to the old
name+school rule.

This replaced a heuristic that could not follow a transfer and could not tell
two same-named teammates apart. What changed:

- **524 players who switched schools** now have one page, at the school they
  finished at.
- Same-named teammates PSAL files separately stay separate — which means some
  career totals went *down*, because they had been conflated.

### Where PSAL has no opinion

Two people it keeps apart can still land on the same address — same name, same
school. That happened 82 times. The rule: seasons that sit next to each other
and fit inside a high-school career are one student PSAL failed to link, so
merge; seasons that overlap, or sit years apart, are two students, so the more
recent keeps the bare slug and the others get `-2`, `-3` (87 of those).

### Slugs

`/player/<name>-<school>/<sport>`, where the school is the one they finished at.

The app derives that URL in the browser from a roster row, which for a transfer
— or a truncated name — is not where the career lives. So every spelling and
school a player was ever filed under gets a one-line stub pointing at the real
page: **1,656 of them**. No link the app can construct leads nowhere.

## Sharding, and why the current season is missing from it

Career payloads are sharded by FNV-1a of `<sport>/<slug>`, mirrored between
`build_players.py` and the app so a page can find its own shard with no index.

**The shards deliberately stop at last season.** The app already holds the
current season in the payload it boots with and stitches those rows in itself,
which means an hourly refresh never rewrites a 90KB shard.

The cost of that decision, and it has bitten twice: a player whose *only*
season is the current one has no shard at all. Both times the fix was the same
— fall back to the name index, which knows the current number and grade for
everyone. `fillLiveNumber()` in the app is that fallback.

The name index carries the **most recent** uniform and grade, which is why a
2012 player's row reads SR meaning "was a senior in his last recorded season".
For current players, which is nearly everything anyone looks at, it reads
right. Box scores and roster folds show that season's actual values, from
`pu<season>.json`.

## Names

PSAL truncates at its field widths and its coaches type inconsistently.
`canonical_names()` merges two systematic shapes — per-word truncation
(`SEBASTI COCIOBA` → `SEBASTIAN COCIOBA`) and whole-string truncation at 20
characters — but only within the same school and sport, non-overlapping, with
at most a one-year gap. 578 merges land automatically.

The profile name is preferred over the box-score name because it is not
truncated, but `name_fixes.json` still gets the last word: Mamdani is filed as
MOMDANI on his own profile and MAMDANI in three of his four box scores.

## Privacy, deliberately

Most of these players are minors.

- There is **no file listing every player** and no way to page through them.
  Search needs three letters and returns one small prefix file.
- `/player/*` carries `X-Robots-Tag: noindex, nofollow` from `netlify.toml`, a
  meta tag in the page, and a `robots.txt` block.
- Followed players live in the browser, not on a server. There are no accounts.

If that posture ever changes, change it on purpose.
