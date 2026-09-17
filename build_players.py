#!/usr/bin/env python3
"""Build player pages' data from the backfilled rosters.

Identity: a player is one person per (sport, school, name). PSAL's cid is
stable within a season but reissued every year, so a career can only be joined
by matching the name at the same school -- deliberately conservative. A player
who transfers shows up as two pages rather than risking two different kids
being merged into one.

The slug carries both halves of that rule, so the app can derive a player's URL
from a roster row without a lookup table:

    /player/<name>-<school>/<sport>      e.g. /player/zohran-mamdani-bronx-science/boys

Output:
  data/p/<xx>.json   career payloads, sharded by a hash of the slug so a player
                     page fetches exactly one small file
  data/pmeta.json    shard count + counts, read at boot (tiny)
"""
import json, os, re, sys, glob, collections, unicodedata

DATA = os.environ.get('PSAL_OUT', '/home/claude/psal/out/data')
# 1024 keeps a shard near 100KB once the full rosters are in -- one small
# fetch per player page, and no index file to load up front.
SHARDS = int(os.environ.get('PSAL_SHARDS', '1024'))
SPORT_PATH = {0: 'boys', 1: 'girls'}


def slugify(name):
    # Accents are folded rather than dropped so the slug the app derives in the
    # browser (NFD + strip combining marks) matches this one exactly.
    name = unicodedata.normalize('NFD', name or '')
    name = ''.join(c for c in name if not unicodedata.combining(c))
    out, dash = [], False
    for ch in name.lower():
        if ('a' <= ch <= 'z') or ('0' <= ch <= '9'):
            out.append(ch); dash = False
        elif not dash and out:
            out.append('-'); dash = True
    return ''.join(out).strip('-')


def hexname(i):
    return '%03x.json' % i


def shard_of(slug, shards=SHARDS):
    """FNV-1a, mirrored in the app so it can find a player's shard offline."""
    h = 2166136261
    for ch in slug:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h % shards


def build(skip=None):
    seasons = sorted(m.group(1) for m in
                     (re.match(r'^s(\d{4})\.json$', f) for f in os.listdir(DATA)) if m)
    # The current season is deliberately left out. The app already holds it in
    # the payload it boots with, so it can assemble those rows itself -- which
    # means an hourly refresh never rewrites a single shard.
    live = skip or (seasons[-1] if seasons else None)
    seasons = [s for s in seasons if s != live]
    players = {}
    missing = []

    for sid in seasons:
        rpath = os.path.join(DATA, 'r%s.json' % sid)
        if not os.path.exists(rpath):
            missing.append(sid)
            continue
        season = json.load(open(os.path.join(DATA, 's%s.json' % sid)))
        rost = json.load(open(rpath))
        P, R = rost['P'], rost['R']

        games = {'%d:%d' % (g[0], g[1]): g for g in season['G']}
        short = {'%d:%s' % (t[0], t[1]): (t[4] if len(t) > 4 else t[2]) for t in season['T']}
        full = {'%d:%s' % (t[0], t[1]): t[2] for t in season['T']}

        for key, rows in R.items():
            g = games.get(key)
            if not g:
                continue
            sp = g[0]
            for r in rows:
                school, nidx, cid, go, a, sv, sh, ga = r
                name = P[nidx] if nidx < len(P) else ''
                if not name or not school:
                    continue
                home = school == g[4]
                opp = g[5] if home else g[4]
                gf = g[6] if home else g[7]
                gaN = g[7] if home else g[6]
                pid = '%d\t%s\t%s' % (sp, school, name)
                p = players.get(pid)
                if p is None:
                    p = players[pid] = {
                        'n': name, 'sp': sp, 'sc': school,
                        'sn': short.get('%d:%s' % (sp, school), school),
                        'fn': full.get('%d:%s' % (sp, school), school),
                        'g': [],
                    }
                p['g'].append([int(sid), g[1], g[2], opp,
                               1 if home else 0, gf, gaN,
                               1 if g[10] == 1 else 0,
                               go, a, sv, sh, ga])

    # ---- slugs. name + school is the identity, so the slug spells out both and
    # the app can derive it from a roster row with no lookup table. The school
    # half reuses build2.py's own slug map (written to slugs.json) rather than a
    # second copy of the rules, so the two can never drift apart.
    school_slugs = json.load(open(os.path.join(DATA, 'slugs.json')))
    for pid, p in sorted(players.items()):
        p['slug'] = '%s-%s' % (slugify(p['n']),
                               school_slugs.get(p['sc'], slugify(p['sn'])))
    # Two players who slug the same are the same person under the stated rule
    # (same sport, same school, same name), so they merge rather than split --
    # a split would leave one of them unreachable from a linked name.
    merged = {}
    for pid, p in sorted(players.items()):
        k = '%d/%s' % (p['sp'], p['slug'])
        if k in merged:
            merged[k]['g'].extend(p['g'])
        else:
            merged[k] = p
    players = {k: v for k, v in merged.items()}

    shards = collections.defaultdict(dict)
    tot_apps = 0
    for key, p in players.items():
        p['g'].sort(key=lambda r: (r[0], r[2]))
        tot_apps += len(p['g'])
        by_year = collections.OrderedDict()
        for r in p['g']:
            by_year.setdefault(r[0], []).append(r[1:])
        payload = {
            'n': p['n'], 'sp': p['sp'], 'sc': p['sc'], 'fn': p['fn'],
            's': [[y, rows] for y, rows in by_year.items()],
        }
        shards[shard_of(key)][key] = payload

    outdir = os.path.join(DATA, 'p')
    os.makedirs(outdir, exist_ok=True)
    for old in glob.glob(os.path.join(outdir, '*.json')):
        os.remove(old)
    sizes = []
    for i in range(SHARDS):
        path = os.path.join(outdir, hexname(i))
        json.dump(shards.get(i, {}), open(path, 'w'), separators=(',', ':'))
        sizes.append(os.path.getsize(path))

    meta = {'shards': SHARDS, 'players': len(players), 'appearances': tot_apps,
            'seasons': seasons, 'live': live, 'missing': missing}
    json.dump(meta, open(os.path.join(DATA, 'pmeta.json'), 'w'), separators=(',', ':'))
    return {'players': len(players), 'appearances': tot_apps,
            'shard_kb_avg': round(sum(sizes) / len(sizes) / 1024, 1),
            'shard_kb_max': round(max(sizes) / 1024, 1),
            'total_mb': round(sum(sizes) / 1048576.0, 1),
            'seasons_with_rosters': len(seasons) - len(missing),
            'missing': missing}


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
