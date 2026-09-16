#!/usr/bin/env python3
"""Convert raw psal_<season>.json pulls into compact per-season app files."""
import json, os, glob, re, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shorten import shorten

RAW = '/mnt/user-data/uploads/Downloads'
OUT = '/home/claude/psal/out/data'
SPORTS = {'012': 0, '021': 1}

def dnum(s):
    m = re.search(r'\((-?\d+)', s or '')
    if not m: return 0
    ms = int(m.group(1))
    d = datetime.datetime(1970,1,1) + datetime.timedelta(milliseconds=ms)
    return d.year*10000 + d.month*100 + d.day

def code(x):
    return str(x).zfill(5)

def sc(v):
    if v is None or v == '': return None
    try: return int(round(float(v)))
    except: return None

def klass(div):
    m = re.match(r'\s*(\d[A-D]|[A-D])\b', div or '')
    return m.group(1) if m else ''

# PSAL renamed its soccer levels: through 2024 the top flight was "1A" with B/C/D below;
# from 2025 the ladder is 3A (top), 2A, 1A.
NEW_TIER = {'3A': 0, '2A': 1, '1A': 2}
OLD_TIER = {'1A': 0, 'A': 0, 'B': 1, 'C': 2, 'D': 3}

def tier_of(cls, new_scheme):
    if new_scheme:
        return NEW_TIER.get(cls, 3)
    return OLD_TIER.get(cls, 3)

def boro_of(div):
    p = (div or '').split('--')
    return p[1].strip() if len(p) > 1 else ''

def src_for(season):
    cands = [p for p in glob.glob(os.path.join(RAW, '*%s*.json' % season)) if re.match(r'psal2?_%s(\b|[_.(])' % season, os.path.basename(p))]
    if not cands:
        raise IOError('no raw file for season %s' % season)
    return max(cands, key=os.path.getsize)

def flags_for(season):
    for name in ('psalfl2_%s.json' % season, 'psalflags_%s.json' % season):
        p = os.path.join(RAW, name)
        if os.path.exists(p):
            try: return json.load(open(p))
            except Exception: pass
    return None

def convert(season):
    raw = json.load(open(src_for(season)))
    FL = flags_for(season)
    D, Di = [], {}
    L, Li = [], {}
    RS, RSi = [], {}
    P, Pi = [], {}
    R, Ri = [], {}
    AD, ADi = [], {}
    def ix(arr, m, s):
        if s is None or s == '': return -1
        if s not in m:
            m[s] = len(arr); arr.append(s)
        return m[s]

    teams = {}          # (sp, code) -> [name, divIdx]
    stand = []
    games = []
    det = {}

    for spc, sp in SPORTS.items():
        blk = raw['sports'].get(spc)
        if not blk: continue
        # standings + division membership
        for s in blk['standings']:
            di = ix(D, Di, s['name'])
            rows = []
            for r in s['rows']:
                c = code(r[0])
                rows.append([c, r[2], r[3], r[4], r[5]])
                teams.setdefault((sp, c), [r[1], di])
                if teams[(sp, c)][1] == -1: teams[(sp, c)][1] = di
            if rows: stand.append([sp, di, rows])
        # games
        for g in blk['games']:
            gid = g['id']
            d = blk['detail'].get(str(gid)) or blk['detail'].get(gid) or {}
            hc = d.get('hc') or code(g['h'])
            ac = d.get('ac') or code(g['a'])
            teams.setdefault((sp, hc), [g['hn'], -1])
            teams.setdefault((sp, ac), [g['an'], -1])
            reason = (g.get('st') or d.get('re') or '').strip()
            hs, as_ = sc(d.get('hs')), sc(d.get('as'))
            po = 0
            if FL is not None:
                f = FL.get('%d:%d' % (sp, gid))
                if f:
                    lg = f[1]
                    if isinstance(lg, str):
                        u = lg.upper()
                        po = 1 if u == 'P' else (2 if u == 'N' else 0)
                    else:
                        po = 1 if lg else 0
                    if f[0]:
                        hs, as_ = sc(f[3]), sc(f[4])
                    else:
                        hs = as_ = None
                    if len(f) > 5 and f[5] and not reason:
                        reason = f[5]
                else:
                    hs = as_ = None
            games.append([sp, gid, dnum(g['d']), (g.get('t') or '').strip(),
                          hc, ac, hs, as_,
                          ix(RS, RSi, reason.upper() if reason else ''),
                          ix(L, Li, (g.get('loc') or '').strip()), po, -1])
            # detail
            if d:
                ph = [sc(x) for x in (d.get('ph') or [])]
                pa = [sc(x) for x in (d.get('pa') or [])]
                while ph and (ph[-1] in (None, 0)): ph.pop()
                while pa and (pa[-1] in (None, 0)): pa.pop()
                box = []
                for b in (d.get('b') or []):
                    box.append([code(b[0]), ix(P, Pi, b[1]), b[2], b[3], b[4], b[5], b[6]])
                refs = [ix(R, Ri, x) for x in (d.get('rf') or [])]
                entry = [ix(AD, ADi, (d.get('ad') or '').strip()), refs, ph, pa, box,
                         ix(R, Ri, d.get('tr'))]
                if any([entry[0] != -1, refs, ph, pa, box, entry[5] != -1]):
                    det['%d:%d' % (sp, gid)] = entry

    # ---- playoff detection + rounds ----
    tdiv = {k: v[1] for k, v in teams.items()}
    def cls_of(sp, c):
        di = tdiv.get((sp, c), -1)
        return klass(D[di]) if di >= 0 else ''
    if FL is None:
        dates = sorted(set(g[2] for g in games if g[2]))
        cutoff = dates[int(len(dates)*0.80)] if dates else 0
        for g in games:
            sp, hc, ac = g[0], g[4], g[5]
            dh, da = tdiv.get((sp, hc), -1), tdiv.get((sp, ac), -1)
            if g[2] >= cutoff and dh != da and cls_of(sp, hc) and cls_of(sp, hc) == cls_of(sp, ac):
                g[10] = 1
    # rounds: per sport+class, group playoff games by date, label from the end
    RD = ['Opening Round', 'Round of 32', 'Round of 16', 'Quarterfinals', 'Semifinals', 'Final']
    def round_idx(n):
        return {1:5, 2:4, 4:3, 8:2, 16:1}.get(n, 0)
    new_scheme = any(klass(d) == '3A' for d in D)
    TI = [tier_of(klass(d), new_scheme) for d in D]

    # ---- brackets: connected components of playoff games (teams that meet share a bracket) ----
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    po_games = [g for g in games if g[10] == 1]
    for g in po_games:
        union((g[0], g[4]), (g[0], g[5]))
    comps = {}
    for g in po_games:
        comps.setdefault(find((g[0], g[4])), []).append(g)

    BR = []
    for root, gs in comps.items():
        if len(gs) < 3:
            # a stray one-off (usually a cancelled crossover) is not a bracket
            for g in gs:
                g[11] = -1
                g.append(-1)
            continue
        # round labels: in a single-elimination bracket the number of games played after
        # a round is fixed (final 0, semis 1, quarters 3, R16 7, R32 15)
        dates = sorted(g[2] for g in gs)
        for g in gs:
            after = sum(1 for d in dates if d > g[2])
            if after == 0:      ri = 5
            elif after <= 2:    ri = 4
            elif after <= 6:    ri = 3
            elif after <= 14:   ri = 2
            elif after <= 30:   ri = 1
            else:               ri = 0
            g[11] = ri
        # label the bracket by the class most of its teams sit in
        counts, tiers = {}, []
        seen_teams = set()
        for g in gs:
            for tcode in (g[4], g[5]):
                key = (g[0], tcode)
                if key in seen_teams:
                    continue
                seen_teams.add(key)
                di = tdiv.get(key, -1)
                if di < 0:
                    continue
                c = klass(D[di])
                if not c:
                    continue
                counts[c] = counts.get(c, 0) + 1
                tiers.append(tier_of(c, new_scheme))
        label = max(counts, key=lambda c: counts[c]) if counts else ''
        tier = min(tiers) if tiers else 3
        bi = len(BR)
        BR.append([label, tier])
        for g in gs:
            g.append(bi)
    for g in games:
        if len(g) < 13:
            g.append(-1)

    T = [[k[0], k[1], v[0], v[1], shorten(v[0])] for k, v in sorted(teams.items())]
    # keep short names unique within a season+sport
    seen = {}
    for row in T:
        seen.setdefault((row[0], row[4]), []).append(row)
    for (sp_, sn), rows_ in seen.items():
        names = {r[2] for r in rows_}
        if len(names) > 1:
            for r in rows_:
                r[4] = r[2]
    yr = int(season) - 1
    out = {
        'id': season, 'label': 'Fall %d' % yr, 'scheme': 'new' if new_scheme else 'old',
        'T': T, 'D': D, 'TI': TI, 'BR': BR, 'S': stand, 'L': L, 'RS': RS,
        'P': P, 'R': R, 'AD': AD, 'RD': RD,
        'G': games, 'X': det,
    }
    path = os.path.join(OUT, 's%s.json' % season)
    with open(path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    return {'season': season, 'flags': FL is not None, 'games': len(games), 'detail': len(det), 'teams': len(T),
            'divs': len(D), 'players': len(P), 'po': sum(1 for g in games if g[10]),
            'bytes': os.path.getsize(path)}

if __name__ == '__main__':
    if sys.argv[1:]:
        seasons = sys.argv[1:]
    else:
        seasons = sorted({re.search(r'psal2?_(\d{4})', os.path.basename(p)).group(1)
                          for p in glob.glob(os.path.join(RAW, 'psal*_*.json'))
                          if re.search(r'psal2?_(\d{4})', os.path.basename(p))})
    for s in seasons:
        try:
            print(convert(s))
        except Exception as e:
            print('FAIL', s, type(e).__name__, e)
