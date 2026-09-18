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

# psal_refresh is usually the script being run, which makes it __main__. A plain
# "import psal_refresh" would then load a SECOND copy of the module with its own
# _cookies still None, and every request would go out cookie-less, get bounced to
# Login.aspx and retry its way to nothing. So reuse the instance that is already
# loaded when there is one.
_main = sys.modules.get('__main__')
if os.path.basename(getattr(_main, '__file__', '') or '') == 'psal_refresh.py':
    _rf = _main
else:
    import psal_refresh as _rf  # noqa: E402
warm, call, pmap = _rf.warm, _rf.call, _rf.pmap
SPORTS, SPORT_INDEX = _rf.SPORTS, _rf.SPORT_INDEX

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

    # A game with no rows is ordinary -- plenty of coaches never file a sheet.
    # What is not ordinary is a pull where nothing at all comes back, which is
    # what a dead session looks like: cookie-less requests bounce to Login.aspx
    # and every game reads as empty.
    #
    # The test used to be a 90% empty rate, and that was wrong in a way that
    # only showed up mid-season. Games whose coach never files stay uncovered
    # and are retried on every run, so the uncovered set fills up with them as
    # the season goes on and the empty rate climbs past 90% on its own. It
    # tripped at 62 of 68 on a night when the service was working perfectly,
    # took the player-page rebuild down with it, and did so silently.
    #
    # Whether the session is alive is answered by whether ANY game came back
    # with rows, not by the ratio. A pull that dies halfway writes what it got;
    # the games it missed are left out rather than recorded empty, so the next
    # run retries them and it heals itself.
    got = sum(1 for _key, rows in results if rows)
    if len(todo) >= 10 and got == 0:
        raise SystemExit(
            "REFUSING to write r%s.json: not one of %d games returned a roster. "
            "That is a broken session, not a season without sheets."
            % (season, len(todo)))
    blob = {"season": season, "P": names, "R": R}
    json.dump(blob, open(out_path, "w"), separators=(",", ":"))
    total = sum(len(v) for v in R.values())
    was = stored_rows(season, datadir)
    print("  s%s: %d games, %d roster rows (archive had %d stat rows), %d names, "
          "%d empty, %.1f MB"
          % (season, len(R), total, was, len(names), empty,
             os.path.getsize(out_path) / 1048576.0), flush=True)
    return out_path


def commit_season(repo, season):
    """Push each season as it lands.

    The first backfill ran for hours and would have lost everything if the
    runner had been cut off, because the workflow only commits at the end. A
    season is a natural checkpoint, and pull_season skips games a file already
    covers, so a rerun picks up exactly where the last commit left off.
    """
    import subprocess
    path = os.path.join('data', 'r%s.json' % season)
    try:
        subprocess.run(['git', 'config', 'user.name', 'psal-refresh'], cwd=repo, check=True)
        subprocess.run(['git', 'config', 'user.email',
                        'actions@users.noreply.github.com'], cwd=repo, check=True)
        subprocess.run(['git', 'add', path], cwd=repo, check=True)
        if subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=repo).returncode == 0:
            return
        subprocess.run(['git', 'commit', '-q', '-m',
                        'Rosters: season %s' % season], cwd=repo, check=True)
        for attempt in range(3):
            if subprocess.run(['git', 'push'], cwd=repo).returncode == 0:
                return
            subprocess.run(['git', 'pull', '--rebase', '-q'], cwd=repo)
        print('  ! could not push season %s' % season, file=sys.stderr, flush=True)
    except Exception as e:
        print('  ! commit failed for %s: %s' % (season, e), file=sys.stderr, flush=True)


def run(datadir, seasons=None, force=False, commit_repo=None):
    if not seasons:
        seasons = sorted(f[1:-5] for f in os.listdir(datadir)
                         if f.startswith("s") and f.endswith(".json"))
    t0 = time.time()
    print("backfilling rosters for %d seasons" % len(seasons), flush=True)
    for s in seasons:
        out = pull_season(s, datadir, force=force)
        if out and commit_repo:
            commit_season(commit_repo, s)
    print("\nrosters done in %.0fs" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--seasons", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--commit", action="store_true",
                    help="commit and push each season as it finishes")
    a = ap.parse_args()
    warm()
    run(os.path.join(a.repo, "data"),
        [s for s in a.seasons.split(",") if s] or None, a.force,
        a.repo if a.commit else None)
