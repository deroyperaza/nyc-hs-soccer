#!/usr/bin/env python3
"""Pull PSAL's player profiles: uniform number, grade, position, and identity.

The box-score feed gives a name, a school and a cid. GetPlayerDetails, keyed
by that same cid, gives four things it does not:

  cuniform   the jersey number -- filled in for about three quarters of
             players, evenly across the archive; it is school-by-school
             sloppiness, not a historical gap
  cclass     the grade, as 9/10/11/12 -- present for every single player
             sampled, in every season back to 2002
  cposition  Defender, Midfield, Goalie, Forward
  season+cid every season that player appeared in, under whichever cid that
             year issued -- PSAL's own answer to a question we have been
             guessing at with names and schools

That last one is why this is worth an hour of runner time. cid is reissued
annually, so a career could not be assembled from box scores alone; here the
service hands over the whole chain, which means one call resolves every cid
belonging to that person and the pull shrinks to roughly the number of people.

Writes data/pr<sport>.json. Checkpoints to git as it goes, because a run this
long that only commits at the end is a run that can lose everything.
"""
import json, os, re, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_main = sys.modules.get('__main__')
if os.path.basename(getattr(_main, '__file__', '') or '') == 'psal_refresh.py':
    _rf = _main
else:
    import psal_refresh as _rf  # noqa: E402
call, pmap = _rf.call, _rf.pmap

SPC = {0: "012", 1: "021"}
CHUNK = 6000            # cids between checkpoints


def clean(v):
    return (v or "").strip()


def num(v):
    v = clean(v)
    return v if v.isdigit() else ""


def archive_cids(datadir):
    """{sportCode: {cid, ...}} over every roster file on disk."""
    out = {c: set() for c in SPC.values()}
    for f in sorted(os.listdir(datadir)):
        if not re.match(r'^r\d{4}\.json$', f):
            continue
        o = json.load(open(os.path.join(datadir, f)))
        for key, rows in o.get("R", {}).items():
            spc = SPC.get(int(key.split(":")[0]))
            if not spc:
                continue
            s = out[spc]
            for r in rows:
                s.add(r[2])
    return out


def load(path):
    if not os.path.exists(path):
        return {"P": {}, "X": {}}
    try:
        o = json.load(open(path))
        o.setdefault("P", {})
        o.setdefault("X", {})
        return o
    except Exception:
        return {"P": {}, "X": {}}


def save(path, o):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(o, f, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, path)


def fetch(spc, cid):
    rows = call("GetPlayerDetails", sportcode="'%s'" % spc,
                playerId="'%d'" % cid, query="'profiledetails'", season=0)
    if not rows:
        return None
    seasons = []
    for r in rows:
        try:
            rcid = int(r.get("cid"))
        except (TypeError, ValueError):
            continue
        seasons.append({
            "y": clean(r.get("season")),
            "c": rcid,
            "s": clean(r.get("cschool")),
            "u": clean(r.get("cuniform")),
            "g": num(r.get("cclass")),
            "p": clean(r.get("cposition")),
        })
    if not seasons:
        return None
    seasons.sort(key=lambda s: s["y"])
    last = rows[-1]
    return {
        "n": ("%s %s" % (clean(last.get("cfname")),
                         clean(last.get("clname")))).strip(),
        "y": seasons,
    }


def commit(repo, path, note):
    """Checkpoint. A push that loses a race is rebased and retried, not lost."""
    try:
        subprocess.run(["git", "config", "user.name", "psal-refresh"],
                       cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email",
                        "actions@users.noreply.github.com"], cwd=repo, check=True)
        subprocess.run(["git", "add", path], cwd=repo, check=True)
        if subprocess.run(["git", "diff", "--cached", "--quiet"],
                          cwd=repo).returncode == 0:
            return
        subprocess.run(["git", "commit", "-q", "-m", note], cwd=repo, check=True)
        for _ in range(3):
            if subprocess.run(["git", "push"], cwd=repo).returncode == 0:
                return
            subprocess.run(["git", "pull", "--rebase", "-q"], cwd=repo)
        print("  ! could not push %s" % note, file=sys.stderr, flush=True)
    except Exception as e:
        print("  ! checkpoint failed (%s): %s" % (note, e), file=sys.stderr, flush=True)


def pull_sport(spc, want, datadir, repo=None):
    path = os.path.join(datadir, "pr%s.json" % spc)
    o = load(path)
    people, index = o["P"], o["X"]

    todo = [c for c in sorted(want) if str(c) not in index]
    print("  %s: %d cids on file, %d already resolved, %d to pull"
          % (spc, len(want), len(want) - len(todo), len(todo)), flush=True)
    if not todo:
        return 0

    lock = threading.Lock()
    pulled = [0]
    t0 = time.time()

    def one(cid):
        # Another cid in this same chunk may have already claimed this person.
        with lock:
            if str(cid) in index:
                return None
        got = fetch(spc, cid)
        if not got:
            return None
        key = str(min(s["c"] for s in got["y"]))
        with lock:
            people[key] = got
            for s in got["y"]:
                index[str(s["c"])] = key
            index.setdefault(str(cid), key)   # a cid the profile did not echo
            pulled[0] += 1
        return key

    for i in range(0, len(todo), CHUNK):
        chunk = [c for c in todo[i:i + CHUNK] if str(c) not in index]
        if not chunk:
            continue
        pmap(one, chunk, "%s %d-%d" % (spc, i, min(i + CHUNK, len(todo))))
        save(path, {"P": people, "X": index})
        done = min(i + CHUNK, len(todo))
        rate = done / max(time.time() - t0, 1)
        print("    checkpoint: %d people, %d cids mapped, %.1f cids/s, "
              "~%.0f min left" % (len(people), len(index), rate,
                                  (len(todo) - done) / max(rate, .01) / 60),
              flush=True)
        if repo:
            commit(repo, os.path.join("data", "pr%s.json" % spc),
                   "Player profiles: %s %d/%d" % (spc, done, len(todo)))

    print("  %s: %d people from %d cids" % (spc, len(people), len(index)),
          flush=True)
    return pulled[0]


def run(datadir, sports=None, commit_repo=None):
    have = archive_cids(datadir)
    for spc in (sports or sorted(have)):
        if not have.get(spc):
            continue
        pull_sport(spc, have[spc], datadir, commit_repo)
