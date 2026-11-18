"""Shared settings and helpers. Runs on the studio's Python 3.9 (stdlib only)."""
import json, os, re, struct, urllib.parse, urllib.request, zlib

DATA = os.environ.get('GG_DATA', os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'))
API = 'https://app.browsertrix.com/api/public/orgs/usgov-archive/collections/'
UA = 'Mozilla/5.0 (compatible; WaybackLabs-GoneGov/1.0; +https://wayback-labs.sf.archive.org/gone-gov/about.html)'

# slug on Browsertrix, short name, govarchive.us mirror subdomain
COLLECTIONS = [
    ('epa', 'EPA', 'epa'),
    ('cdc', 'CDC', 'cdc'),
    ('department-of-education', 'Department of Education', 'ed'),
    ('fema', 'FEMA', 'fema'),
    ('usaid', 'USAID', 'usaid'),
    ('global-change-research-program', 'Global Change Research Program', 'globalchange'),
    ('climate-gov-dashboard', 'Climate.gov + Dashboard', 'climate'),
    ('imls', 'IMLS', 'imls'),
    ('sea-level-change', 'Sea Level Change', 'sealevel-globalchange'),
    ('covid-gov', 'COVID.gov', 'covid'),
]

PAGE_EXT = {'', 'html', 'htm', 'shtml', 'shtm', 'xhtml', 'php', 'asp', 'aspx', 'cfm', 'jsp', 'do', 'action'}
DOC_EXT = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'ppt', 'pptx', 'rtf', 'odt', 'ods', 'epub'}
DOC_MIME = ('application/pdf', 'application/msword', 'application/vnd.openxmlformats', 'application/vnd.ms-excel',
            'application/vnd.ms-powerpoint', 'text/csv', 'application/rtf', 'application/epub')
ASSET_EXT = {'jpg', 'jpeg', 'png', 'gif', 'svg', 'webp', 'ico', 'bmp', 'tif', 'tiff', 'js', 'css', 'json', 'xml',
             'woff', 'woff2', 'ttf', 'eot', 'otf', 'mp4', 'mp3', 'm4a', 'm4v', 'mov', 'wav', 'avi', 'wmv', 'webm',
             'zip', 'gz', 'tgz', 'tar', 'exe', 'dmg', 'kml', 'kmz', 'map', 'rss', 'atom', 'txt', 'swf', 'ics', 'vcf'}

def ext_of(url):
    path = urllib.parse.urlsplit(url).path
    last = path.rsplit('/', 1)[-1]
    if '.' not in last:
        return ''
    e = last.rsplit('.', 1)[-1].lower()
    return e if re.fullmatch(r'[a-z0-9]{1,6}', e) else ''

def kind_of(url):
    """'page', 'doc' or None (image, script, data file...)."""
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ('http', 'https'):
        return None
    e = ext_of(url)
    if e in DOC_EXT:
        return 'doc'
    if e in ASSET_EXT:
        return None
    return 'page'

def host_of(url):
    h = urllib.parse.urlsplit(url).netloc.lower().split('@')[-1].split(':')[0]
    return h[4:] if h.startswith('www.') else h

def norm(url):
    """Key that folds scheme, www., trailing slash and #fragment."""
    p = urllib.parse.urlsplit(url.strip())
    path = p.path.rstrip('/') or '/'
    return host_of(url) + path + ('?' + p.query if p.query else '')

def get(url, timeout=60, headers=None):
    h = {'User-Agent': UA}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)

def coll_meta(slug):
    with get(API + slug) as r:
        return json.load(r)

# ---- reading files inside a remote WACZ (zip) with HTTP range requests ----
def rng(url, start, end):
    for attempt in range(5):
        try:
            with get(url, timeout=300, headers={'Range': 'bytes=%d-%d' % (start, end)}) as r:
                return r.read()
        except Exception:
            if attempt == 4:
                raise

def zip_entries(url, size):
    base = max(0, size - 65536)
    tail = rng(url, base, size - 1)
    i = tail.rfind(b'PK\x05\x06')
    cd_size, cd_off = struct.unpack('<II', tail[i + 12:i + 20])
    j = tail.rfind(b'PK\x06\x06')
    if j >= 0:
        cd_size, cd_off = struct.unpack('<QQ', tail[j + 40:j + 56])
    cd = rng(url, cd_off, cd_off + cd_size - 1)
    p = 0
    while cd[p:p + 4] == b'PK\x01\x02':
        meth, = struct.unpack('<H', cd[p + 10:p + 12])
        csz, usz = struct.unpack('<II', cd[p + 20:p + 28])
        nl, el, cl = struct.unpack('<HHH', cd[p + 28:p + 34])
        off, = struct.unpack('<I', cd[p + 42:p + 46])
        name = cd[p + 46:p + 46 + nl].decode()
        extra = cd[p + 46 + nl:p + 46 + nl + el]
        q = 0
        while q < len(extra):
            hid, hl = struct.unpack('<HH', extra[q:q + 4])
            if hid == 1:
                vals = list(struct.unpack('<' + 'Q' * (hl // 8), extra[q + 4:q + 4 + hl]))
                k = 0
                if usz == 0xffffffff: usz = vals[k]; k += 1
                if csz == 0xffffffff: csz = vals[k]; k += 1
                if off == 0xffffffff: off = vals[k]; k += 1
            q += 4 + hl
        yield {'name': name, 'meth': meth, 'csz': csz, 'off': off}
        p += 46 + nl + el + cl

def data_start(url, ent):
    h = rng(url, ent['off'], ent['off'] + 29)
    nl, el = struct.unpack('<HH', h[26:30])
    return ent['off'] + 30 + nl + el

def read_entry(url, ent):
    s = data_start(url, ent)
    data = rng(url, s, s + ent['csz'] - 1)
    return zlib.decompress(data, -15) if ent['meth'] == 8 else data

def gunzip_multi(b):
    out = []
    while b:
        d = zlib.decompressobj(31)
        out.append(d.decompress(b))
        b = d.unused_data
    return b''.join(out)

def jsonl(path):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass
