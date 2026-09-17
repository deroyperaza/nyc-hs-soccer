#!/usr/bin/env python3
"""Pull a PSAL season straight from the JSON service and rebuild the site data.

PSAL answers with a 302 to Login.aspx when a request carries no cookies, but a
plain GET of the homepage hands out anonymous cookies that satisfy it -- no
account and no browser required.

Field names below were all read off live responses (see `--mode discover`),
not guessed. The one subtle bit: in getTeamScheduleAny a drawn game comes back
with cwinner == "TIE " (trailing space), while an unplayed game has cwinner
null. Testing "is cwinner set" is therefore what separates played from
unplayed, and it keeps 0-0 draws, which a score-based test would throw away.
"""
import argparse, json, os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = "https://www.psal.org/SportDisplay.svc"
HOME = "https://www.psal.org/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SPORTS = ["012", "021"]                 # boys varsity, girls varsity
SPORT_INDEX = {"012": 0, "021": 1}
WORKERS = 12

_local = threading.local()
_cookies = None


def make_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "Referer": HOME, "X-Requested-With": "XMLHttpRequest"})
    return s


def warm():
    global _cookies
    s = make_session()
    r = s.get(HOME, timeout=60)
    r.raise_for_status()
    if not s.cookies:
        raise SystemExit("PSAL handed out no cookies -- the service changed")
    _cookies = s.cookies
    return s


def sess():
    s = getattr(_local, "s", None)
    if s is None:
        s = make_session()
        s.cookies.update(_cookies)
        _local.s = s
    return s


def call(path, **params):
    qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
    url = "%s/%s?%s" % (BASE, path, qs)
    last = None
    for attempt in range(4):
        try:
            r = sess().get(url, timeout=60)
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                return r.json().get("d")
            last = "HTTP %s" % r.status_code
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
        time.sleep(1.0 * (attempt + 1))
    print("  ! gave up on %s (%s)" % (path, last), file=sys.stderr)
    return None


def pmap(fn, items, label):
    """Run fn over items with a worker pool, printing progress."""
    out, done, total = [], [0], len(items)
    lock = threading.Lock()

    def wrapped(it):
        r = fn(it)
        with lock:
            done[0] += 1
            if done[0] % 100 == 0 or done[0] == total:
                print("    %s %d/%d" % (label, done[0], total), flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        out = list(ex.map(wrapped, items))
    return out


# ---------------------------------------------------------------- discover
def discover(season):
    def show(label, val, limit=3):
        print("\n=== %s ===" % label)
        if val is None:
            print("  -> None"); return
        if isinstance(val, list):
            print("  rows: %d" % len(val))
            for row in val[:limit]:
                print("  " + json.dumps(row)[:700])
        else:
            print("  " + json.dumps(val)[:700])

    sched = call("GetFullScheduleBySport", csport="'012'", season=season)
    show("GetFullScheduleBySport", sched, 2)
    if not sched:
        return
    gid = sched[0]["eventid"]
    show("Get_Score_Soccer", call("Get_Score_Soccer", gameid=gid, csports="'012'", filter=1), 2)
    show("Get_Score_Soccer2", call("Get_Score_Soccer2", gameid=gid, csports="'012'", filter=2), 3)
    show("Get_DisplayGameInfo", call("Get_DisplayGameInfo", gameid=gid, csport="'012'"), 1)
    leagues = call("GetSportLeague", csports="'012'", season="'%s'" % season)
    show("GetSportLeague", leagues, 3)
    if leagues:
        show("getTeamStandings012_021",
             call("getTeamStandings012_021", csports="'012'", season=season,
                  league=leagues[0].get("lcode")), 3)


# ---------------------------------------------------------------- fetch
def num(v):
    return v if v is not None else 0


def fetch_sport(spc, season):
    print("  [%s] schedule" % spc, flush=True)
    sched = call("GetFullScheduleBySport", csport="'%s'" % spc, season=season) or []
    games, schools = [], set()
    for g in sched:
        games.append({
            "id": g["eventid"],
            "d": g.get("evdate") or "",
            "t": (g.get("evtime") or "").strip(),
            "h": g.get("hteamid"), "hn": g.get("hteam") or "",
            "a": g.get("ateamid"), "an": g.get("ateam") or "",
            "loc": g.get("evlocation") or "",
            "boro": g.get("evboro"),
            "st": (g.get("evstatus") or "").strip(),
            "ty": g.get("evtype") or "game",
        })
        # School codes are 5 digits WITH leading zeros ("08269"), but the schedule
        # returns them as ints, so str() alone drops the zero and the per-school
        # lookup silently returns nothing for every Manhattan/Bronx school.
        for t in (g.get("hteamid"), g.get("ateamid")):
            if t: schools.add(str(t).zfill(5))
    print("  [%s] %d games, %d schools" % (spc, len(games), len(schools)), flush=True)

    # divisions + standings
    leagues_raw = call("GetSportLeague", csports="'%s'" % spc, season="'%s'" % season) or []
    leagues = [[l.get("lcode"), l.get("clname")] for l in leagues_raw]

    def one_standing(l):
        rows = call("getTeamStandings012_021", csports="'%s'" % spc,
                    season=season, league=l[0]) or []
        return {"name": l[1],
                "rows": [[r.get("cschool"), r.get("newname"), num(r.get("nwins")),
                          num(r.get("nloses")), num(r.get("nties")), num(r.get("npoints"))]
                         for r in rows]}
    standings = [s for s in pmap(one_standing, leagues, "standings") if s["rows"]]

    # per-school schedules: the authoritative "was a result posted" source
    def one_school(code):
        return call("getTeamScheduleAny", csports="'%s'" % spc, season=season,
                    schoolid="'%s'" % code, format="''") or []
    per_school = pmap(one_school, sorted(schools), "schools")

    flags, played = {}, set()
    sp = SPORT_INDEX[spc]
    for rows in per_school:
        for r in rows:
            gid = r.get("cid")
            if gid is None:
                continue
            win = r.get("cwinner")
            has = 1 if win else 0          # "TIE " counts as played; null does not
            flags["%d:%d" % (sp, gid)] = [
                has, r.get("cleague") or "", (win or "").strip(),
                r.get("nfscoreh") or "0.00", r.get("nfscorea") or "0.00",
                (r.get("creason") or "").strip(), (r.get("clevel") or "").strip(),
            ]
            if has:
                played.add(gid)
    covered = len(flags)
    if covered < len(games):
        print("  [%s] WARNING: only %d/%d games covered by per-school pulls"
              % (spc, covered, len(games)), flush=True)
    print("  [%s] %d/%d games covered, %d with a posted result"
          % (spc, covered, len(games), len(played)), flush=True)

    # per-game detail, only for games that actually have a result
    def one_detail(gid):
        d = {}
        sc = call("Get_Score_Soccer", gameid=gid, csports="'%s'" % spc, filter=1)
        if sc:
            row = sc[0]
            d.update({
                "hs": row.get("nfscoreh"), "as": row.get("nfscorea"),
                "hc": row.get("cschoolh"), "ac": row.get("cschoola"),
                "ph": [row.get("n1qh"), row.get("n2qh"), row.get("n3qh"), row.get("n4qh"),
                       row.get("not1h"), row.get("not2h"), row.get("not3h")],
                "pa": [row.get("n1qa"), row.get("n2qa"), row.get("n3qa"), row.get("n4qa"),
                       row.get("not1a"), row.get("not2a"), row.get("not3a")],
            })
            if row.get("creason"):
                d["re"] = row["creason"].strip()
        info = call("Get_DisplayGameInfo", gameid=gid, csport="'%s'" % spc)
        if info:
            row = info[0]
            d.setdefault("hc", row.get("cschoolh"))
            d.setdefault("ac", row.get("cschoola"))
            d["ad"] = (row.get("addname") or "").strip()
            refs = [row.get("r%dName" % i) for i in range(1, 8)]
            d["rf"] = [r.strip() for r in refs if r and r.strip()]
            tr = " ".join(x for x in (row.get("TrainerFirstname"),
                                      row.get("TrainerLastname")) if x)
            if tr.strip():
                d["tr"] = tr.strip()
        box = call("Get_Score_Soccer2", gameid=gid, csports="'%s'" % spc, filter=2)
        if box:
            d["b"] = [[b.get("cschool"), b.get("pname"), num(b.get("goals")),
                       num(b.get("assists")), num(b.get("saves")),
                       num(b.get("shots")), num(b.get("gallowe"))] for b in box]
        return (gid, d)

    detail = {}
    for gid, d in pmap(one_detail, sorted(played), "detail"):
        if d:
            detail[str(gid)] = d

    return {"games": games, "detail": detail,
            "leagues": leagues, "standings": standings}, flags


def fetch(season, rawdir):
    os.makedirs(rawdir, exist_ok=True)
    out = {"season": season, "pulled": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "sports": {}}
    all_flags = {}
    for spc in SPORTS:
        blk, flags = fetch_sport(spc, season)
        out["sports"][spc] = blk
        all_flags.update(flags)

    main = os.path.join(rawdir, "psal2_%s.json" % season)
    fl = os.path.join(rawdir, "psalfl2_%s.json" % season)
    json.dump(out, open(main, "w"))
    json.dump(all_flags, open(fl, "w"))
    tot = sum(len(out["sports"][s]["games"]) for s in out["sports"])
    res = sum(1 for v in all_flags.values() if v[0])
    print("\nwrote %s (%d games) and %s (%d flags, %d with results)"
          % (main, tot, fl, len(all_flags), res), flush=True)
    return tot, res


def sanity(season, res_now, datadir):
    """Never publish a season that just lost results -- that means a bad pull."""
    path = os.path.join(datadir, "s%s.json" % season)
    if not os.path.exists(path):
        return
    try:
        prev = json.load(open(path))
    except Exception:
        return
    before = sum(1 for g in prev.get("G", []) if g[6] is not None)
    print("results: %d before, %d now" % (before, res_now))
    if res_now < before:
        raise SystemExit("REFUSING to publish: results dropped %d -> %d"
                         % (before, res_now))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="fetch",
                    choices=["discover", "fetch", "rosters"])
    ap.add_argument("--season", default="2027")
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = ap.parse_args()

    warm()
    print("session ok", flush=True)

    if args.mode == "discover":
        discover(args.season)
        return

    if args.mode == "rosters":
        # One-shot backfill of the full participation lists. Writes only
        # data/r<season>.json, so it cannot disturb the live season files.
        from psal_rosters import run as run_rosters
        one = str(args.season)
        run_rosters(os.path.join(args.repo, "data"),
                    None if one in ("0", "all", "") else [one],
                    commit_repo=args.repo)
        return

    rawdir = os.path.join(args.repo, "_raw")
    datadir = os.path.join(args.repo, "data")
    t0 = time.time()
    _, res = fetch(args.season, rawdir)
    sanity(args.season, res, datadir)

    env = dict(os.environ,
               PSAL_RAW=rawdir,
               PSAL_OUT=datadir,
               PSAL_BASE=args.repo,
               PSAL_TPL=os.path.join(args.repo, "app.template.html"),
               PSAL_PAGE=os.path.join(args.repo, "index.html"))
    for script in ("convert.py", "build2.py"):
        print("\n$ python3 %s %s" % (script, args.season), flush=True)
        subprocess.run([sys.executable, os.path.join(args.repo, script), str(args.season)],
                       check=True, cwd=args.repo, env=env)

    # Rosters for this season only, and incremental: pull_season skips games the
    # file already covers, so a nightly run costs one call per new game. Then
    # rebuild the player shards and run build2 once more, which is what picks up
    # the shard count. A failure here must not fail a good score refresh.
    try:
        from psal_rosters import run as run_rosters
        run_rosters(datadir, [str(args.season)])
        # Player pages need the archive rosters. Until the backfill has landed
        # at least one past season there is nothing to shard, and building
        # anyway would commit 1024 empty files.
        archive = [f for f in os.listdir(datadir)
                   if f.startswith("r") and f.endswith(".json")
                   and f[1:-5] != str(args.season)]
        if not archive:
            print("no archive rosters yet -- skipping player pages", flush=True)
            raise StopIteration
        print("\n$ python3 build_players.py", flush=True)
        subprocess.run([sys.executable, os.path.join(args.repo, "build_players.py")],
                       check=True, cwd=args.repo, env=env)
        subprocess.run([sys.executable, os.path.join(args.repo, "build2.py"), str(args.season)],
                       check=True, cwd=args.repo, env=env)
    except StopIteration:
        pass
    except Exception as e:
        print("rosters/player pages skipped: %s: %s" % (type(e).__name__, e),
              file=sys.stderr, flush=True)
    print("\ndone in %.0fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
