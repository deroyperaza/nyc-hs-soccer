#!/usr/bin/env python3
"""Build the NYC High School Soccer page + history.json from converted season files."""
import json, os, glob, re, datetime, sys

BASE = os.environ.get('PSAL_BASE', '/home/claude/psal')
# In CI the repo keeps data/ and index.html at the top level, so each path is
# overridable rather than assuming the local out/ layout.
DATA = os.environ.get('PSAL_OUT',  os.path.join(BASE, 'out', 'data'))
TPL  = os.environ.get('PSAL_TPL',  os.path.join(BASE, 'app.template.html'))
PAGE = os.environ.get('PSAL_PAGE', os.path.join(BASE, 'out', 'index.html'))

SEASON_FILE = re.compile(r'^s(\d{4})\.json$')


def season_ids(datadir):
    """Only real season files -- data/ also holds slugs.json, pmeta.json and the
    roster files, and a bare s*.json glob happily swallows them."""
    return sorted(m.group(1) for m in
                  (SEASON_FILE.match(f) for f in os.listdir(datadir)) if m)


def load_all():
    out = {}
    for sid in season_ids(DATA):
        out[sid] = json.load(open(os.path.join(DATA, 's%s.json' % sid)))
    return out

def build(updated=None, current=None):
    seasons = load_all()
    ids = sorted(seasons.keys())
    cur = current or ids[-1]

    teams, champs, titles, finals = {}, {}, {}, {}
    # one short name per school for the whole archive, latest season wins --
    # player pages need to name opponents from seasons they haven't loaded
    global_short = {}
    for sid in ids:
        o = seasons[sid]
        D = o['D']
        # ---- playoff performance per team for this season ----
        po_wins, po_best, po_title = {}, {}, set()
        po_loss, po_tie = {}, {}
        for g in o['G']:
            if g[10] != 1 or g[6] is None or g[7] is None:
                continue
            hk, ak = '%d:%s' % (g[0], g[4]), '%d:%s' % (g[0], g[5])
            ri = g[11] if g[11] is not None else -1
            for k in (hk, ak):
                po_best[k] = max(po_best.get(k, -1), ri)
            if g[6] == g[7]:
                # drawn playoff ties are rare but real in the archive
                for k in (hk, ak):
                    po_tie[k] = po_tie.get(k, 0) + 1
                continue
            win, lose = (hk, ak) if g[6] > g[7] else (ak, hk)
            po_wins[win] = po_wins.get(win, 0) + 1
            po_loss[lose] = po_loss.get(lose, 0) + 1
            if ri == 5:
                po_title.add(win)
        champs[sid] = {'0': [], '1': []}
        name_by, short_by = {}, {}
        for t in o['T']:
            name_by['%d:%s' % (t[0], t[1])] = t[2]
            short_by['%d:%s' % (t[0], t[1])] = t[4] if len(t) > 4 else t[2]
        for k_, v_ in short_by.items():
            global_short[k_.split(':')[1]] = v_
        for sp, di, rows in o['S']:
            srt = sorted(rows, key=lambda r: (-r[4], -r[1], r[2]))
            top = []
            for r in srt[:2]:
                top.append([r[0], short_by.get('%d:%s' % (sp, r[0]), r[0]), r[1], r[2], r[3], r[4]])
            while len(top) < 2:
                top.append(None)
            champs[sid][str(sp)].append([D[di], top[0], top[1]])
            for r in rows:
                k = '%d:%s' % (sp, r[0])
                e = teams.setdefault(k, {'n': name_by.get(k, r[0]), 'sn': short_by.get(k, r[0]), 's': []})
                cls = (D[di] or '').split('--')[0].strip()
                tier = o.get('TI', [])[di] if di < len(o.get('TI', [])) else 3
                best = po_best.get(k, -1)
                res = 0
                if k in po_title: res = 6
                elif best == 5: res = 5
                elif best == 4: res = 4
                elif best == 3: res = 3
                elif best == 2: res = 2
                elif best >= 0: res = 1
                e['s'].append([int(sid), r[1], r[2], r[3], r[4], cls, po_wins.get(k, 0), res, tier,
                               po_wins.get(k, 0), po_loss.get(k, 0), po_tie.get(k, 0)])
                if name_by.get(k):
                    e['n'] = name_by[k]
                    e['sn'] = short_by.get(k, e['n'])
        # city finals: one per class per sport
        finals[sid] = {'0': [], '1': []}
        TI = o.get('TI', [])
        cls_of_div = {}
        tier_of_div = {}
        for i, dname in enumerate(D):
            c = (dname or '').split('--')[0].strip()
            cls_of_div[i] = c
            tier_of_div[i] = TI[i] if i < len(TI) else 3
        divi = {}
        for t in o['T']:
            divi['%d:%s' % (t[0], t[1])] = t[3]
        for g in o['G']:
            if g[10] != 1 or g[11] != 5 or g[6] is None or g[7] is None:
                continue
            hk, ak = '%d:%s' % (g[0], g[4]), '%d:%s' % (g[0], g[5])
            BRs = o.get('BR', [])
            bi = g[12] if len(g) > 12 else -1
            if 0 <= bi < len(BRs):
                cls, tier = BRs[bi][0], BRs[bi][1]
            else:
                di = divi.get(hk, -1)
                if di < 0:
                    di = divi.get(ak, -1)
                cls = cls_of_div.get(di, '')
                tier = tier_of_div.get(di, 3)
            if g[6] >= g[7]:
                w, ws, l, ls = g[4], g[6], g[5], g[7]
            else:
                w, ws, l, ls = g[5], g[7], g[4], g[6]
            row = [cls, tier,
                   w, short_by.get('%d:%s' % (g[0], w), w), ws,
                   l, short_by.get('%d:%s' % (g[0], l), l), ls,
                   g[2], bi]
            bucket = finals[sid][str(g[0])]
            # one final per bracket; a season can run two brackets at the same level
            same = [x for x in bucket if x[9] == bi]
            if same:
                if g[2] >= same[0][8]:
                    bucket[bucket.index(same[0])] = row
            else:
                bucket.append(row)
        for spk in ('0', '1'):
            rows_ = finals[sid][spk]
            by_cls = {}
            for r in rows_:
                by_cls.setdefault(r[0], []).append(r)
            for c_, group in by_cls.items():
                group.sort(key=lambda r: r[8])
                for r in group[:-1]:
                    r.append(1)          # an earlier, separate bracket at the same level
                group[-1].append(0)
            rows_.sort(key=lambda r: (r[1], r[0], r[8]))

        # titles: winners of games flagged Final (round index 5)
        divof = {}
        for t in o['T']:
            divof['%d:%s' % (t[0], t[1])] = D[t[3]] if t[3] >= 0 else ''
        for g in o['G']:
            if g[10] == 1 and g[11] == 5 and g[6] is not None and g[7] is not None:
                win = g[4] if g[6] >= g[7] else g[5]
                k = '%d:%s' % (g[0], win)
                cls = (divof.get('%d:%s' % (g[0], g[4])) or '')[:2]
                titles.setdefault(k, []).append([sid, cls])

    # ---- stable URL slugs, one per school (sport is a separate path segment) ----
    # Built from the abbreviated names so /school/beacon reads well. A school that
    # slugs to the same string as another gets its PSAL code appended, so a link
    # is never ambiguous. Sorted so the winner of a collision is deterministic
    # across builds rather than dependent on dict ordering.
    def slugify(name):
        out, prev_dash = [], False
        for ch in (name or '').lower():
            if ch.isalnum():
                out.append(ch); prev_dash = False
            elif not prev_dash and out:
                out.append('-'); prev_dash = True
        return ''.join(out).strip('-') or 'school'

    best = {}
    for k, e in teams.items():
        code = k.split(':')[1]
        label = e.get('sn') or e.get('n') or code
        # prefer the boys entry's name when both exist, for a consistent slug
        if code not in best or k.startswith('0:'):
            best[code] = label
    taken, slugs = {}, {}
    for code in sorted(best):
        base = slugify(best[code])
        if base in taken:
            slugs[code] = base + '-' + str(code)
        else:
            taken[base] = code
            slugs[code] = base
    # a name that collided must not leave the first claimant on the bare slug if
    # that would be misleading -- only genuine duplicates get suffixed, and the
    # first (lowest code) keeps the clean one, which is stable build to build.

    # the player builder needs exactly these slugs, so they are written out
    # rather than regenerated from a second copy of the rules
    with open(os.path.join(DATA, 'slugs.json'), 'w') as f:
        json.dump(slugs, f, separators=(',', ':'))

    # a few KB the edge function reads to title a school page for link
    # previews, so it never has to parse the whole embedded payload
    by_slug = {}
    for code, sl in slugs.items():
        by_slug[sl] = global_short.get(code, code)
    with open(os.path.join(DATA, 'titles.json'), 'w') as f:
        json.dump({'schools': by_slug, 'codes': global_short},
                  f, separators=(',', ':'))

    hist = {'teams': teams, 'finals': finals, 'titles': titles}
    with open(os.path.join(DATA, 'history.json'), 'w') as f:
        json.dump(hist, f, separators=(',', ':'))

    meta = {
        'updated': updated or datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'path': '/data/',   # absolute: deep routes like /school/beacon must not resolve it relatively
        'defaultSeason': cur,
        'seasons': [{'id': s, 'label': seasons[s]['label'], 'cur': s == cur} for s in sorted(ids, reverse=True)],
        'slugs': slugs,
        'shorts': global_short,
    }
    pmeta_path = os.path.join(DATA, 'pmeta.json')
    if os.path.exists(pmeta_path):
        try:
            meta['pshards'] = json.load(open(pmeta_path)).get('shards')
        except Exception:
            pass
    payload = {'meta': meta, 'season': seasons[cur]}
    blob = json.dumps(payload, separators=(',', ':')).replace('</script>', '<\\/script>')
    tpl = open(TPL).read()
    open(PAGE, 'w').write(tpl.replace('__PSAL_DATA__', blob))
    return {'seasons': len(ids), 'current': cur, 'page_kb': round(os.path.getsize(PAGE)/1024),
            'history_kb': round(os.path.getsize(os.path.join(DATA, 'history.json'))/1024),
            'teams': len(teams), 'slugs': len(slugs),
            'dupe_slugs': sum(1 for c, sl in slugs.items() if sl.endswith('-' + str(c))),
            'titles': sum(len(v) for v in titles.values()),
            'finals': sum(len(v['0']) + len(v['1']) for v in finals.values())}

if __name__ == '__main__':
    print(build(current=sys.argv[1] if len(sys.argv) > 1 else None))
