"""Pull page/document lists and embedded YouTube videos out of each collection's WACZ files.

python3 -m gg.lists [slug ...]   -> data/lists/<slug>.jsonl, data/videos/<slug>.jsonl, data/meta/<slug>.json
Reads pages/*.jsonl and indexes/*.cdx(.gz) only, by HTTP range requests (no full download). Resumable per WACZ.
"""
import json, os, re, sys, time
from gg.common import COLLECTIONS, DATA, coll_meta, zip_entries, read_entry, gunzip_multi, kind_of, norm, host_of, DOC_MIME, jsonl

YT = re.compile(r'(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?(?:.*&)?v=|v/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})')

def run(slug):
    meta = coll_meta(slug)
    for d in ('lists', 'videos', 'meta', 'lists/done'):
        os.makedirs(os.path.join(DATA, d), exist_ok=True)
    m = {k: meta.get(k) for k in ('name', 'slug', 'caption', 'pageCount', 'uniquePageCount', 'totalSize', 'dateEarliest', 'dateLatest', 'homeUrl')}
    m['wacz'] = [r['name'] for r in meta['resources']]
    json.dump(m, open(os.path.join(DATA, 'meta', slug + '.json'), 'w'), indent=1)
    donefile = os.path.join(DATA, 'lists/done', slug + '.txt')
    done = set(open(donefile).read().split()) if os.path.exists(donefile) else set()
    out = open(os.path.join(DATA, 'lists', slug + '.raw.jsonl'), 'a')
    vout = open(os.path.join(DATA, 'videos', slug + '.raw.jsonl'), 'a')
    for i, res in enumerate(meta['resources']):
        if res['name'] in done:
            continue
        t0 = time.time(); n = nv = 0
        ents = list(zip_entries(res['path'], res['size']))
        for e in ents:
            if e['name'].startswith('pages/') and e['name'].endswith('.jsonl'):
                for line in read_entry(res['path'], e).decode('utf-8', 'replace').splitlines():
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    u = d.get('url')
                    if not u or not kind_of(u):
                        continue
                    out.write(json.dumps({'u': u, 'ts': d.get('ts'), 't': (d.get('title') or '')[:300],
                                          's': d.get('status'), 'src': 'pages', 'w': res['name']}) + '\n'); n += 1
            elif e['name'].startswith('indexes/') and (e['name'].endswith('.cdx.gz') or e['name'].endswith('.cdxj') or e['name'].endswith('.cdx')):
                raw = read_entry(res['path'], e)
                txt = gunzip_multi(raw) if e['name'].endswith('.gz') else raw
                for line in txt.decode('utf-8', 'replace').splitlines():
                    parts = line.split(' ', 2)
                    if len(parts) < 3:
                        continue
                    key, ts, js = parts
                    if 'youtu' in key:
                        try:
                            d = json.loads(js)
                        except ValueError:
                            continue
                        mt = YT.search(d.get('url', ''))
                        if mt:
                            vout.write(json.dumps({'id': mt.group(1), 'ts': ts, 'url': d['url'], 'st': d.get('status'),
                                                   'w': res['name'], 'f': d.get('filename'), 'o': d.get('offset'), 'l': d.get('length')}) + '\n'); nv += 1
                        continue
                    if 'application/' not in js and 'text/csv' not in js:
                        continue
                    try:
                        d = json.loads(js)
                    except ValueError:
                        continue
                    if str(d.get('status')) != '200' or not (d.get('mime') or '').startswith(DOC_MIME):
                        continue
                    u = d.get('url', '')
                    if '__wb_method' in u or not u.startswith('http'):
                        continue
                    out.write(json.dumps({'u': u, 'ts': ts, 't': '', 's': 200, 'src': 'cdx', 'm': d['mime'], 'w': res['name']}) + '\n'); n += 1
        out.flush(); vout.flush()
        with open(donefile, 'a') as f:
            f.write(res['name'] + '\n')
        print('%s %d/%d %s %d urls %d yt %.0fs' % (slug, i + 1, len(meta['resources']), res['name'], n, nv, time.time() - t0), flush=True)
    out.close(); vout.close()
    merge(slug)

def merge(slug):
    """Dedupe raw rows into lists/<slug>.jsonl: one row per normalised address, earliest capture."""
    own = set()
    rows = {}
    for d in jsonl(os.path.join(DATA, 'lists', slug + '.raw.jsonl')):
        if d['src'] == 'pages':
            own.add(host_of(d['u']))
    for d in jsonl(os.path.join(DATA, 'lists', slug + '.raw.jsonl')):
        u = d['u']; h = host_of(u)
        k = norm(u)
        kind = 'doc' if d.get('m') else kind_of(u)
        if d['src'] == 'cdx' and not (h in own or h.endswith('.gov') or h.endswith('.mil') or h.endswith('.fed.us')):
            continue
        ts = str(d.get('ts') or '')
        ts = re.sub(r'\D', '', ts)[:14]
        r = rows.get(k)
        st = d.get('s')
        st = int(st) if str(st).isdigit() else None
        if r is None:
            rows[k] = {'u': u, 'k': kind, 'ts': ts, 't': d.get('t') or '', 'h': h, 'as': st}
        else:
            if st and (r.get('as') is None or not (200 <= r['as'] < 400)) and (r.get('as') is None or 200 <= st < 400):
                r['as'] = st          # the archive's best status for this address: any working capture wins
            if d.get('t') and not r['t']:
                r['t'] = d['t']
            if ts and ts < r['ts']:
                r['ts'] = ts
            if kind == 'doc':
                r['k'] = 'doc'
    with open(os.path.join(DATA, 'lists', slug + '.jsonl'), 'w') as f:
        for r in rows.values():
            f.write(json.dumps(r) + '\n')
    vids = {}
    for d in jsonl(os.path.join(DATA, 'videos', slug + '.raw.jsonl')):
        v = vids.get(d['id'])
        if v is None or (str(d.get('st')) == '200' and str(v.get('st')) != '200'):
            vids[d['id']] = d
    with open(os.path.join(DATA, 'videos', slug + '.jsonl'), 'w') as f:
        for v in vids.values():
            f.write(json.dumps(v) + '\n')
    print(slug, 'merged', len(rows), 'addresses', sum(1 for r in rows.values() if r['k'] == 'doc'), 'docs', len(vids), 'videos', flush=True)

if __name__ == '__main__':
    slugs = sys.argv[1:] or [c[0] for c in COLLECTIONS]
    for s in slugs:
        if s == '--merge':
            continue
        if '--merge' in sys.argv:
            merge(s)
        else:
            run(s)
