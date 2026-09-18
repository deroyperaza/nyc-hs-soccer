#!/usr/bin/env python3
"""Find out whether PSAL has headshots, and what pulling them would cost.

GetPlayerDetails returns an img_id. Player.js turns it into

    /psalapps/psalsports/common/dsplyprflPicture.ashx?id=<img_id>

and falls back to the PSAL crest when it is null. Nothing about how often it
is filled in is knowable from the documentation, because there isn't any, so
this samples two seasons -- the current one and the one before -- counts how
many players carry an id, and downloads a few of the images to see how big
they are and what format they come back as.

Writes probe/photos.json. No image is kept.
"""
import json, os, re, sys, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_main = sys.modules.get('__main__')
if os.path.basename(getattr(_main, '__file__', '') or '') == 'psal_refresh.py':
    _rf = _main
else:
    import psal_refresh as _rf  # noqa: E402
call, pmap, sess = _rf.call, _rf.pmap, _rf.sess

PIC = "https://www.psal.org/psalapps/psalsports/common/dsplyprflPicture.ashx?id=%s"
SPC = {0: "012", 1: "021"}
SAMPLE = 400          # cids per season, both sports pooled
FETCH = 12            # images actually downloaded, to size them


def season_cids(datadir, season):
    path = os.path.join(datadir, "r%s.json" % season)
    if not os.path.exists(path):
        return []
    o = json.load(open(path))
    out = set()
    for key, rows in o.get("R", {}).items():
        spc = SPC.get(int(key.split(":")[0]))
        if not spc:
            continue
        for r in rows:
            out.add((spc, r[2]))
    return sorted(out)


def run(datadir, repo, seasons):
    import random
    random.seed(23)
    report = {"seasons": {}, "images": []}
    ids = []

    for season in seasons:
        pool = season_cids(datadir, season)
        if not pool:
            report["seasons"][season] = {"error": "no roster file"}
            continue
        pick = random.sample(pool, min(SAMPLE, len(pool)))

        def one(job):
            spc, cid = job
            rows = call("GetPlayerDetails", sportcode="'%s'" % spc,
                        playerId="'%d'" % cid, query="'profiledetails'",
                        season=0) or []
            for r in rows:
                if str(r.get("season")) == season:
                    return r.get("img_id")
            return rows[0].get("img_id") if rows else None

        got = pmap(one, pick, "photos %s" % season)
        have = [g for g in got if g not in (None, "", 0, "0")]
        report["seasons"][season] = {
            "sampled": len(pick), "with_photo": len(have),
            "pct": round(100.0 * len(have) / max(len(pick), 1), 1),
            "roster_size": len(pool),
            "projected": int(round(len(pool) * len(have) / max(len(pick), 1))),
        }
        ids += [str(g) for g in have]
        print("  %s: %d of %d sampled have an img_id (%.1f%%)"
              % (season, len(have), len(pick), report["seasons"][season]["pct"]),
              flush=True)

    # What actually comes back? Size and type decide whether a full pull is a
    # few megabytes or a few hundred.
    seen = []
    for i in ids[:FETCH]:
        try:
            r = sess().get(PIC % i, timeout=60)
            seen.append({"id": i, "status": r.status_code,
                         "bytes": len(r.content),
                         "type": r.headers.get("Content-Type", ""),
                         "magic": r.content[:4].hex()})
        except Exception as e:
            seen.append({"id": i, "error": repr(e)[:200]})
    report["images"] = seen
    real = [s for s in seen if s.get("bytes")]
    if real:
        avg = sum(s["bytes"] for s in real) / len(real)
        report["avg_bytes"] = int(avg)
        total = sum(v.get("projected", 0) for v in report["seasons"].values()
                    if isinstance(v, dict))
        report["projected_mb_for_sampled_seasons"] = round(total * avg / 1048576.0, 1)
        print("  average image %.0f KB over %d fetched" % (avg / 1024.0, len(real)))

    d = os.path.join(repo, "probe")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "photos.json"), "w") as f:
        json.dump(report, f, indent=1)
    print("wrote probe/photos.json")


def main(datadir, repo, seasons):
    try:
        run(datadir, repo, seasons)
    except Exception:
        d = os.path.join(repo, "probe")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "photos.json"), "w") as f:
            json.dump({"failed": traceback.format_exc()[-3000:]}, f, indent=1)
        print("photo probe failed -- traceback in probe/photos.json")
