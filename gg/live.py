"""Check each listed address on the live web today.

python3 -m gg.live [slug ...]      -> data/live/<slug>.jsonl (append-only, resumable; the last row per address wins)
python3 -m gg.live --retry [slug]   same, slower (2 s between requests per host)

Asks again about rows that ended blocked, refused, 401/403/429/5xx, timed out or failed TLS, once the last try
is more than six hours old.

Per-host politeness: one request at a time (two for hosts with >50,000 addresses), 0.5 s apart. A host that
refuses automated requests (Cloudflare or AWS WAF challenge, Akamai "Access Denied", bare 403, 429) 15 times in a
row without ever answering is marked blocked and its remaining addresses are not requested. A host that did
answer before is assumed to be rate limiting: pause 15 minutes, give up for this run after 3 pauses.
A host whose name no longer resolves is marked dns for every address without further requests.
Every refusal or limit (and every pause, block decision and give-up) is also written to data/blocks/events.jsonl
with the answering server's identifying headers, for gg.blocks and the site's blocks page.
No challenge solving, no browser impersonation: the User-Agent names this project.
Run with Homebrew Python (/opt/homebrew/bin/python3) on the studio: the system Python's LibreSSL has no TLS 1.3.
"""
import html, json, os, re, socket, ssl, sys, threading, time, urllib.error, urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from gg.common import COLLECTIONS, DATA, get, jsonl

TITLE = re.compile(rb'<title[^>]*>(.*?)</title>', re.S | re.I)
RECHECK_AGE = int(os.environ.get("GG_RECHECK_AGE", 6 * 3600))
lock = threading.Lock()
EVIDENCE_HEADERS = ('Server', 'Retry-After', 'cf-ray', 'cf-mitigated', 'x-amzn-waf-action', 'x-amzn-requestid',
                    'x-akamai-request-id', 'Akamai-GRN', 'x-iinfo', 'x-cdn', 'Via', 'X-Cache')
AKAMAI_REF = re.compile(rb'Reference&#32;#?([0-9a-f.]+)|Reference #([0-9a-f.]+)', re.I)
_events = None


def event(**ev):
    """Append one block/limit event (thread-safe)."""
    global _events
    with lock:
        if _events is None:
            os.makedirs(os.path.join(DATA, 'blocks'), exist_ok=True)
            _events = open(os.path.join(DATA, 'blocks', 'events.jsonl'), 'a')
        ev.setdefault('at', now())
        _events.write(json.dumps(ev) + '\n')
        _events.flush()


def evidence(headers, body=b''):
    ev = {}
    for h in EVIDENCE_HEADERS:
        v = headers.get(h) if headers else None
        if v:
            ev[h.lower()] = v[:120]
    m = AKAMAI_REF.search(body or b'')
    if m:
        ev['akamai-ref'] = (m.group(1) or m.group(2)).decode('ascii', 'replace')
    return ev


def now():
    return time.strftime('%Y%m%d%H%M%S', time.gmtime())


def title_of(b):
    m = TITLE.search(b)
    if not m:
        return ''
    return re.sub(r'\s+', ' ', html.unescape(m.group(1).decode('utf-8', 'replace'))).strip()[:300]


def check(u):
    rec = {'u': u, 'at': now()}
    try:
        r = get(u, timeout=40, headers={'Accept': 'text/html,application/xhtml+xml,application/pdf,*/*;q=0.8'})
        rec['st'] = r.status
        ct = r.headers.get('Content-Type', '')
        rec['ct'] = ct.split(';')[0][:60]
        if r.status == 202 or r.headers.get('x-amzn-waf-action'):
            rec['blk'] = 'aws-waf' if r.headers.get('x-amzn-waf-action') else 'challenge'
            rec['_ev'] = evidence(r.headers)
        elif 'html' in ct:
            rec['t'] = title_of(r.read(65536))
        r.close()
        if r.geturl() != u:
            rec['f'] = r.geturl()
    except urllib.error.HTTPError as e:
        rec['st'] = e.code
        if e.geturl() != u:
            rec['f'] = e.geturl()
        try:
            body = e.read(65536)
        except Exception:
            body = b''
        server = e.headers.get('Server') or ''
        if e.headers.get('cf-mitigated') == 'challenge' or b'challenges.cloudflare.com' in body:
            rec['cf'] = 1
            rec['blk'] = 'cloudflare'
        elif e.headers.get('x-amzn-waf-action'):
            rec['blk'] = 'aws-waf'
        elif e.code == 429:
            rec['blk'] = 'rate'
        elif e.code == 403 and b'<Code>AccessDenied</Code>' in body:
            # Amazon S3 (often behind CloudFront) answers this for a file that is not in the bucket; files that still
            # exist on the same site answer 200, so this is a missing file, not a refusal of our requests
            rec['s3'] = 'AccessDenied'
        elif e.code == 403 and ('AkamaiGHost' in server or b'edgesuite.net' in body or AKAMAI_REF.search(body)):
            rec['blk'] = 'akamai'
        elif e.code == 403 and b'could not be satisfied' in body and 'cloudfront' in (e.headers.get('Via') or '').lower():
            rec['blk'] = 'cloudfront'
        elif e.code == 403 and b'Access Denied' in body:
            rec['blk'] = 'access-denied'
        elif e.code == 403:
            rec['blk'] = 'forbidden'
        elif e.code in (404, 410):
            rec['t'] = title_of(body)
        if rec.get('blk') or e.code in (401, 503) or e.headers.get('Retry-After'):
            rec['_ev'] = evidence(e.headers, body)
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


def dns_ok(host, tries=3, wait=20):
    """True if the host (or www.host) resolves. Tries three times, 20 s apart: right after a studio reboot the
    resolver can fail for a few minutes, which once marked all of www.fema.gov as gone."""
    for attempt in range(tries):
        for h in (host, 'www.' + host):
            try:
                socket.getaddrinfo(h, 443)
                return True
            except socket.gaierror:
                pass
            except Exception:
                return True
        if attempt < tries - 1:
            time.sleep(wait)
    return False


def recheck(prev):
    st = prev.get('st')
    bad = st in ('timeout', 'err', 'refused', 'tls', 'blocked') or prev.get('blk') or prev.get('cf') or \
        (isinstance(st, int) and (st in (202, 401, 403, 429) or st >= 500))
    if not bad:
        return False
    try:
        t = time.mktime(time.strptime(prev.get('at', '19700101000000'), '%Y%m%d%H%M%S')) - time.timezone
    except ValueError:
        return True
    return time.time() - t > RECHECK_AGE


def run(slug, retry=False):
    os.makedirs(os.path.join(DATA, 'live'), exist_ok=True)
    path = os.path.join(DATA, 'live', slug + '.jsonl')
    last = {}
    for d in jsonl(path):
        last[d['u']] = d
    todo = []
    resolves = {}
    for d in jsonl(os.path.join(DATA, 'lists', slug + '.jsonl')):
        prev = last.get(d['u'])
        if prev is None or recheck(prev):
            todo.append(d['u'])
        elif prev.get('st') == 'dns':
            # ask again if the host resolves now (a resolver failure must not stick)
            h = urllib.parse.urlsplit(d['u']).netloc.lower().split(':')[0]
            h = h[4:] if h.startswith('www.') else h
            if h not in resolves:
                resolves[h] = dns_ok(h, tries=1)
            if resolves[h]:
                todo.append(d['u'])
    byhost = defaultdict(list)
    for u in todo:
        byhost[urllib.parse.urlsplit(u).netloc.lower()].append(u)
    print(slug, len(todo), 'to check on', len(byhost), 'hosts', time.strftime('%H:%M:%S'), flush=True)
    out = open(path, 'a')
    count = [0]

    def write(rec):
        with lock:
            out.write(json.dumps(rec) + '\n')
            count[0] += 1
            if count[0] % 1000 == 0:
                out.flush()
                print(slug, count[0], '/', len(todo), time.strftime('%H:%M:%S'), flush=True)

    def host_job(host, urls, step, start, state):
        pauses = 0
        for u in urls[start::step]:
            if state.get('dns'):
                write({'u': u, 'st': 'dns', 'at': now(), 'e': 'host does not resolve'})
                continue
            if state.get('blocked'):
                write({'u': u, 'st': 'blocked', 'blk': state['blocked'], 'at': now()})
                continue
            if state.get('stop'):
                return
            rec = check(u)
            ev = rec.pop('_ev', None)
            write(rec)
            if ev is not None:
                event(type='refused' if rec.get('blk') else 'limited', coll=slug, host=host, u=u, st=rec.get('st'),
                      blk=rec.get('blk'), ev=ev, at=rec['at'])
            elif rec['st'] in ('refused', 'timeout') or (rec['st'] == 'err' and 'reset' in rec.get('e', '').lower()):
                event(type='no-answer', coll=slug, host=host, u=u, st=rec['st'], e=rec.get('e', ''), at=rec['at'])
            if rec.get('blk'):
                state['refused'] = state.get('refused', 0) + 1
                if state['refused'] >= 15:
                    # 15 refusals in a row: ask for the homepage before deciding. If it answers, these were pages
                    # that are closed to everyone (e.g. comment-reply forms), not a refusal of our checks.
                    # Only plain 403s qualify: challenge pages, CDN "request blocked" pages and 429s are aimed at
                    # automated clients, and a cached homepage answering proves nothing about them.
                    root = urllib.parse.urlsplit(u)._replace(path='/', query='', fragment='').geturl()
                    probe = check(root) if rec['blk'] in ('forbidden', 'access-denied') else {'st': None, 'blk': rec['blk']}
                    pev = probe.pop('_ev', None)
                    if not probe.get('blk') and isinstance(probe.get('st'), int) and probe['st'] < 400:
                        event(type='per-page', coll=slug, host=host, blk=rec['blk'], u=root, st=probe['st'],
                              note='15 addresses in a row refused, but the homepage answers: treated as pages closed to everyone, checks continue')
                        state['ok'] = True
                        state['refused'] = 0
                        time.sleep(2.0 if retry else 0.5)
                        continue
                    if probe.get('st') is not None:
                        event(type='homepage-refused', coll=slug, host=host, u=root, st=probe.get('st'),
                              blk=probe.get('blk'), ev=pev or {})
                    if not state.get('ok'):
                        state['blocked'] = rec['blk']
                        print(slug, host, 'blocked:', rec['blk'], flush=True)
                        event(type='marked-blocked', coll=slug, host=host, blk=rec['blk'],
                              note='refused 15 requests in a row and never answered; its remaining addresses are not requested this run')
                    else:
                        pauses += 1
                        if pauses > 3:
                            state['stop'] = True
                            print(slug, host, 'still refusing after 3 pauses; left for a later run', flush=True)
                            event(type='gave-up', coll=slug, host=host, blk=rec['blk'],
                                  note='still refusing after three 15-minute pauses; left for a later run')
                            return
                        print(slug, host, 'refusing (%s); pausing 15 min' % rec['blk'], flush=True)
                        event(type='paused', coll=slug, host=host, blk=rec['blk'],
                              note='answered earlier, then refused 15 in a row: treated as rate limiting, pausing 15 minutes')
                        time.sleep(900)
                        state['refused'] = 0
            elif rec['st'] not in ('timeout', 'err'):
                state['ok'] = True
                state['refused'] = 0
            time.sleep(2.0 if retry else 0.5)

    jobs = []
    with ThreadPoolExecutor(48) as ex:
        for host, urls in sorted(byhost.items(), key=lambda kv: -len(kv[1])):
            state = {}
            h = host.split(':')[0]
            if not dns_ok(h[4:] if h.startswith('www.') else h):
                state['dns'] = True
            step = 1 if retry else (2 if len(urls) > 50000 else 1)
            for s in range(step):
                jobs.append(ex.submit(host_job, host, urls, step, s, state))
        for j in jobs:
            j.result()
    out.close()
    print(slug, 'done', count[0], time.strftime('%H:%M:%S'), flush=True)


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    for s in args or [c[0] for c in COLLECTIONS]:
        run(s, retry='--retry' in sys.argv)
