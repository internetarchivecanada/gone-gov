"""YouTube videos embedded on the archived pages: are they still on YouTube?

python3 -m gg.videos [slug ...]  -> data/videos/<slug>.checked.jsonl (resumable)
- live: YouTube's public oEmbed endpoint (200 = playable and embeddable; 401 = private or embedding off; 404 = gone),
  then the watch page's own reason text for anything not 200 ("This video is private", "removed by the uploader"...).
- title: from oEmbed when live; otherwise from the archived embed page inside the Webrecorder WACZ (range read).
- Wayback: latest status-200 capture of youtube.com/watch?v=<id>.
"""
import html, json, os, re, sys, time, urllib.error, urllib.parse, zlib
from concurrent.futures import ThreadPoolExecutor
from gg.common import COLLECTIONS, DATA, get, jsonl, coll_meta, zip_entries, data_start, rng

REASONS = [
    ('private', re.compile(r'This video is private|"status":"LOGIN_REQUIRED"[^}]*private', re.I)),
    ('removed by uploader', re.compile(r'removed by the uploader', re.I)),
    ('account terminated', re.compile(r'account associated with this video has been terminated|channel was removed|account has been terminated', re.I)),
    ('copyright', re.compile(r'copyright claim', re.I)),
    ('unavailable', re.compile(r'Video unavailable|"status":"ERROR"', re.I)),
]

def oembed(vid):
    u = 'https://www.youtube.com/oembed?format=json&url=' + urllib.parse.quote('https://www.youtube.com/watch?v=' + vid)
    try:
        with get(u, timeout=30) as r:
            d = json.load(r)
            return 200, d
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        return 'err', None

def reason(vid):
    try:
        with get('https://www.youtube.com/watch?v=' + vid + '&hl=en', timeout=30, headers={'Accept-Language': 'en'}) as r:
            b = r.read(800000).decode('utf-8', 'replace')
    except Exception:
        return ''
    m = re.search(r'"playabilityStatus":\{"status":"(\w+)"(?:,"reason":"([^"]*)")?', b)
    text = (m.group(2) or m.group(1)) if m else ''
    for name, rx in REASONS:
        if rx.search(b[:400000]):
            return name + (' - ' + text if text and text.lower() not in name else '')
    return text

def wayback(vid):
    q = 'https://web.archive.org/cdx/search/cdx?' + urllib.parse.urlencode({'url': 'youtube.com/watch?v=' + vid, 'output': 'json', 'fl': 'timestamp', 'filter': 'statuscode:200', 'limit': '-1', 'fastLatest': 'true'})
    for a in range(4):
        try:
            with get(q, timeout=60) as r:
                rows = json.load(r)
            return rows[-1][0] if len(rows) > 1 else ''
        except Exception:
            time.sleep(5 * (a + 1))
    return None

_ents = {}
def archived_title(meta, v):
    """Read the embed page's WARC record from the WACZ and take its <title>."""
    try:
        res = next(r for r in meta['resources'] if r['name'] == v['w'])
        if v['w'] not in _ents:
            _ents[v['w']] = {e['name']: e for e in zip_entries(res['path'], res['size'])}
        ent = _ents[v['w']].get('archive/' + v['f'])
        if not ent or ent['meth'] != 0:
            return ''
        s = data_start(res['path'], ent) + int(v['o'])
        raw = rng(res['path'], s, s + int(v['l']) - 1)
        body = zlib.decompressobj(31).decompress(raw)
        m = re.search(rb'<title>(.*?)</title>', body, re.S)
        t = html.unescape(m.group(1).decode('utf-8', 'replace')).strip() if m else ''
        return re.sub(r'\s*-\s*YouTube$', '', t)
    except Exception:
        return ''

def wayback_title(vid, ts):
    try:
        with get('https://web.archive.org/web/%sid_/https://www.youtube.com/watch?v=%s' % (ts, vid), timeout=60) as r:
            b = r.read(600000).decode('utf-8', 'replace')
    except Exception:
        return '', ''
    m = re.search(r'<meta name="title" content="([^"]*)"', b) or re.search(r'<meta property="og:title" content="([^"]*)"', b) or re.search(r'<title>(.*?)</title>', b, re.S)
    t = html.unescape(m.group(1)).strip() if m else ''
    t = re.sub(r'\s*-\s*YouTube$', '', t)
    a = re.search(r'"ownerChannelName":"([^"]*)"', b) or re.search(r'<link itemprop="name" content="([^"]*)"', b)
    return ('' if t == 'YouTube' else t), (html.unescape(a.group(1)) if a else '')

def run(slug):
    path = os.path.join(DATA, 'videos', slug + '.checked.jsonl')
    done = {d['id'] for d in jsonl(path)}
    vids = [v for v in jsonl(os.path.join(DATA, 'videos', slug + '.jsonl')) if v['id'] not in done and v['id'] not in ('videoseries', 'live_stream')]
    print(slug, len(vids), 'videos to check', flush=True)
    out = open(path, 'a')

    def one(v):
        code, d = oembed(v['id'])
        rec = {'id': v['id'], 'ts': v['ts'], 'yt': code, 'at': time.strftime('%Y%m%d%H%M%S', time.gmtime())}
        if d:
            rec['t'] = d.get('title', '')[:300]
            rec['by'] = d.get('author_name', '')[:120]
        else:
            rec['why'] = reason(v['id'])[:200]
        rec['wb'] = wayback(v['id'])
        if not d and rec['wb']:
            t, by = wayback_title(v['id'], rec['wb'])
            rec['t'], rec['by'] = t[:300], by[:120]
        time.sleep(0.5)
        return rec

    with ThreadPoolExecutor(3) as ex:
        for rec in ex.map(one, vids):
            out.write(json.dumps(rec) + '\n'); out.flush()
    out.close()
    print(slug, 'videos done', flush=True)

if __name__ == '__main__':
    for s in sys.argv[1:] or [c[0] for c in COLLECTIONS]:
        run(s)
