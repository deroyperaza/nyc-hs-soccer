# PSAL's service, as far as we have mapped it

Everything here was read off `psal.org`'s own JavaScript and confirmed against
live responses. None of it is documented by PSAL and none of it is promised to
stay put.

Base: `https://www.psal.org/SportDisplay.svc/`. Responses are WCF-flavoured
JSON with the payload under `d`. Send `Accept: application/json` or you get XML.

`--mode discover` dumps a sample of every endpoint below, which is how these
field names were established in the first place.

## The cookie gate

A request without cookies is redirected to `Login.aspx` and returns HTML. The
fix is one line: `GET https://www.psal.org/` into a cookie jar first, then reuse
that jar. `warm()` in `tools/psal_refresh.py` does it and every worker thread
copies the result.

The cookies handed out are `PSAL_COOKIE` and `DOE-DC-Persist`. There is no
account and no browser involved; the cookies are anonymous. But a bounced request
looks like a successful empty response to careless code, which is the shape of
more than one bug in this repo's history. See `docs/operations.md`.

Sport codes: `012` boys varsity, `021` girls varsity. Seasons are named for the
spring of the school year, so **`2027` is the fall of 2026**.

## Endpoints

### `GetFullScheduleBySport?csport='012'&season=2027`
Every fixture: `eventid`, schools, date, time, location, status, playoff round.
The backbone of `data/s<season>.json`.

### `getTeamScheduleAny?csports='012'&season=2027&schoolid='03300'&format=''`
Per-school results, and — importantly — whether a result has been posted at
all. See the traps below.

### `Get_Score_Soccer?gameid=&csports='012'&filter=1`
One row per game: halves, overtime, penalties, final, and the reason a game was
not played.

### `Get_Score_Soccer2?gameid=&csports='012'&filter=2`
**The box score, and more usefully the team sheet.** Returns a row for every
player dressed, including all-zero rows — which is where the roster comes from.

`cschool · pname · goals · assists · saves · shots · gallowe · groundball · cid · status`

No shirt number, no grade, no position. PSAL's own box score renders six of
these columns and nothing else.

The original archive pull kept only rows carrying a statistic and discarded the
rest, losing about 40% of every game. `tools/psal_rosters.py` exists to undo
that.

### `getTeamRosters?season=&csports='012'&schoolid=&activeInactive='Y'`
Name and position per player. Superseded for our purposes by the profile
endpoint, which gives the same and much more.

### `GetPlayerDetails?sportcode='012'&playerId=<cid>&query='profiledetails'&season=0`
**The most valuable endpoint in the service.** One row per season the player
appeared in:

`cid · season · csport · cschool · newname · cfname · clname · cuniform · cclass · cposition · cfeet · cinches · cweight · img_id · athletic · scholastic · community · colplan · coachquote`

With `season=0` it returns *every* season for that person — under whichever cid
that year issued. That is the identity link (below).

### `GetPlayerSport?sportcode=&playerId=`
The other sports that player appears in, with a uniform and position each. Not
imported; soccer is the whole scope here.

### `GetSportStats6`, `Get_DisplayGameInfo`, `GetSportLeague`, `getTeamStandings012_021`
Season statistics, referees and trainers, leagues, and the standings table.
Used by `psal_refresh.py` in the ordinary refresh.

## cid: a roster-entry id that PSAL can nonetheless resolve to a person

`cid` identifies a player **within one season** and is reissued every year.
Mamdani is 120492, 141514, 161866 and 180413 across his four seasons. A career
cannot be assembled from box scores alone, which is why this app originally
guessed at it by matching a name at a school.

But `GetPlayerDetails` on *any* of those cids returns all four seasons, each
labelled with its own cid. PSAL is joining them internally. So one call per cid
resolves the whole career, and the pull collapses to roughly the number of
people rather than the number of season-entries: **119,984 cids in the archive
→ 63,665 people**, about two cids each.

## What the fields are actually worth

Measured, not assumed — sampled across five eras, 400 players a season.

| Field | Coverage | Notes |
|---|---|---|
| `cclass` (grade) | **100%** | Every player, every season back to 2002. The one field with no gaps. `9`/`10`/`11`/`12`. |
| `cuniform` | **73–82%** | Flat across the archive. School-by-school sloppiness, not a historical gap: one team files all 18, the other files none. |
| `cposition` | ~32% | Free text. Twenty-five years of coaches typing by hand produced **2,786 distinct spellings** of four positions — `Defender`, `DEF`, `def`, `D`, `Defense`, `foward`, `MDF`. `norm_position()` in `build_players.py` folds them; 91% map cleanly. |
| `img_id` (headshot) | **~0.5%** | 13 of 2,000 sampled. There is no photo archive here, just a field nobody used. The one image fetched was 23KB, served as `image/gif`, actually a JPEG. |
| `cfeet`/`cweight` | 43% in 2002 → 0% now | |
| `athletic`, `colplan`, `scholastic`, `community`, `coachquote` | 21% in 2002 → 0% by 2012 | A student-athlete profile feature used heavily in the early 2000s and abandoned. Roughly 2–3k coach's quotes exist, all from 2002–2008. **Not imported.** |

The last row is the one to revisit if this project ever wants colour rather than
numbers. It is the only untapped seam left in the feed.

## Two things that are easy to get wrong

**School codes are five digits with leading zeros** (`08269`), but the schedule
returns them as integers. Without zero-padding, every Manhattan and Bronx
school silently drops out — about 30% of games. `shorten.py` holds the
abbreviated-name rules that go with these codes.

**A drawn game comes back as `cwinner: "TIE "`, not null.** Test "is `cwinner`
set" to tell played from unplayed. A score-based test throws away 0–0 draws,
and `Get_Score_Soccer` returns `0.00` for unplayed games, so it can never
decide this on its own.

## Page URLs, for cross-checking by hand

- Game: `psal.org/games/game-detail.aspx#<sportCode>/<gameid>` — the hash, not a query string
- Player: `psal.org/profiles/player-profile.aspx#<cid>/<sportCode>`
- School: `psal.org/profiles/school-profile.aspx#<schoolCode>`

Navigating to a `.svc` URL directly gets you the login page; the endpoints only
answer from inside a page that has the cookies.
