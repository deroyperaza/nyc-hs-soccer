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


# PSAL lets coaches type the position by hand, which over 25 years has
# produced 2,786 distinct spellings of four positions -- "Defender", "DEF",
# "def", "D", "Defense", "foward", "MDF". Folding them here rather than in the
# app keeps the files smaller and the rendering dumb.
_POS_PREFIX = (
    ('goal', 'Goalkeeper'), ('keep', 'Goalkeeper'), ('golie', 'Goalkeeper'),
    ('def', 'Defender'), ('back', 'Defender'),
    ('mid', 'Midfielder'), ('half', 'Midfielder'),
    ('forw', 'Forward'), ('fow', 'Forward'), ('for', 'Forward'),
    ('fwd', 'Forward'), ('strik', 'Forward'), ('attack', 'Forward'),
    ('offen', 'Forward'), ('wing', 'Forward'),
)
_POS_EXACT = {
    'gk': 'Goalkeeper', 'g': 'Goalkeeper', 'k': 'Goalkeeper',
    'd': 'Defender', 'df': 'Defender', 'cb': 'Defender', 'lb': 'Defender',
    'rb': 'Defender', 'fb': 'Defender', 'sweeper': 'Defender',
    'stopper': 'Defender', 'centerback': 'Defender',
    'm': 'Midfielder', 'md': 'Midfielder', 'mf': 'Midfielder',
    'mdf': 'Midfielder', 'cm': 'Midfielder', 'dm': 'Midfielder',
    'am': 'Midfielder', 'cdm': 'Midfielder', 'cam': 'Midfielder',
    'f': 'Forward', 'fw': 'Forward', 's': 'Forward', 'st': 'Forward',
    'cf': 'Forward', 'w': 'Forward', 'lw': 'Forward', 'rw': 'Forward',
}
_POS_ORDER = {'Goalkeeper': 0, 'Defender': 1, 'Midfielder': 2, 'Forward': 3}


def norm_position(raw):
    out = []
    for part in re.split(r"[,/&;+\-]|\band\b", raw or ''):
        t = re.sub(r'[^a-z]', '', part.lower())
        if not t:
            continue
        hit = _POS_EXACT.get(t)
        if not hit:
            for pre, name in _POS_PREFIX:
                if t.startswith(pre):
                    hit = name
                    break
        if hit and hit not in out:
            out.append(hit)
    out.sort(key=lambda x: _POS_ORDER[x])
    return '/'.join(out)


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


def canonical_names(DATA, seasons, live):
    """One person can appear under more than one spelling, and it is nearly
    always PSAL's field widths rather than a real second player.

    Two systematic shapes show up in the data:
      * per-word truncation -- older seasons cut each name part, so CHRISTIAN
        SON is filed as CHRISTI SON, SEBASTIAN COCIOBA as SEBASTI COCIOBA;
      * whole-string truncation -- long names stop at the field limit, so
        JEFFERSON CASTILLO ALVAREZ is filed as JEFFERSON CASTILLO ALVARE.

    Both are merged, but only when the two spellings sit at the same school in
    the same sport and their seasons don't overlap and are within a year of each
    other -- a real pair of same-named teammates would overlap. A longer name
    that adds a whole new word (JOSE RAMALES -> JOSE RAMALES FLORES) is NOT
    merged: that is as likely to be two people as one.

    data/name_fixes.json handles the rest -- plain misspellings, which no rule
    can catch. Each entry is [sport, schoolCode, asFiled, correct].
    """
    spans = collections.defaultdict(lambda: [9999, 0])
    for sid in seasons + ([live] if live else []):
        rp = os.path.join(DATA, 'r%s.json' % sid)
        if not os.path.exists(rp):
            continue
        R = json.load(open(rp))
        P = R['P']
        y = int(sid)
        for gk, rows in R['R'].items():
            sp = int(gk.split(':')[0])
            for r in rows:
                nm = P[r[1]] if r[1] < len(P) else ''
                if not nm or not r[0]:
                    continue
                sl = spans[(sp, r[0], nm)]
                sl[0] = min(sl[0], y); sl[1] = max(sl[1], y)

    by_school = collections.defaultdict(list)
    for (sp, code, nm), (y0, y1) in spans.items():
        by_school[(sp, code)].append((nm, y0, y1))

    fix = {}
    for key, people in by_school.items():
        buckets = collections.defaultdict(list)
        for t in people:
            buckets[t[0][:6]].append(t)
        for grp in buckets.values():
            for a_ in grp:
                for b_ in grp:
                    if a_ is b_ or len(a_[0]) >= len(b_[0]):
                        continue
                    if not (a_[2] < b_[1] or b_[2] < a_[1]):
                        continue                      # overlapping: two people
                    gap = b_[1] - a_[2] if a_[2] < b_[1] else a_[1] - b_[2]
                    if gap > 1:
                        continue
                    aw, bw = a_[0].split(), b_[0].split()
                    per_word = (len(aw) == len(bw) and aw != bw and
                                all(y.startswith(x) for x, y in zip(aw, bw)))
                    whole = b_[0].startswith(a_[0]) and len(a_[0]) >= 20
                    if per_word or whole:
                        fix[(key[0], key[1], a_[0])] = b_[0]

    auto = len(fix)
    path = os.path.join(DATA, 'name_fixes.json')
    manual = 0
    if os.path.exists(path):
        try:
            for sp, code, wrong, right in json.load(open(path)):
                fix[(int(sp), code, wrong)] = right
                manual += 1
        except Exception as e:
            print('name_fixes.json ignored: %s' % e)

    # follow chains so A -> B -> C lands everyone on C
    def resolve(sp, code, nm, depth=0):
        nxt = fix.get((sp, code, nm))
        if nxt is None or depth > 4:
            return nm
        return resolve(sp, code, nxt, depth + 1)
    fix = {k: resolve(k[0], k[1], v) for k, v in fix.items()}
    return fix, auto, manual


def build(skip=None):
    seasons = sorted(m.group(1) for m in
                     (re.match(r'^s(\d{4})\.json$', f) for f in os.listdir(DATA)) if m)
    # The current season is deliberately left out. The app already holds it in
    # the payload it boots with, so it can assemble those rows itself -- which
    # means an hourly refresh never rewrites a single shard.
    live = skip or (seasons[-1] if seasons else None)
    seasons = [s for s in seasons if s != live]
    namefix, auto_fixes, manual_fixes = canonical_names(DATA, seasons, live)

    # ---- who is who, according to PSAL.
    # data/pr<sport>.json is the player-profile backfill: every cid the archive
    # mentions, resolved through GetPlayerDetails, which returns each season a
    # person played under whichever cid that year issued. That is an identity
    # the box scores cannot express -- cid is reissued annually -- and it
    # replaces the name+school rule this file used to guess with. X maps any
    # cid to the person; P carries the name PSAL filed plus, per season, the
    # school, uniform number, grade and position.
    prof, pidx = {}, {}
    for sp, spc in ((0, '012'), (1, '021')):
        path = os.path.join(DATA, 'pr%s.json' % spc)
        if not os.path.exists(path):
            continue
        o = json.load(open(path))
        for cid, key in o.get('X', {}).items():
            pidx[(sp, int(cid))] = key
        for key, v in o.get('P', {}).items():
            prof[(sp, key)] = v

    players = {}
    missing = []
    short_all, full_all = {}, {}

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
        # A transfer's page names schools from several seasons, so the team
        # names have to outlive the season file they came from.
        for t in season['T']:
            short_all[(t[0], t[1])] = t[4] if len(t) > 4 else t[2]
            full_all[(t[0], t[1])] = t[2]

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
                raw = name
                name = namefix.get((sp, school, name), name)
                home = school == g[4]
                opp = g[5] if home else g[4]
                gf = g[6] if home else g[7]
                gaN = g[7] if home else g[6]
                # PSAL's own person id where it has one; the old name+school
                # rule only as a fallback, for a cid the backfill never saw.
                pkey = pidx.get((sp, cid))
                pid = ('%d\t%s' % (sp, pkey) if pkey
                       else '%d\t%s\t%s' % (sp, school, name))
                p = players.get(pid)
                if p is None:
                    p = players[pid] = {
                        'n': name, 'sp': sp, 'key': pkey,
                        'ys': {}, 'seen': set(), 'g': [],
                    }
                p['ys'][int(sid)] = school
                p['seen'].add((school, name))
                p['seen'].add((school, raw))
                p['g'].append([int(sid), g[1], g[2], opp,
                               1 if home else 0, gf, gaN,
                               1 if g[10] == 1 else 0,
                               go, a, sv, sh, ga])

    # ---- names, schools and per-season detail from the profile backfill.
    for pid, p in players.items():
        pr = prof.get((p['sp'], p['key'])) if p.get('key') else None
        if pr and pr.get('n'):
            # PSAL's own spelling, which is not truncated the way a box-score
            # row can be -- but is not immune to a typo either. Mamdani is
            # filed as MOMDANI on his profile and as MAMDANI in three of his
            # four box scores, so the corrections still get the last word.
            nm = pr['n']
            for code in set(p['ys'].values()):
                nm = namefix.get((p['sp'], code, nm), nm)
            p['n'] = nm
        last = max(p['ys'])
        p['sc'] = p['ys'][last]       # the school they finished at
        p['sn'] = short_all.get((p['sp'], p['sc']), p['sc'])
        p['fn'] = full_all.get((p['sp'], p['sc']), p['sc'])
        p['meta'] = {}
        for e in (pr or {}).get('y', []):
            try:
                p['meta'][int(e['y'])] = e
            except (TypeError, ValueError):
                pass

    # ---- slugs. The identity is settled, so a slug only has to be a stable,
    # readable address for it: the name PSAL filed plus the school the player
    # finished at. A transfer gets one page, at the school they ended up at,
    # and every spelling and school they passed through becomes a stub that
    # points at it -- so a link built from an old roster row still lands.
    school_slugs = json.load(open(os.path.join(DATA, 'slugs.json')))
    groups = collections.defaultdict(list)
    for pid, p in sorted(players.items()):
        p['slug0'] = '%s-%s' % (slugify(p['n']),
                                school_slugs.get(p['sc'], slugify(p['sn'])))
        groups[(p['sp'], p['slug0'])].append(p)

    def span(p):
        y = sorted(p['ys'])
        return y[0], y[-1]

    def absorb(a, b):
        a['g'].extend(b['g'])
        a['ys'].update(b['ys'])
        a['seen'] |= b['seen']
        a['meta'].update(b['meta'])

    players, collisions, suffixed = {}, 0, 0
    for (sp, slug), grp in sorted(groups.items()):
        if len(grp) > 1:
            # PSAL has no opinion here: it kept these apart, but they share a
            # name and a school, so they share an address and something has to
            # decide. Seasons that sit next to each other and fit inside a high
            # school career are one student PSAL failed to link; seasons that
            # overlap, or sit years apart, are two students.
            grp.sort(key=lambda q: span(q))
            clusters = [grp[0]]
            for q in grp[1:]:
                a0, a1 = span(clusters[-1])
                b0, b1 = span(q)
                if b0 > a1 and b0 - a1 <= 1 and b1 - a0 + 1 <= 5:
                    absorb(clusters[-1], q)
                else:
                    clusters.append(q)
            grp = clusters
            if len(grp) > 1:
                collisions += 1
        # Most recent keeps the bare slug: that is the one people are looking
        # up, and the one a link off this season's roster will derive.
        grp.sort(key=lambda q: span(q)[1], reverse=True)
        for i, q in enumerate(grp):
            q['slug'] = slug if i == 0 else '%s-%d' % (slug, i + 1)
            if i:
                suffixed += 1
            players['%d/%s' % (sp, q['slug'])] = q
        if len(grp) > 1:
            for q in grp:
                for o in grp:
                    if o is q:
                        continue
                    oy = span(o)
                    q.setdefault('also', []).append([o['slug'], o['sc'], oy[0], oy[1]])

    shards = collections.defaultdict(dict)
    tot_apps = 0
    for key, p in players.items():
        p['g'].sort(key=lambda r: (r[0], r[2]))
        tot_apps += len(p['g'])
        by_year = collections.OrderedDict()
        for r in p['g']:
            by_year.setdefault(r[0], []).append(r[1:])
        # Number, grade and position travel in their own map rather than
        # inside the season rows, because they cover the live season too --
        # the rows for that are stitched in by the app, but a jersey number
        # does not change hourly the way a goal tally does.
        detail = {}
        for y, e in p['meta'].items():
            m = {}
            if e.get('u'):
                m['u'] = e['u']
            if e.get('g'):
                m['g'] = e['g']
            pos = norm_position(e.get('p'))
            if pos:
                m['p'] = pos
            code = p['ys'].get(y)
            if code and code != p['sc']:
                m['sc'] = code            # the season they spent elsewhere
                m['sn'] = short_all.get((p['sp'], code), code)
            if m:
                detail[str(y)] = m
        payload = {
            'n': p['n'], 'sp': p['sp'], 'sc': p['sc'], 'fn': p['fn'],
            's': [[y, rows] for y, rows in by_year.items()],
        }
        if detail:
            payload['m'] = detail
        if p.get('also'):
            payload['also'] = sorted(p['also'])
        shards[shard_of(key)][key] = payload

    # A link built from a roster row is derived in the browser from that row's
    # own spelling and school, which for a transfer -- or a truncated name --
    # is not where the career lives. Every combination the player was ever
    # filed under gets a one-line stub pointing at the real page, so no link
    # the app can construct leads nowhere.
    stubs = 0
    for key, p in players.items():
        for code, spelling in p['seen']:
            alias = '%d/%s-%s' % (p['sp'], slugify(spelling),
                                  school_slugs.get(code, slugify(code)))
            if alias == key or alias in players or alias in shards[shard_of(alias)]:
                continue
            shards[shard_of(alias)][alias] = {'ref': key}
            stubs += 1

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
                    nm = namefix.get((sp, r[0], nm), nm)
                    slug = '%s-%s' % (slugify(nm), school_slugs.get(r[0], slugify(r[0])))
                    live_ids[(sp, slug)] = (nm, r[0], r[2])

    index = collections.defaultdict(list)
    entry_by = {}                 # (sp, slug) -> the shared row object

    def add_index(name, slug, sp, code, y0, y1, uni=''):
        # one row object shared by every prefix it lands in, so widening a span
        # later is a single assignment rather than a scan of the whole index
        # The jersey number rides along so the players page can show it without
        # opening a career shard per row. It is the most recent one PSAL has,
        # and it changes at most once a season, so it does not churn the index
        # the way a stat would.
        row = entry_by.get((sp, slug))
        if row is None:
            row = entry_by[(sp, slug)] = ([name, slug, sp, code, y0, y1] +
                                          ([uni] if uni else []))
        seen = set()
        for word in slugify(name).split('-'):
            if len(word) < 2:
                continue
            pre = word[:3]
            if pre in seen:
                continue
            seen.add(pre)
            index[pre].append(row)

    def newest_uniform(meta):
        for y in sorted(meta, reverse=True):
            if meta[y].get('u'):
                return meta[y]['u']
        return ''

    for key, p in players.items():
        years = sorted({r[0] for r in p['g']})
        add_index(p['n'], p['slug'], p['sp'], p['sc'], years[0], years[-1],
                  newest_uniform(p['meta']))
    liveyr = int(live) if live else 0
    for (sp, slug), (nm, code, cid) in live_ids.items():
        row = entry_by.get((sp, slug))
        if row is not None:
            row[5] = max(row[5], liveyr)      # already indexed; widen the span
            # a career that is still going: this season's shirt is the current
            # one, and the shards stop at last season
            pk = pidx.get((sp, cid))
            cur = ''
            for e in (prof.get((sp, pk)) or {}).get('y', []):
                if e.get('y') == str(liveyr) and e.get('u'):
                    cur = e['u']
            if cur:
                if len(row) > 6:
                    row[6] = cur
                else:
                    row.append(cur)
            continue
        pk = pidx.get((sp, cid))
        uni = ''
        for e in (prof.get((sp, pk)) or {}).get('y', []):
            if e.get('y') == str(liveyr) and e.get('u'):
                uni = e['u']
        add_index(nm, slug, sp, code, liveyr, liveyr, uni)

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

    # ---- numbers and grades by cid, one file per season.
    # A roster fold on a box score has the cid in hand and nothing else, so it
    # can look a player up here without knowing which career page they belong
    # to. Keyed by cid because that is what the roster rows carry.
    udir = DATA
    useasons = collections.defaultdict(dict)
    for (sp, key), v in prof.items():
        for e in v.get('y', []):
            row = [e.get('u') or '', e.get('g') or '', norm_position(e.get('p'))]
            if any(row):
                useasons[e['y']][str(e['c'])] = row
    for y, rows in useasons.items():
        json.dump(rows, open(os.path.join(udir, 'pu%s.json' % y), 'w'),
                  separators=(',', ':'))

    meta = {'shards': SHARDS, 'players': len(players), 'appearances': tot_apps,
            'seasons': seasons, 'live': live, 'missing': missing,
            'indexed': len(players) + len(live_ids), 'prefixes': len(index),
            'deep': sorted(deep)}
    json.dump(meta, open(os.path.join(DATA, 'pmeta.json'), 'w'), separators=(',', ':'))
    return {'players': len(players), 'live_only': len(live_ids),
            'name_merges_auto': auto_fixes, 'name_merges_manual': manual_fixes,
            'alias_stubs': stubs,
            'psal_identity': sum(1 for v in players.values() if v.get('key')),
            'name_school_fallback': sum(1 for v in players.values() if not v.get('key')),
            'slug_collisions': collisions, 'suffixed_slugs': suffixed,
            'transfers': sum(1 for v in players.values()
                             if len({c for c in v['ys'].values()}) > 1),
            'prefix_files': len(index), 'deep_prefixes': len(deep),
            'index_kb_avg': round(sum(nsizes) / max(1, len(nsizes)) / 1024, 1),
            'index_kb_max': round(max(nsizes) / 1024, 1) if nsizes else 0,
            'appearances': tot_apps,
            'shard_kb_avg': round(sum(sizes) / len(sizes) / 1024, 1),
            'shard_kb_max': round(max(sizes) / 1024, 1),
            'total_mb': round(sum(sizes) / 1048576.0, 1),
            'seasons_with_rosters': len(seasons) - len(missing),
            'uniform_files': len(useasons),
            'missing': missing}


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
