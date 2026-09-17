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

    # ---- careers that may be the same person at a different school.
    # Nothing is merged: name + school stays the identity, and the page offers a
    # link instead of a claim. A pair only qualifies when the seasons don't
    # overlap, sit within a year of each other, and span no more than five
    # seasons all told -- nobody plays high school soccer for six.
    by_name = collections.defaultdict(list)
    for key, p in players.items():
        years = sorted({r[0] for r in p['g']})
        by_name[(p['sp'], p['n'])].append((key, p, years[0], years[-1]))
    for (sp, name), group in by_name.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: t[2])
        for i, (key, p, y0, y1) in enumerate(group):
            for j, (okey, op, oy0, oy1) in enumerate(group):
                if i == j or op['sc'] == p['sc']:
                    continue
                lo, hi = sorted([(y0, y1), (oy0, oy1)])
                if lo[1] >= hi[0]:
                    continue                      # overlapping: two people
                if hi[0] - lo[1] > 1:
                    continue                      # a gap: different cohorts
                if hi[1] - lo[0] + 1 > 5:
                    continue                      # too long to be one student
                p.setdefault('also', []).append([op['slug'], op['sc'], oy0, oy1])

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
        if p.get('also'):
            payload['also'] = sorted(p['also'])
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

    # ---- name index for search.
    # Sharded by the first three letters of each word in a name, so looking
    # someone up costs one small fetch, and there is no file that lists every
    # player -- you have to know roughly who you are looking for. Deliberately carries no per-game numbers: an entry that changed as
    # a player's stats changed would rewrite index files on every refresh.
    live_ids = {}
    if live:
        lp = os.path.join(DATA, 'r%s.json' % live)
        sp_path = os.path.join(DATA, 's%s.json' % live)
        if os.path.exists(lp) and os.path.exists(sp_path):
            rl = json.load(open(lp))
            for gk, rows in rl['R'].items():
                sp = int(gk.split(':')[0])
                for r in rows:
                    nm = rl['P'][r[1]] if r[1] < len(rl['P']) else ''
                    if not nm or not r[0]:
                        continue
                    slug = '%s-%s' % (slugify(nm), school_slugs.get(r[0], slugify(r[0])))
                    live_ids[(sp, slug)] = (nm, r[0])

    index = collections.defaultdict(list)
    entry_by = {}                 # (sp, slug) -> the shared row object

    def add_index(name, slug, sp, code, y0, y1):
        # one row object shared by every prefix it lands in, so widening a span
        # later is a single assignment rather than a scan of the whole index
        row = entry_by.get((sp, slug))
        if row is None:
            row = entry_by[(sp, slug)] = [name, slug, sp, code, y0, y1]
        seen = set()
        for word in slugify(name).split('-'):
            if len(word) < 2:
                continue
            pre = word[:3]
            if pre in seen:
                continue
            seen.add(pre)
            index[pre].append(row)

    for key, p in players.items():
        years = sorted({r[0] for r in p['g']})
        add_index(p['n'], p['slug'], p['sp'], p['sc'], years[0], years[-1])
    liveyr = int(live) if live else 0
    for (sp, slug), (nm, code) in live_ids.items():
        row = entry_by.get((sp, slug))
        if row is not None:
            row[5] = max(row[5], liveyr)      # already indexed; widen the span
            continue
        add_index(nm, slug, sp, code, liveyr, liveyr)

    ndir = os.path.join(DATA, 'n')
    os.makedirs(ndir, exist_ok=True)
    for old in glob.glob(os.path.join(ndir, '*.json')):
        os.remove(old)
    nsizes, deep = [], []
    for pre, rows in index.items():
        rows.sort(key=lambda r: (r[0], r[3]))
        path = os.path.join(ndir, '%s.json' % pre)
        json.dump(rows, open(path, 'w'), separators=(',', ':'))
        size = os.path.getsize(path)
        nsizes.append(size)
        # A handful of prefixes carry a big share of the names -- "mar", "jos",
        # "ale". Those also get four-letter files, so typing one more letter
        # fetches a small one. The three-letter file stays, so a three-letter
        # search still works.
        if size > 40 * 1024:
            deep.append(pre)
            four = collections.defaultdict(list)
            for r in rows:
                for word in slugify(r[0]).split('-'):
                    if word.startswith(pre) and len(word) >= 4:
                        four[word[:4]].append(r)
                        break
            for p4, rs in four.items():
                json.dump(rs, open(os.path.join(ndir, '%s.json' % p4), 'w'),
                          separators=(',', ':'))

    meta = {'shards': SHARDS, 'players': len(players), 'appearances': tot_apps,
            'seasons': seasons, 'live': live, 'missing': missing,
            'indexed': len(players) + len(live_ids), 'prefixes': len(index),
            'deep': sorted(deep)}
    json.dump(meta, open(os.path.join(DATA, 'pmeta.json'), 'w'), separators=(',', ':'))
    return {'players': len(players), 'live_only': len(live_ids),
            'prefix_files': len(index), 'deep_prefixes': len(deep),
            'index_kb_avg': round(sum(nsizes) / max(1, len(nsizes)) / 1024, 1),
            'index_kb_max': round(max(nsizes) / 1024, 1) if nsizes else 0,
            'appearances': tot_apps,
            'shard_kb_avg': round(sum(sizes) / len(sizes) / 1024, 1),
            'shard_kb_max': round(max(sizes) / 1024, 1),
            'total_mb': round(sum(sizes) / 1048576.0, 1),
            'seasons_with_rosters': len(seasons) - len(missing),
            'missing': missing}


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
