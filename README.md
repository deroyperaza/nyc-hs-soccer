# NYC High School Soccer — data pipeline

Everything behind the published app lives here.

## Files
- `index.html` — the built page (current season embedded inline, past seasons fetched from `data/`)
- `app.template.html` — the page source; `__PSAL_DATA__` is replaced at build time
- `data/sYYYY.json` — one file per PSAL season (2002–2027 = fall 2001–fall 2026)
- `data/history.json` — every school's season-by-season record, division winners, titles
- `convert.py` — turns a raw PSAL pull into `data/sYYYY.json`
- `build2.py` — builds `index.html` + `data/history.json` from the season files
- `shorten.py` — the abbreviated-school-name rules

## Where the data comes from
PSAL exposes a JSON service at `https://www.psal.org/SportDisplay.svc/`. The calls used:

| Call | Gives |
|---|---|
| `GetFullScheduleBySport?csport='012'&season=2027` | every fixture for a sport + season |
| `getTeamScheduleAny?csports='012'&season=2027&schoolid='03300'&format=''` | per-school results, **`cwinner` is null until a result is posted**, `cleague` is `Y` league / `P` playoff / `N` non-league |
| `Get_Score_Soccer?gameid=…&csports='012'&filter=1` | half-by-half scores |
| `Get_Score_Soccer2?gameid=…&csports='012'&filter=2` | per-player box score (goals, assists, saves, shots, goals allowed) |
| `Get_DisplayGameInfo?gameid=…&csport='012'` | venue, address, referees, trainer |
| `GetSportLeague?csports='012'&season='2027'` | divisions for that season |
| `getTeamStandings012_021?csports='012'&season=2027&league=175` | standings for one division |

Sport codes: `012` boys varsity, `021` girls varsity. Season `2027` = fall 2026.
Score `999.00` = forfeit win. `Get_Score_Soccer` returns `0.00` for games not yet played —
always use `cwinner` from `getTeamScheduleAny` to tell "0-0 draw" from "not played".

The service is only reachable from a browser session on psal.org (the cloud sandbox is blocked),
so refreshes run through the Claude browser on this Mac.

## Refreshing the current season
1. Open psal.org in the Claude browser.
2. Pull the current season (schedule + per-game detail) and the result flags.
3. Save the two JSON files to `~/Downloads`, then run:
   `python3 convert.py 2027 && python3 build2.py 2027`
4. Republish `index.html` plus `data/` to the existing artifact.
