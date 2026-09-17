#!/usr/bin/env python3
"""Backfill the full participation list for every played game in the archive.

Get_Score_Soccer2 returns every player on a game's sheet, including the ones
whose line is all zeros -- that is the roster. The original archive pull kept
only rows that carried a stat, which threw away roughly 40% of every game and
left the app unable to say who actually played. This walks the archive and
writes the complete list to data/r<season>.json.

Those files are deliberately separate from data/s<season>.json: the app boots
from the season file, so it stays lean, and a roster file is fetched only when
someone opens a roster accordion or a player page.

Row shape: [schoolCode, nameIndex, cid, goals, assists, saves, shots, gallowed]

cid is PSAL's roster-entry id. It is stable for a player across every game of
one season -- so two same-named players on different teams never collide --
but it is reissued each year, so it cannot link a career together on its own.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from psal_refresh import warm, call, pmap, SPORTS, SPORT_INDEX  # noqa: E402

SPC_BY_INDEX = {v: k for k, v in SPORT_INDEX.items()}


def num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def played_games(season, datadir):
    """Every game with a posted result, as (sportCode, gameid, key)."""
    path = os.path.join(datadir, "s%s.json" % season)
    if not os.path.exists(path):
        return []
    o = json.load(open(path))
    out = []
    for g in o.get("G", []):
        if g[6] is None or g[7] is None:
            continue
        spc = SPC_BY_INDEX.get(g[0])
        if spc:
            out.append((spc, g[1], "%d:%d" % (g[0], g[1])))
    return out


def stored_rows(season, datadir):
    path = os.path.join(datadir, "s%s.json" % season)
    if not os.path.exists(path):
        return 0
    o = json.load(open(path))
    return sum(len(d[4]) for d in (o.get("X") or {}).values())


def pull_season(season, datadir, force=False):
    out_path = os.path.join(datadir, "r%s.json" % season)
    games = played_games(season, datadir)
    if not games:
        print("  s%s: no played games on file, skipping" % season, flush=True)
        return None

    have = {}
    if os.path.exists(out_path) and not force:
        try:
            prev = json.load(open(out_path))
            have = prev.get("R") or {}
        except Exception:
            have = {}
    todo = [g for g in games if g[2] not in have]
    if not todo:
        print("  s%s: already complete (%d games)" % (season, len(have)), flush=True)
        return out_path

    def one(item):
        spc, gid, key = item
        rows = call("Get_Score_Soccer2", gameid=gid, csports="'%s'" % spc, filter=2)
        return (key, rows or [])

    results = pmap(one, todo, "s%s" % season)

    # Rebuild the name table from scratch each time so it never accumulates
    # orphans from an earlier partial run.
    names, nidx, R = [], {}, {}

    def ix(name):
        name = (name or "").strip()
        if name not in nidx:
            nidx[name] = len(names)
            names.append(name)
        return nidx[name]

    fresh = {key: rows for key, rows in results}
    for key, rows in list(have.items()):
        fresh.setdefault(key, None)   # placeholder, filled from the old table below

    prev_names = []
    if have:
        try:
            prev_names = json.load(open(out_path)).get("P") or []
        except Exception:
            prev_names = []

    empty = 0
    for key in sorted(fresh):
        rows = fresh[key]
        if rows is None:                      # carried over from an earlier run
            R[key] = [[r[0], ix(prev_names[r[1]] if r[1] < len(prev_names) else ""),
                       r[2], r[3], r[4], r[5], r[6], r[7]] for r in have[key]]
            continue
        if not rows:
            # A game that came back empty is left out entirely rather than
            # recorded as an empty roster, so a later run retries it instead of
            # treating a failed call as a finished one.
            empty += 1
            continue
        R[key] = [[(b.get("cschool") or "").strip(), ix(b.get("pname")),
                   num(b.get("cid")), num(b.get("goals")), num(b.get("assists")),
                   num(b.get("saves")), num(b.get("shots")), num(b.get("gallowe"))]
                  for b in rows]

    blob = {"season": season, "P": names, "R": R}
    json.dump(blob, open(out_path, "w"), separators=(",", ":"))
    total = sum(len(v) for v in R.values())
    was = stored_rows(season, datadir)
    print("  s%s: %d games, %d roster rows (archive had %d stat rows), %d names, "
          "%d empty, %.1f MB"
          % (season, len(R), total, was, len(names), empty,
             os.path.getsize(out_path) / 1048576.0), flush=True)
    return out_path


def run(datadir, seasons=None, force=False):
    if not seasons:
        seasons = sorted(f[1:-5] for f in os.listdir(datadir)
                         if f.startswith("s") and f.endswith(".json"))
    t0 = time.time()
    print("backfilling rosters for %d seasons" % len(seasons), flush=True)
    for s in seasons:
        pull_season(s, datadir, force=force)
    print("\nrosters done in %.0fs" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--seasons", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    warm()
    run(os.path.join(a.repo, "data"),
        [s for s in a.seasons.split(",") if s] or None, a.force)
