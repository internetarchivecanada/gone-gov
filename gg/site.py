"""Build the static site from data/ into a public folder.

    python3 -m gg.site [OUT]      (default OUT: ./public)
Reads lists/, live/, wayback/, videos/ and meta/ under GG_DATA. Safe to run while checks are still going.
"""
import html, json, os, re, shutil, sys, time, urllib.parse
from collections import Counter, defaultdict
from gg.common import COLLECTIONS, DATA, jsonl, norm, host_of
from gg.classify import catchalls, status

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = 'https://wayback-labs.sf.archive.org/gone-gov/'
V = '8'
STATUS_LABEL = {'gone': 'Gone', 'away': 'Redirected away', 'moved': 'Moved', 'live': 'Still online',
                'blocked': "Can't be checked", 'unclear': 'Unclear', 'pending': 'Not yet checked'}

def esc(s):
    return html.escape(str(s if s is not None else ''), quote=True)

def n(x):
    return '{:,}'.format(x)

def pct(a, b):
    return '%d%%' % round(100.0 * a / b) if b else '–'

def day(ts):
    if not ts or len(ts) < 8:
        return ''
    return time.strftime('%-d %b %Y', time.strptime(ts[:8], '%Y%m%d'))

def code_of(r, cls):
    st = r.get('st')
    if cls == 'gone':
        if st in ('dns',):
            return 'dns'
        if st == 'refused':
            return 'refused'
        if isinstance(st, int) and 200 <= st < 300:
            return 'soft'
        return str(st)
    if cls == 'away':
        return 'away'
    return str(st)

def page(title, body, rel='', active='', desc=''):
    nav = ''.join('<a href="%s%s"%s>%s</a>' % (rel, h, ' aria-current="page"' if a == active else '', t)
                  for h, t, a in [('index.html', 'Overview', 'home'), ('videos.html', 'Videos', 'videos'), ('about.html', 'About', 'about')])
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<meta name="description" content="%s">
<link rel="icon" href="%sfavicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="%sstyle.css?v=%s">
</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="top"><div class="wrap">
<a class="brand" href="%sindex.html"><svg viewBox="0 0 32 32" aria-hidden="true"><use href="%sfavicon.svg#g"/></svg><span>Gone from <em>.gov</em></span></a>
<nav aria-label="Main">%s</nav>
</div></header>
<main id="main" class="wrap">%s</main>
<footer class="wrap"><a class="ia" href="https://archive.org/"><img src="%sinternet-archive.png" alt="Internet Archive" width="40" height="40"></a>
<div><p>A <a href="https://wayback-labs.sf.archive.org/">Wayback Machine Labs</a> experiment, <a href="https://archive.org/">Internet Archive</a>.
Feedback? <a href="mailto:info@archive.org?subject=Gone%%20from%%20.gov">Email us</a>.</p>
<p>Archived copies: the <a href="https://web.archive.org/">Wayback Machine</a>.
Made by Claude (Anthropic) at the direction of Mark Graham. <a href="%sabout.html">About this site</a> · <a href="%sabout.html#accessibility">Accessibility</a></p></div></footer>
</body></html>''' % (esc(title), esc(desc), rel, rel, V, rel, rel, nav, body, rel, rel, rel)

def load(slug):
    rows = list(jsonl(os.path.join(DATA, 'lists', slug + '.jsonl')))
    live = {}
    for r in jsonl(os.path.join(DATA, 'live', slug + '.jsonl')):
        live[r['u']] = r
    wb = {}
    for r in jsonl(os.path.join(DATA, 'wayback', slug + '.jsonl')):
        if not r.get('err') or r['u'] not in wb:
            wb[r['u']] = r
    vids = {}
    for r in jsonl(os.path.join(DATA, 'videos', slug + '.checked.jsonl')):
        vids[r['id']] = r
    nv = sum(1 for v in jsonl(os.path.join(DATA, 'videos', slug + '.jsonl')) if v['id'] not in ('videoseries', 'live_stream'))
    meta = {}
    mp = os.path.join(DATA, 'meta', slug + '.json')
    if os.path.exists(mp):
        meta = json.load(open(mp))
    return rows, live, wb, vids, nv, meta

def month_of(w):
    t = w.get('ft') or ''
    return t[:6] if t else ''

def chart(months, title_id):
    """Single-series column chart of removals per month (first missing capture in the Wayback Machine)."""
    if not months:
        return ''
    keys = sorted(months)
    start, end = keys[0], keys[-1]
    allm = []
    y, m = int(start[:4]), int(start[4:])
    while '%04d%02d' % (y, m) <= end:
        allm.append('%04d%02d' % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    W, H, L, B, T = 760, 240, 52, 34, 12
    mx = max(months.values())
    step = 10 ** max(0, len(str(mx)) - 1)
    top = ((mx + step - 1) // step) * step
    bw = (W - L - 8) / float(len(allm))
    g = []
    for i in range(5):
        v = top * i // 4
        yy = T + (H - T - B) * (1 - v / float(top))
        g.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" class="grid"/><text x="%d" y="%.1f" class="ax" text-anchor="end">%s</text>' % (L, W - 4, yy, yy, L - 6, yy + 4, n(v)))
    bars = []
    for i, k in enumerate(allm):
        v = months.get(k, 0)
        x = L + i * bw + 1
        h = (H - T - B) * v / float(top)
        label = time.strftime('%B %Y', time.strptime(k, '%Y%m'))
        bars.append('<g class="b" tabindex="0"><rect class="hit" x="%.1f" y="%d" width="%.1f" height="%d"/><path class="bar" d="M%.1f,%.1f h%.1f v%.1f h-%.1f z"/><title>%s: %s addresses first seen missing</title></g>' % (
            x, T, max(bw - 1, 1), H - T - B, x, H - B - h, max(bw - 2, 1), h, max(bw - 2, 1), label, n(v)))
        if k.endswith('01') or i == 0:
            bars.append('<text x="%.1f" y="%d" class="ax">%s</text>' % (x, H - B + 16, k[:4]))
    table = ''.join('<tr><td>%s</td><td class="num">%s</td></tr>' % (time.strftime('%b %Y', time.strptime(k, '%Y%m')), n(months[k])) for k in keys)
    return '''<figure class="chart"><svg viewBox="0 0 %d %d" role="img" aria-labelledby="%s">%s%s</svg>
<details><summary>Table view</summary><table class="mini"><thead><tr><th>Month</th><th class="num">Addresses</th></tr></thead><tbody>%s</tbody></table></details></figure>''' % (W, H, title_id, ''.join(g), ''.join(bars), table)

def build(out):
    os.makedirs(os.path.join(out, 'c'), exist_ok=True)
    os.makedirs(os.path.join(out, 'data'), exist_ok=True)
    for f in ('style.css', 'app.js', 'favicon.svg', 'internet-archive.png'):
        shutil.copy(os.path.join(HERE, 'assets', f), os.path.join(out, f))
    summary = []
    allmonths = Counter()
    deadhosts = []
    catchlist = []
    sections = []
    videos_all = []
    total = Counter()
    for slug, short, sub in COLLECTIONS:
        rows, live, wb, vids, nv, meta = load(slug)
        if not rows:
            continue
        catch = catchalls(live.values())
        c = Counter(); ck = Counter(); hosts = []; hidx = {}; out_rows = []
        hstat = defaultdict(Counter); sec = defaultdict(Counter); months = Counter(); finals = Counter()
        for r in rows:
            lv = live.get(r['u'])
            cls = status(lv, catch) if lv else 'pending'
            c[cls] += 1
            ck[(r['k'], cls)] += 1
            h = urllib.parse.urlsplit(r['u']).netloc.lower()
            hstat[h][cls] += 1
            hstat[h]['dns'] += 1 if lv and lv.get('st') == 'dns' else 0
            if cls not in ('gone', 'away'):
                continue
            w = wb.get(r['u'], {})
            if w.get('lt'):
                c['wb'] += 1
            elif r['u'] in wb and not w.get('err'):
                c['nowb'] += 1
            mo = month_of(w)
            if mo:
                months[mo] += 1
            if cls == 'away' and lv.get('f'):
                finals[lv['f']] += 1
            p = urllib.parse.urlsplit(r['u'])
            seg = p.path.strip('/').split('/')[0] if p.path.strip('/') else ''
            sec[(h, seg)][cls] += 1
            if h not in hidx:
                hidx[h] = len(hosts); hosts.append(h)
            path = p.path + ('?' + p.query if p.query else '')
            out_rows.append([hidx[h], path, r.get('t') or '', 1 if r['k'] == 'doc' else 0, 0 if cls == 'gone' else 1,
                             code_of(lv, cls), lv.get('f', '') if cls == 'away' else '', w.get('lt', ''), w.get('ft', ''), w.get('fs', ''),
                             (w.get('lo') or '') if w.get('lo') and norm(w['lo']) != norm(r['u']) else '', (r.get('ts') or '')[:8], 1 if r['u'] in wb else 0])
        checked = sum(v for k, v in c.items() if k in STATUS_LABEL and k != 'pending')
        vgone = [v for v in vids.values() if v.get('yt') != 200]
        for v in vgone:
            videos_all.append([slug, v['id'], v.get('t', ''), v.get('by', ''), v.get('why', '') or str(v.get('yt')), v.get('wb') or '', v.get('ts', '')[:8]])
        s = {'slug': slug, 'short': short, 'sub': sub, 'total': len(rows), 'checked': checked, 'c': dict(c),
             'docs': sum(1 for r in rows if r['k'] == 'doc'), 'videos': nv, 'vchecked': len(vids), 'vgone': len(vgone),
             'dates': (meta.get('dateEarliest') or '')[:10] + ' – ' + (meta.get('dateLatest') or '')[:10],
             'pagecount': meta.get('pageCount')}
        summary.append(s)
        for k in ('gone', 'away', 'moved', 'live', 'blocked', 'unclear', 'pending', 'wb', 'nowb'):
            total[k] += c.get(k, 0)
        total['all'] += len(rows); total['videos'] += nv; total['vchecked'] += len(vids); total['vgone'] += len(vgone)
        allmonths.update(months)
        for h, hc in hstat.items():
            tot = sum(hc[k] for k in STATUS_LABEL)
            if tot >= 20 and hc['dns'] >= 0.9 * tot:
                deadhosts.append((h, tot, slug, short))
        for f, k in finals.most_common(5):
            if k >= 25:
                catchlist.append((f, k, slug, short))
        for (h, seg), sc in sec.items():
            sections.append((sc['gone'] + sc['away'], h, seg, slug, short))
        json.dump({'slug': slug, 'short': short, 'hosts': hosts, 'rows': out_rows}, open(os.path.join(out, 'data', slug + '.json'), 'w'), separators=(',', ':'))
        # host table for the collection page
        htab = sorted(hstat.items(), key=lambda kv: -(kv[1]['gone'] + kv[1]['away'] + kv[1]['blocked']))
        hrows = ''.join('<tr><td>%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%s</td></tr>' % (
            esc(h), n(sum(hc[k] for k in STATUS_LABEL)), n(hc['gone']), n(hc['away']), n(hc['moved']), n(hc['live']), n(hc['blocked'] + hc['unclear'] + hc['pending'])) for h, hc in htab[:40])
        nosec = ''
        if c.get('blocked'):
            nosec = '<p class="note"><b>%s addresses can\'t be checked.</b> Their site refuses automated requests (a Cloudflare or AWS challenge page, or Akamai\'s “Access Denied”). We don\'t try to get around that, so these addresses are left out of the list below rather than guessed at. Some refusals may lift; they are asked again on later passes.</p>' % n(c['blocked'])
        body = '''<p class="crumb"><a href="../index.html">Overview</a> › %s</p>
<h1>%s</h1>
<p class="lede">%s archived addresses (%s documents) from %s, captured %s. Checked on the live web: %s so far.</p>
%s
%s
<h2 id="gone">Gone or redirected away</h2>
<div id="app" data-slug="%s" data-rel="../"><p>Loading the list…</p></div>
<h2>By website</h2>
<div class="scroll"><table class="tab"><thead><tr><th>Host</th><th class="num">Addresses</th><th class="num">Gone</th><th class="num">Redirected away</th><th class="num">Moved</th><th class="num">Online</th><th class="num">Other</th></tr></thead><tbody>%s</tbody></table></div>
<script src="../app.js?v=%s"></script>''' % (
            esc(short), esc(short), n(len(rows)), n(s['docs']), esc(short), esc(s['dates']), pct(checked, len(rows)),
            bars_html(s), nosec, esc(slug), hrows, V)
        open(os.path.join(out, 'c', slug + '.html'), 'w').write(page(short + ' – Gone from .gov', body, '../', '', 'Pages and documents from the %s archive that the live web no longer serves.' % short))
    # front page
    checked = sum(total[k] for k in ('gone', 'away', 'moved', 'live', 'blocked', 'unclear'))
    lost = total['gone'] + total['away']
    cards = ''.join('''<a class="card" href="c/%s.html"><h3>%s</h3>%s<p class="small">%s addresses · %s checked · <b>%s gone or redirected away</b>%s</p></a>''' % (
        s['slug'], esc(s['short']), bars_html(s, small=True), n(s['total']), pct(s['checked'], s['total']), n(s['c'].get('gone', 0) + s['c'].get('away', 0)),
        (' · %s of %s videos unplayable' % (n(s['vgone']), n(s['vchecked']))) if s['vchecked'] else '') for s in summary)
    hl = []
    if deadhosts:
        dh = sorted(deadhosts, key=lambda x: -x[1])
        hl.append('<h3>Whole websites that no longer exist</h3><p>Every address on these hosts fails because the name itself is gone from the internet\'s address book (DNS).</p><ul class="hl">%s</ul>' % ''.join(
            '<li><b>%s</b> — %s addresses <span class="muted">(%s)</span></li>' % (esc(h), n(t), esc(short)) for h, t, slug, short in dh[:15]))
    if catchlist:
        cl = sorted(catchlist, key=lambda x: -x[1])
        hl.append('<h3>Where redirected pages land</h3><p>Many old addresses now send visitors to one unrelated page.</p><ul class="hl">%s</ul>' % ''.join(
            '<li><b>%s</b> addresses from %s now land on <a href="%s">%s</a></li>' % (n(k), esc(short), esc(f), esc(f.replace('https://', ''))) for f, k, slug, short in cl[:10]))
    sec_top = sorted(sections, reverse=True)[:15]
    if sec_top:
        hl.append('<h3>Biggest losses by section</h3><div class="scroll"><table class="tab"><thead><tr><th>Section</th><th>Collection</th><th class="num">Gone or redirected away</th></tr></thead><tbody>%s</tbody></table></div>' % ''.join(
            '<tr><td>%s/%s</td><td><a href="c/%s.html">%s</a></td><td class="num">%s</td></tr>' % (esc(h), esc(seg), slug, esc(short), n(k)) for k, h, seg, slug, short in sec_top if k))
    looked = total['wb'] + total['nowb']
    left = lost - looked
    wb_big = ('%.1f%%' % (100.0 * total['wb'] / looked)) if looked else '–'
    if left > 0:
        wb_text = 'of the %s looked up so far have a working copy in the Wayback Machine (%s still to look up)' % (n(looked), n(left))
    else:
        wb_text = 'have a working copy in the Wayback Machine (%s of %s)' % (n(total['wb']), n(looked))
    progress = ''
    if total['pending'] or total['vchecked'] < total['videos']:
        progress = '<p class="note">Checks are still running: %s of %s addresses and %s of %s videos checked so far. This page rebuilds every 30 minutes.</p>' % (
            n(checked), n(total['all']), n(total['vchecked']), n(total['videos']))
    body = '''<section class="hero"><h1>Pages the US government took down, still in the archive</h1>
<p class="lede">In the weeks around the January 2025 change of administration, %s pages and documents from ten US government websites were archived. We checked each address on today's live web. <b>%s are gone or now redirect somewhere unrelated</b>%s.</p></section>
%s
<div class="stats">
<div><b>%s</b><span>gone (404, deleted site, “not found” page)</span></div>
<div><b>%s</b><span>redirected away (to a homepage or a catch-all page)</span></div>
<div><b>%s</b><span>%s</span></div>
<div><b>%s</b><span>embedded YouTube videos no longer play</span></div>
</div>
<h2>Collections</h2>
<div class="cards">%s</div>
<p class="legend"><span class="k gone"></span>Gone <span class="k away"></span>Redirected away <span class="k moved"></span>Moved <span class="k live"></span>Still online <span class="k other"></span>Can't be checked, unclear or not yet checked</p>
<h2 id="when">When they disappeared</h2>
<p>Month of the first Wayback Machine capture that found the address missing, after its last working capture. Only addresses the Wayback Machine visited both before and after removal are counted (%s).</p>
%s
<h2>Highlights</h2>
%s''' % (
        n(total['all']), n(lost), (' (of %s checked so far)' % n(checked)) if total['pending'] else '', progress,
        n(total['gone']), n(total['away']), wb_big, wb_text, n(total['vgone']), cards, n(sum(allmonths.values())), chart(allmonths, 'when'), ''.join(hl))
    open(os.path.join(out, 'index.html'), 'w').write(page('Gone from .gov', body, '', 'home', 'Pages from ten US government websites archived in 2024–25 that are gone from the live web today, with links to Wayback Machine copies.'))
    # videos page
    vrows = []
    for slug, short, sub in COLLECTIONS:
        vs = [v for v in videos_all if v[0] == slug]
        if not vs:
            continue
        vrows.append('<h2 id="%s">%s <span class="muted">(%s)</span></h2><div class="scroll"><table class="tab vid"><thead><tr><th>Video</th><th>Channel</th><th>YouTube says</th><th>Wayback Machine</th></tr></thead><tbody>%s</tbody></table></div>' % (
            slug, esc(short), n(len(vs)), ''.join('<tr><td>%s<br><span class="muted small">%s</span></td><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(v[2]) or '<span class="muted">(title not recorded)</span>', esc(v[1]), esc(v[3]), esc(v[4]),
                ('<a href="https://web.archive.org/web/%s/https://www.youtube.com/watch?v=%s">%s</a>' % (v[5], v[1], day(v[5]))) if v[5] else '<span class="muted">no capture</span>') for v in sorted(vs, key=lambda v: v[2].lower() or 'zzz'))))
    vbody = '''<h1>YouTube videos that no longer play</h1>
<p class="lede">The archived pages embedded %s distinct YouTube videos. We asked YouTube about each one: <b>%s of the %s checked no longer play</b> — made private, removed, or their channel closed. The Wayback Machine link is its latest capture of the video's YouTube page (the page, which may not include the video itself).</p>
%s%s''' % (n(total['videos']), n(total['vgone']), n(total['vchecked']), progress, ''.join(vrows) or '<p>No results yet.</p>')
    open(os.path.join(out, 'videos.html'), 'w').write(page('Videos – Gone from .gov', vbody, '', 'videos', 'YouTube videos embedded on archived US government pages that no longer play.'))
    open(os.path.join(out, 'about.html'), 'w').write(page('About – Gone from .gov', ABOUT % {'built': time.strftime('%-d %B %Y %H:%M UTC', time.gmtime())}, '', 'about', 'How Gone from .gov was made.'))
    open(os.path.join(out, '404.html'), 'w').write(page('Not found – Gone from .gov', '<h1>Not here either</h1><p>This address isn\'t part of the site. <a href="index.html">Back to the overview</a>.</p>', '/gone-gov/'))
    open(os.path.join(out, 'robots.txt'), 'w').write('User-agent: *\nAllow: /\nSitemap: %ssitemap.xml\n' % BASE)
    urls = ['', 'videos.html', 'about.html'] + ['c/%s.html' % s['slug'] for s in summary]
    open(os.path.join(out, 'sitemap.xml'), 'w').write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n%s</urlset>\n' % ''.join(
        '<url><loc>%s%s</loc><lastmod>%s</lastmod></url>\n' % (BASE, u, time.strftime('%Y-%m-%d', time.gmtime())) for u in urls))
    json.dump({'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'total': total, 'collections': summary}, open(os.path.join(out, 'data', 'summary.json'), 'w'), indent=1)
    print('built', out, dict(total))

def bars_html(s, small=False):
    c = s['c']; t = float(s['total']) or 1
    parts = [('gone', c.get('gone', 0)), ('away', c.get('away', 0)), ('moved', c.get('moved', 0)), ('live', c.get('live', 0)),
             ('other', c.get('blocked', 0) + c.get('unclear', 0) + c.get('pending', 0))]
    segs = ''.join('<span class="%s" style="width:%.2f%%" title="%s: %s"></span>' % (k, 100 * v / t, {'gone': 'Gone', 'away': 'Redirected away', 'moved': 'Moved', 'live': 'Still online', 'other': "Can't be checked, unclear or not yet checked"}[k], n(v)) for k, v in parts if v)
    lab = '' if small else '<p class="small">%s</p>' % ' · '.join('%s %s' % (n(v), {'gone': 'gone', 'away': 'redirected away', 'moved': 'moved', 'live': 'still online', 'other': "can't be checked, unclear or not yet checked"}[k]) for k, v in parts if v)
    return '<div class="sbar%s" role="img" aria-label="%s">%s</div>%s' % (' small' if small else '', esc('; '.join('%s %s' % (n(v), k) for k, v in parts)), segs, lab)

ABOUT = '''<h1>About</h1>
<p class="lede">Gone from .gov shows which pages and documents from ten archived US government websites are no longer on the live web, and where a working copy can still be found.</p>
<h2>Where the list comes from</h2>
<p>The addresses come from archives of ten US government websites made between November 2024 and April 2025: EPA, CDC, the Department of Education, FEMA, USAID, the Global Change Research Program, Climate.gov, IMLS, Sea Level Change and COVID.gov. We read each archive's list of pages and its capture index straight out of its published WACZ files (only the small index parts, using range requests). Images, scripts, style sheets and data feeds are left out; web pages and documents (PDF, Word, Excel, PowerPoint, CSV) are kept. Addresses are counted once, ignoring http/https, “www.” and a trailing slash.</p>
<h2>How each address is checked</h2>
<ul>
<li><b>Gone</b>: the live site answers 404 or 410, serves a “page not found” page, or the site's name no longer resolves at all.</li>
<li><b>Redirected away</b>: the address now forwards to a homepage, or to a page that at least 25 old addresses land on (for example COVID.gov's pages now forward to a single White House page).</li>
<li><b>Moved</b>: forwards to a specific other page; the content is probably still online. Counted but not listed.</li>
<li><b>Can't be checked</b>: the site refuses automated requests: a Cloudflare challenge (www.ed.gov, www.usaid.gov), an AWS challenge (climate.gov) or Akamai's “Access Denied” (www.fema.gov). We don't try to get around it, so these are left out of the lists. On www.ed.gov the Wayback Machine's own crawler gets the same refusal. A site that answers at first and then starts refusing is treated as rate limiting: the check pauses and asks again later.</li>
</ul>
<p>Requests name this project in their User-Agent and go at most two to four at a time per site. Timeouts and server errors are tried again more slowly.</p>
<h2>Wayback Machine evidence</h2>
<p>For each address that is gone or redirected away we look up its latest working (status 200) capture in the Wayback Machine, and the first capture after it that was not working. Together they bracket when the page disappeared. The chart on the overview counts the month of that first missing capture.</p>
<h2>YouTube videos</h2>
<p>The capture index records every YouTube video the archived pages embedded. We asked YouTube's public oEmbed service about each; for any that fail we read the reason on the video's page (private, removed, account closed). Titles of videos that no longer play come from the Wayback Machine's capture of the video's page. The index doesn't record which page embedded a video, so videos are listed by collection.</p>
<h2>Limits</h2>
<ul><li>A page can return 200 and still have lost its content; we only catch “not found” pages that say so in their title.</li>
<li>“Moved” is counted as online even when the new page says less.</li>
<li>The live web changes; each check has a date in the data files (<code>data/*.json</code>).</li></ul>
<h2 id="accessibility">Accessibility</h2>
<p>The site is plain HTML with a skip link, labelled navigation and form fields, text alternatives for the charts (each has a table view), and enough colour contrast in light and dark mode. Statuses are always written out, never shown by colour alone. The overview, the per-website tables and the videos page work without JavaScript; the searchable lists on the collection pages need it. It is meant to meet WCAG 2.2 AA (Web Content Accessibility Guidelines). If something does not work for you, please write to <a href="mailto:info@archive.org?subject=Gone%%20from%%20.gov">info@archive.org</a>.</p>
<h2>Web archives</h2>
<p>Web archives are welcome to capture this site. If your crawler has trouble capturing it, contact <a href="mailto:info@archive.org?subject=Gone%%20from%%20.gov">info@archive.org</a>.</p>
<h2>Who made this</h2>
<p>This site was made by Claude, an AI model made by Anthropic, working in Claude Code at the direction of Mark Graham (Internet Archive). Mark Graham decided what it should be and what it should cover; Claude did the research and wrote the code.</p>
<p class="muted small">Built %(built)s.</p>'''

if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), 'public'))
