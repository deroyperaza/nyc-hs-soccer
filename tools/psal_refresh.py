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
        lid = leagues[0].get("lcode")
        show("getTeamStandings012_021 (league=%s)" % lid,
             call(s, "getTeamStandings012_021", csports="'012'", season=season, league=lid), 4)
    hteam = sched[0].get("hteamid")
    show("getTeamScheduleAny (current season)",
         call(s, "getTeamScheduleAny", csports="'012'", season=season,
              schoolid="'%s'" % hteam, format="''"), 2)

    # How is a DRAW encoded? cwinner is null for an unplayed game too, so a naive
    # "cwinner is null => no result" rule would silently drop every tie.
    # 2026 game 483598 was a real 4-4 draw for school 08269.
    rows = call(s, "getTeamScheduleAny", csports="'012'", season=2026,
                schoolid="'08269'", format="''") or []
    draw = [r for r in rows if r.get("cid") == 483598]
    show("A KNOWN 4-4 DRAW (2026 game 483598)", draw, 1)
    played = [r for r in rows if r.get("cwinner")]
    show("a decided game from the same school", played[:1], 1)
    print("\n-- draw vs unplayed discriminator --")
    for r in rows[:12]:
        print("   cid=%s score=%s-%s winner=%r loser=%r reason=%r level=%r" % (
            r.get("cid"), r.get("nfscoreh"), r.get("nfscorea"),
            r.get("cwinner"), r.get("closer"), r.get("creason"), r.get("clevel")))


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
