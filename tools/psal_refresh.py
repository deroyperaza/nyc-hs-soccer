#!/usr/bin/env python3
"""Pull a PSAL season straight from the JSON service (no browser needed).

PSAL rejects cookie-less requests with a 302 to Login.aspx, but a plain GET of
the homepage yields anonymous cookies that satisfy it -- no account required.

Modes:
  discover  dump one sample response per endpoint so field names can be mapped
  fetch     full pull -> psal2_<season>.json + psalfl2_<season>.json
"""
import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://www.psal.org/SportDisplay.svc"
HOME = "https://www.psal.org/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SPORTS = ["012", "021"]          # boys varsity, girls varsity
SPORT_INDEX = {"012": 0, "021": 1}


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "Referer": HOME, "X-Requested-With": "XMLHttpRequest"})
    r = s.get(HOME, timeout=60)
    r.raise_for_status()
    if not s.cookies:
        raise SystemExit("no cookies from the homepage -- PSAL changed something")
    return s


def call(s, path, **params):
    """GET one service method. Values already carrying quotes are passed through."""
    qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
    url = "%s/%s?%s" % (BASE, path, qs)
    for attempt in range(4):
        try:
            r = s.get(url, timeout=60)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                return r.json().get("d")
            if r.status_code in (301, 302):
                raise RuntimeError("redirected to login -- session lost")
        except Exception as e:
            if attempt == 3:
                raise
        time.sleep(1.5 * (attempt + 1))
    return None


def discover(s, season):
    """Print the shape of every endpoint so the mapping can be written from fact."""
    def show(label, val, limit=3):
        print("\n=== %s ===" % label)
        if val is None:
            print("  -> None")
            return
        if isinstance(val, list):
            print("  rows: %d" % len(val))
            for row in val[:limit]:
                print("  " + json.dumps(row)[:700])
        else:
            print("  " + json.dumps(val)[:700])

    sched = call(s, "GetFullScheduleBySport", csport="'012'", season=season)
    show("GetFullScheduleBySport", sched, 2)
    if not sched:
        return
    gid = sched[0]["eventid"]
    print("\n(sample game id: %s)" % gid)

    show("Get_Score_Soccer (filter=1)",
         call(s, "Get_Score_Soccer", gameid=gid, csports="'012'", filter=1), 4)
    show("Get_Score_Soccer2 (filter=2)",
         call(s, "Get_Score_Soccer2", gameid=gid, csports="'012'", filter=2), 4)
    show("Get_DisplayGameInfo",
         call(s, "Get_DisplayGameInfo", gameid=gid, csport="'012'"), 2)
    leagues = call(s, "GetSportLeague", csports="'012'", season="'%s'" % season)
    show("GetSportLeague", leagues, 3)
    if leagues:
        lg = leagues[0]
        lid = lg.get("leagueid") or lg.get("LeagueID") or lg.get("id")
        show("getTeamStandings012_021 (league=%s)" % lid,
             call(s, "getTeamStandings012_021", csports="'012'", season=season, league=lid), 3)
    hteam = sched[0].get("hteamid")
    show("getTeamScheduleAny (a played game's home team)",
         call(s, "getTeamScheduleAny", csports="'012'", season=season,
              schoolid="'%s'" % hteam, format="''"), 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="discover", choices=["discover", "fetch"])
    ap.add_argument("--season", type=int, default=2027)
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    s = session()
    print("session cookies:", ", ".join(c.name for c in s.cookies))

    if args.mode == "discover":
        discover(s, args.season)
        return
    print("fetch mode is not implemented yet -- run discover first")


if __name__ == "__main__":
    main()
