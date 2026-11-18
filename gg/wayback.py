"""Wayback Machine evidence for addresses that are gone or redirected away.

python3 -m gg.wayback [slug ...]   -> data/wayback/<slug>.jsonl (resumable)
Per address: latest capture with status 200 (lt), and the first capture after it that is not 200 (ft, fs) -
together they date the removal. Uses the public CDX API, 4 requests at a time, backs off on 429.
"""
import json, os, sys, threading, time, urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from gg.common import COLLECTIONS, DATA, get, jsonl, norm
from gg.classify import catchalls, status

CDX = 'https://web.archive.org/cdx/search/cdx?'
lock = threading.Lock()

def cdx(params):
    q = CDX + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            with get(q, timeout=120) as r:
                rows = json.load(r) if r.status == 200 else []
            return rows[1:] if rows else []
        except Exception as e:
            code = getattr(e, 'code', None)
            if code == 429:
                time.sleep(60 * (attempt + 1))
            elif code in (400, 403):
                return None
            else:
                time.sleep(5 * (attempt + 1))
    return None

def look(u):
    rec = {'u': u}
    last = cdx({'url': u, 'output': 'json', 'fl': 'timestamp,original,mimetype', 'filter': 'statuscode:200', 'limit': '-1', 'fastLatest': 'true'})
    if last is None:
        rec['err'] = 1
        return rec
    if last:
        rec['lt'] = last[-1][0]
        rec['lo'] = last[-1][1]
        after = cdx({'url': u, 'output': 'json', 'fl': 'timestamp,statuscode', 'from': str(int(rec['lt']) + 1), 'filter': '!statuscode:200', 'limit': '1'})
        if after:
            rec['ft'], rec['fs'] = after[0][0], after[0][1]
    else:
        any_ = cdx({'url': u, 'output': 'json', 'fl': 'timestamp,statuscode', 'limit': '-1', 'fastLatest': 'true'})
        if any_:
            rec['xt'], rec['xs'] = any_[-1][0], any_[-1][1]
    return rec

def key(u):
    return norm(u).lower()

def prefix_host(host, urls, write):
    """Stream every capture under one host (paged CDX) and answer all its addresses at once."""
    want = {key(u): u for u in urls}
    pages = cdx_raw({'url': host + '/', 'matchType': 'prefix', 'showNumPages': 'true'})
    try:
        pages = int(pages.strip())
    except Exception:
        return set()
    caps = defaultdict(list)
    cache = os.path.join(DATA, 'wayback', 'prefix', host)
    os.makedirs(cache, exist_ok=True)
    for pg in range(pages):
        cf = os.path.join(cache, '%05d.txt' % pg)
        if os.path.exists(cf):
            lines = open(cf).read().splitlines()
        else:
            txt = cdx_raw({'url': host + '/', 'matchType': 'prefix', 'fl': 'original,timestamp,statuscode', 'page': str(pg)})
            if txt is None:
                print(host, 'page', pg, 'failed; will retry on the next run', flush=True)
                return set()
            lines = [l for l in txt.splitlines() if len(l.split(' ')) == 3 and key(l.split(' ')[0]) in want]
            with open(cf + '.tmp', 'w') as f:
                f.write('\n'.join(lines))
            os.replace(cf + '.tmp', cf)   # only kept captures matching our addresses; a reboot resumes here
        for line in lines:
            parts = line.split(' ')
            if len(parts) != 3:
                continue
            k = key(parts[0])
            if k in want:
                caps[k].append((parts[1], parts[2], parts[0]))
        if pg % 100 == 0:
            print(host, 'page', pg, '/', pages, len(caps), 'matched', flush=True)
    for k, u in want.items():
        rec = {'u': u, 'via': 'prefix'}
        cs = sorted(caps.get(k, []))
        ok = [c for c in cs if c[1] == '200']
        if ok:
            rec['lt'], rec['lo'] = ok[-1][0], ok[-1][2]
            after = [c for c in cs if c[0] > rec['lt'] and c[1] != '200']
            if after:
                rec['ft'], rec['fs'] = after[0][0], after[0][1]
        elif cs:
            rec['xt'], rec['xs'] = cs[-1][0], cs[-1][1]
        write(rec)
    return set(want.values())

def cdx_raw(params):
    q = CDX + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            with get(q, timeout=300) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            time.sleep(60 if getattr(e, 'code', None) == 429 else 5 * (attempt + 1))
    return None

def targets(slug):
    lives = list(jsonl(os.path.join(DATA, 'live', slug + '.jsonl')))
    latest = {}
    for r in lives:
        latest[r['u']] = r
    catch = catchalls(latest.values())
    return [u for u, r in latest.items() if status(r, catch) in ('gone', 'away')]

def run(slug, threads=6):
    os.makedirs(os.path.join(DATA, 'wayback'), exist_ok=True)
    path = os.path.join(DATA, 'wayback', slug + '.jsonl')
    done = {d['u'] for d in jsonl(path) if not d.get('err')}
    todo = [u for u in targets(slug) if u not in done]
    print(slug, len(todo), 'to look up', flush=True)
    out = open(path, 'a')
    n = [0]

    def one(u):
        rec = look(u)
        with lock:
            out.write(json.dumps(rec) + '\n')
            n[0] += 1
            if n[0] % 500 == 0:
                out.flush()
                print(slug, n[0], '/', len(todo), time.strftime('%H:%M:%S'), flush=True)

    def write(rec):
        with lock:
            out.write(json.dumps(rec) + '\n')
    byhost = defaultdict(list)
    for u in todo:
        byhost[urllib.parse.urlsplit(u).netloc.lower().split(':')[0]].append(u)
    handled = set()
    for host, urls in byhost.items():
        if len(urls) >= 2000:
            np = cdx_raw({'url': host + '/', 'matchType': 'prefix', 'showNumPages': 'true'})
            try:
                np = int(np.strip())
            except Exception:
                continue
            if np * 10 < len(urls):
                print(slug, host, len(urls), 'addresses via', np, 'prefix pages', flush=True)
                handled |= prefix_host(host, urls, write)
                out.flush()
    todo = [u for u in todo if u not in handled]
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(one, todo))
    out.close()
    print(slug, 'done', n[0], flush=True)

if __name__ == '__main__':
    for s in sys.argv[1:] or [c[0] for c in COLLECTIONS]:
        run(s)
