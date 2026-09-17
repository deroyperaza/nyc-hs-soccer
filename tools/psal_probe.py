#!/usr/bin/env python3
"""Look at what GetPlayerDetails actually returns, and commit the answer.

PSAL's box-score feed carries no uniform number and no grade. Its player
profile pages do -- Player.js renders `player.cuniform` beside the name and
`getgradetxt(player.cclass)` underneath -- and those come from a different
endpoint, keyed by the same cid the box scores already give us.

Before spending a couple of hours pulling 120k of them, this establishes two
things a guess cannot:

  1. the exact field names, from a handful of raw responses, and
  2. how far back PSAL actually filled the fields in, from a stratified
     sample across every archived season.

It writes probe/latest.json into the repo rather than printing, because the
refresh job's logs redirect to blob storage that nothing here can read.
"""
import json, os, re, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_main = sys.modules.get('__main__')
if os.path.basename(getattr(_main, '__file__', '') or '') == 'psal_refresh.py':
    _rf = _main
else:
    import psal_refresh as _rf  # noqa: E402
warm, call, pmap = _rf.warm, _rf.call, _rf.pmap

SPC = {0: "012", 1: "021"}
RAW_CIDS = 6          # full responses, to read the field names off
PER_SEASON = 12       # sampled per season per sport, to measure coverage


def cids_by_season(datadir):
    """{season: {(sportCode, cid), ...}} straight out of the roster archive."""
    out = {}
    for f in sorted(os.listdir(datadir)):
        m = re.match(r'^r(\d{4})\.json$', f)
        if not m:
            continue
        o = json.load(open(os.path.join(datadir, f)))
        seen = set()
        for key, rows in o.get("R", {}).items():
            spc = SPC.get(int(key.split(":")[0]))
            if not spc:
                continue
            for r in rows:
                seen.add((spc, r[2]))
        out[m.group(1)] = seen
    return out


def details(spc, cid):
    return call("GetPlayerDetails", sportcode="'%s'" % spc,
                playerId="'%d'" % cid, query="'profiledetails'", season=0)


def sports(spc, cid):
    return call("GetPlayerSport", sportcode="'%s'" % spc, playerId="'%d'" % cid)


def present(v):
    return v is not None and str(v).strip() not in ("", "0", "None")


def run(datadir, repo):
    by_season = cids_by_season(datadir)
    seasons = sorted(by_season)
    print("seasons on file: %s" % ", ".join(seasons), flush=True)

    # 1. A few complete responses, so the field names come from the service
    #    and not from my memory of reading their JavaScript.
    raw = []
    newest = sorted(by_season[seasons[-1]])[:RAW_CIDS]
    for spc, cid in newest:
        raw.append({"cid": cid, "sport": spc,
                    "GetPlayerDetails": details(spc, cid),
                    "GetPlayerSport": sports(spc, cid)})

    # 2. A stratified sample: does a 2003 record carry a number at all?
    import random
    random.seed(11)
    jobs = []
    for s in seasons:
        pool = sorted(by_season[s])
        jobs += [(s, spc, cid) for spc, cid in
                 random.sample(pool, min(PER_SEASON, len(pool)))]

    def probe(job):
        s, spc, cid = job
        rows = details(spc, cid) or []
        first = rows[0] if rows else {}
        return {"season": s, "sport": spc, "cid": cid,
                "rows": len(rows),
                "seasons_linked": sorted({r.get("season") for r in rows}),
                "cids_linked": sorted({r.get("cid") for r in rows}),
                "uniform": first.get("cuniform"),
                "cclass": first.get("cclass"),
                "school": first.get("cschool"),
                "name": "%s %s" % ((first.get("cfname") or "").strip(),
                                   (first.get("clname") or "").strip())}

    sampled = pmap(probe, jobs, "probe")

    cover = {}
    for r in sampled:
        c = cover.setdefault(r["season"], {"n": 0, "uniform": 0, "cclass": 0,
                                           "empty": 0, "multi": 0})
        c["n"] += 1
        if not r["rows"]:
            c["empty"] += 1
        if present(r["uniform"]):
            c["uniform"] += 1
        if present(r["cclass"]):
            c["cclass"] += 1
        if len(r["seasons_linked"]) > 1:
            c["multi"] += 1

    out = {"raw": raw, "coverage": cover, "sampled": sampled,
           "cids_total": len(set().union(*by_season.values()))}
    d = os.path.join(repo, "probe")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "latest.json"), "w") as f:
        json.dump(out, f, indent=1)

    print("\nseason  n  uniform  class  multi-season  empty")
    for s in seasons:
        c = cover.get(s)
        if c:
            print("  %s  %2d   %2d      %2d      %2d          %2d"
                  % (s, c["n"], c["uniform"], c["cclass"], c["multi"], c["empty"]))
    print("\nwrote probe/latest.json")


def main(datadir, repo):
    try:
        run(datadir, repo)
    except Exception:
        d = os.path.join(repo, "probe")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "latest.json"), "w") as f:
            json.dump({"failed": traceback.format_exc()[-3000:]}, f, indent=1)
        print("probe failed -- wrote the traceback to probe/latest.json")
