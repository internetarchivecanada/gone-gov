"""Turn a live-check row into one status.

live     answers 200 at the same address (or a trivial redirect: http->https, www, trailing slash)
moved    redirects to a specific other page (one-to-one); probably still online elsewhere
away     redirects to a homepage, or to a page that many old addresses now land on (catch-all)
gone     404/410, a "page not found" page served with 200, Amazon S3's 403 AccessDenied for a missing file,
         or the host no longer exists / refuses connections
blocked  the site refuses automated requests (Cloudflare / AWS WAF challenge, Akamai "Access Denied", 403, 429)
unclear  other errors: 401/403, 429, 5xx, timeouts, TLS failures
"""
import re, urllib.parse
from collections import Counter
from gg.common import norm, host_of

SOFT404 = re.compile(r'\b(page not found|not found|404|no longer available|page (?:does not|doesn.t) exist|cannot be found|could not be found|error page)\b', re.I)
GONE_CODES = {404, 410}

def base_domain(h):
    parts = h.split('.')
    return '.'.join(parts[-2:])

def is_home(u):
    p = urllib.parse.urlsplit(u)
    return p.path.rstrip('/') in ('', '/index.html', '/index.htm', '/home', '/en', '/es') and not p.query

def catchalls(lives, min_sources=25):
    """Final addresses that at least min_sources distinct old addresses redirect to."""
    c = Counter(norm(r['f']) for r in lives if r.get('f') and norm(r['f']) != norm(r['u']))
    return {k for k, n in c.items() if n >= min_sources}

def status(r, catch):
    st = r.get('st')
    if st == 'blocked' or r.get('cf') or r.get('blk'):
        return 'blocked'
    if st in ('dns', 'refused'):
        return 'gone'
    if isinstance(st, int):
        f = r.get('f')
        redirected = f and norm(f) != norm(r['u'])
        if st in GONE_CODES or (st == 403 and r.get('s3') == 'AccessDenied'):
            return 'gone'
        if st in (200, 203):
            if redirected:
                if norm(f) in catch or (is_home(f) and not is_home(r['u'])):
                    return 'away'
                return 'moved'
            if r.get('t') and SOFT404.search(r['t']) and not SOFT404.search(r.get('t0', '') or ''):
                return 'gone'
            return 'live'
        if redirected and st in (401, 403) and is_home(f):
            return 'away'
    return 'unclear'


# ---- crawler loops: addresses that never existed on the site ----
REPEAT3 = re.compile(r'(/[^/]+)\1{2,}(/|$)')
REPEAT2 = re.compile(r'(/[^/]+)\1(/|$)')


def basename(u):
    return urllib.parse.urlsplit(u).path.rstrip('/').rsplit('/', 1)[-1].lower()


def trap_finder(urls):
    """Return a test for crawler-loop addresses (relative links resolved against the wrong base, again and again):
    a path segment repeated 3+ times in a row, another address glued into the path ('://'), or a segment repeated
    twice where the same file name turns up at 20+ addresses in the collection."""
    common = Counter(basename(u) for u in urls if REPEAT2.search(urllib.parse.urlsplit(u).path))
    many = {b for b, k in common.items() if k >= 20 and '.' in b}

    def is_trap(u):
        path = urllib.parse.urlsplit(u).path
        if REPEAT3.search(path) or '://' in path:
            return True
        return bool(REPEAT2.search(path)) and basename(u) in many
    return is_trap
