"""Every time a government site refused or limited our checks.

    python3 -m gg.blocks              per-host table on stdout
    python3 -m gg.blocks --since YYYYMMDDHHMMSS   only host-level events and refusals after that time (UTC)

Sources: data/live/*.jsonl (one row per request; rows with 'blk' are refusals we actually received, rows with
st 'blocked' were never sent because the host had already been marked blocked) and data/blocks/events.jsonl
(written by gg.live from 2026-11-26: the server's identifying headers for each refusal, plus pauses,
block decisions and give-ups).
"""
import json, os, sys, time
from collections import defaultdict
from gg.common import COLLECTIONS, DATA, jsonl

KIND = {'cloudflare': 'Cloudflare challenge', 'aws-waf': 'AWS WAF challenge', 'challenge': 'Challenge page (202)',
        'akamai': 'Akamai “Access Denied”', 'cloudfront': 'CloudFront “Request blocked”', 'access-denied': '403 “Access Denied” (service not identified)', 'forbidden': '403 Forbidden (no challenge page)', 'rate': '429 Too Many Requests'}


def hostname(u):
    return u.split('/')[2].lower() if u.count('/') >= 2 else u


def collect(since=''):
    """Per (collection, host): refused requests by kind, first/last refusal, answers received, not-sent count,
    no-answer (timeout / connection refused) count; plus the host-level events list."""
    hosts = defaultdict(lambda: {'kinds': defaultdict(int), 'first': '', 'last': '', 'ok': 0, 'notsent': 0,
                                 'noans': 0, 'last_ok': ''})
    for slug, short, sub in COLLECTIONS:
        path = os.path.join(DATA, 'live', slug + '.jsonl')
        if not os.path.exists(path):
            continue
        skipped = {}
        with open(path, 'rb') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                at = d.get('at', '')
                if at < since:
                    continue
                st = d.get('st')
                key = (slug, hostname(d['u']))
                h = hosts[key]
                if st == 'blocked':
                    skipped[d['u']] = key
                    continue
                skipped.pop(d['u'], None)
                if d.get('blk'):
                    h['kinds'][d['blk']] += 1
                    h['first'] = min(h['first'] or at, at)
                    h['last'] = max(h['last'], at)
                elif st in ('timeout', 'refused'):
                    h['noans'] += 1
                elif st not in ('dns', 'tls', 'err'):
                    h['ok'] += 1
                    h['last_ok'] = max(h['last_ok'], at)
        for key in skipped.values():
            hosts[key]['notsent'] += 1
    events = []
    evidence = {}
    path = os.path.join(DATA, 'blocks', 'events.jsonl')
    for e in jsonl(path) if os.path.exists(path) else []:
        if e.get('at', '') < since:
            continue
        if e['type'] in ('refused', 'limited'):
            evidence[(e['coll'], e['host'])] = e
        elif e['type'] != 'no-answer':
            events.append(e)
    rows = {k: v for k, v in hosts.items() if v['kinds'] or v['notsent']}
    return rows, events, evidence


def ts(t):
    return time.strftime('%Y-%m-%d %H:%M UTC', time.strptime(t, '%Y%m%d%H%M%S')) if t else ''


def main():
    since = ''
    if '--since' in sys.argv:
        since = sys.argv[sys.argv.index('--since') + 1]
    rows, events, evidence = collect(since)
    print('%-12s %-34s %8s %8s %8s  %-17s %-17s %s' % ('collection', 'host', 'refused', 'notsent', 'answered', 'first', 'last', 'kinds'))
    for (slug, host), v in sorted(rows.items(), key=lambda kv: -sum(kv[1]['kinds'].values())):
        print('%-12s %-34s %8d %8d %8d  %-17s %-17s %s' % (slug[:12], host[:34], sum(v['kinds'].values()), v['notsent'], v['ok'],
              ts(v['first'])[:16], ts(v['last'])[:16], ', '.join('%s %d' % kv for kv in v['kinds'].items())))
    for e in events:
        print(ts(e['at']), e['type'], e['coll'], e['host'], e.get('blk', ''))


if __name__ == '__main__':
    main()
