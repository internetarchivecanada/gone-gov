"""Check each listed address on the live web today.

python3 -m gg.live [slug ...]      -> data/live/<slug>.jsonl (append-only, resumable)
python3 -m gg.live --retry [slug]   re-check rows that ended in a timeout, 429 or 5xx (slower)

Per-host politeness: 2 requests at a time (4 for hosts with >50,000 addresses). A host whose answers are
Cloudflare challenges is marked blocked after 20 such answers and its remaining addresses are not requested.
A host whose name no longer resolves is marked dns for every address without further requests.
No challenge solving, no browser impersonation: the User-Agent names this project.
"""
import json, os, re, socket, ssl, sys, threading, time, urllib.error, urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from gg.common import COLLECTIONS, DATA, UA, get, jsonl, host_of

TITLE = re.compile(rb'<title[^>]*>(.*?)</title>', re.S | re.I)
lock = threading.Lock()

def title_of(b):
    m = TITLE.search(b)
    if not m:
        return ''
    import html
    return re.sub(r'\s+', ' ', html.unescape(m.group(1).decode('utf-8', 'replace'))).strip()[:300]

def check(u):
    rec = {'u': u, 'at': time.strftime('%Y%m%d%H%M%S', time.gmtime())}
    try:
        r = get(u, timeout=40, headers={'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*;q=0.8'})
        rec['st'] = r.status
        body = b''
        ct = r.headers.get('Content-Type', '')
        if 'html' in ct:
            body = r.read(65536)
            rec['t'] = title_of(body)
        r.close()
        rec['ct'] = ct.split(';')[0][:60]
        if r.geturl() != u:
            rec['f'] = r.geturl()
    except urllib.error.HTTPError as e:
        rec['st'] = e.code
        if e.geturl() != u:
            rec['f'] = e.geturl()
        if e.headers.get('cf-mitigated') == 'challenge':
            rec['cf'] = 1
        try:
            body = e.read(65536)
            if b'challenges.cloudflare.com' in body or b'Just a moment' in body:
                rec['cf'] = 1
            elif e.code in (404, 410):
                rec['t'] = title_of(body)
        except Exception:
            pass
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            rec['st'] = 'dns'
        elif isinstance(reason, ssl.SSLError) or 'CERTIFICATE' in str(reason):
            rec['st'] = 'tls'
        elif isinstance(reason, ConnectionRefusedError):
            rec['st'] = 'refused'
        elif isinstance(reason, (socket.timeout, TimeoutError)) or 'timed out' in str(reason):
            rec['st'] = 'timeout'
        else:
            rec['st'] = 'err'
        rec['e'] = str(reason)[:120]
    except (socket.timeout, TimeoutError):
        rec['st'] = 'timeout'
    except Exception as e:
        rec['st'] = 'err'
        rec['e'] = (type(e).__name__ + ': ' + str(e))[:120]
    return rec

def dns_ok(host):
    for h in (host, 'www.' + host):
        try:
            socket.getaddrinfo(h, 443)
            return True
        except socket.gaierror:
            pass
        except Exception:
            return True
    return False

def run(slug, retry=False):
    os.makedirs(os.path.join(DATA, 'live'), exist_ok=True)
    path = os.path.join(DATA, 'live', slug + '.jsonl')
    last = {}
    for d in jsonl(path):
        last[d['u']] = d
    todo = []
    for d in jsonl(os.path.join(DATA, 'lists', slug + '.jsonl')):
        prev = last.get(d['u'])
        if prev is None:
            todo.append(d['u'])
        elif retry and (prev['st'] in ('timeout', 'err', 'refused', 'tls') or (isinstance(prev['st'], int) and (prev['st'] == 429 or prev['st'] >= 500))):
            todo.append(d['u'])
    byhost = defaultdict(list)
    for u in todo:
        byhost[urllib.parse.urlsplit(u).netloc.lower()].append(u)
    print(slug, len(todo), 'to check on', len(byhost), 'hosts', flush=True)
    out = open(path, 'a')
    stats = defaultdict(int)

    def write(rec):
        with lock:
            out.write(json.dumps(rec) + '\n')
            stats['n'] += 1
            if stats['n'] % 1000 == 0:
                out.flush()
                print(slug, stats['n'], '/', len(todo), time.strftime('%H:%M:%S'), flush=True)

    def host_job(host, urls, step, start, state):
        for u in urls[start::step]:
            if state.get('dns'):
                write({'u': u, 'st': 'dns', 'at': time.strftime('%Y%m%d%H%M%S', time.gmtime()), 'e': 'host does not resolve'}); continue
            if state.get('blocked', 0) >= 20 and not state.get('ok'):
                write({'u': u, 'st': 'blocked', 'cf': 1, 'at': time.strftime('%Y%m%d%H%M%S', time.gmtime())}); continue
            rec = check(u)
            if rec.get('cf'):
                state['blocked'] = state.get('blocked', 0) + 1
            elif rec['st'] not in ('timeout', 'err') and not (rec['st'] == 403):
                state['ok'] = True
            write(rec)
            delay = 1.0 if retry else 0.15
            if rec['st'] == 429:
                delay = 30
            time.sleep(delay)

    jobs = []
    with ThreadPoolExecutor(64) as ex:
        for host, urls in sorted(byhost.items(), key=lambda kv: -len(kv[1])):
            state = {}
            if not dns_ok(host.split(':')[0].removeprefix('www.')):
                state['dns'] = True
            step = 1 if retry else (4 if len(urls) > 50000 else 2)
            for s in range(step):
                jobs.append(ex.submit(host_job, host, urls, step, s, state))
        for j in jobs:
            j.result()
    out.close()
    print(slug, 'done', stats['n'], flush=True)

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    for s in args or [c[0] for c in COLLECTIONS]:
        run(s, retry='--retry' in sys.argv)
