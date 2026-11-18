# Gone from .gov

Which pages and documents from archives of ten US government websites (captured November 2024 – April 2025) are no longer on the live web, and where a working copy can still
be found in the Wayback Machine. Also: embedded YouTube videos that no longer play.

Live: https://wayback-labs.sf.archive.org/gone-gov/ (Wayback Machine Labs studio, static service `gone-gov`).

## Sources

- **Archives of ten US government websites**: each one's
  page list (`pages/*.jsonl`) and capture index (`indexes/*.cdx.gz`), read straight out of its published WACZ files
  with HTTP range requests, without downloading the archives. Web pages and documents (PDF, Word, Excel,
  PowerPoint, CSV) are kept; images, scripts, style sheets and data feeds are left out.
- **The live web**, checked once per address (`gg/live.py`).
- **Wayback Machine** CDX API: latest working capture and the first missing capture after it (`gg/wayback.py`).
- **YouTube** oEmbed and video pages for embedded videos; titles of dead videos from the Wayback Machine (`gg/videos.py`).

## Pipeline (stdlib Python; on the studio use /opt/homebrew/bin/python3)

The studio's system Python 3.9 uses LibreSSL 2.8.3, which has no TLS 1.3, so some sites fail with it.

```
python3 -m gg.lists [slug ...]    # page lists + document captures + YouTube embeds from each WACZ   ~30 min
python3 -m gg.live [slug ...]     # live check (rechecks refusals/errors older than GG_RECHECK_AGE, default 6 h)
python3 -m gg.live --retry slug   # slower pass
python3 -m gg.wayback [slug ...]  # last working Wayback capture + first missing capture after it
python3 -m gg.videos [slug ...]   # YouTube oEmbed + reason + Wayback watch-page capture
python3 -m gg.site OUT            # static site
```

Data lives in `$GG_DATA` (studio: `/Volumes/4tb-ext/data/gone-gov`, symlinked as `data/` in `~/gone-gov-work`, where
the jobs run). `tools/live-all.sh` runs the live checks (screen `gg-live`), `tools/wayback-loop.sh` the Wayback lookups, one
collection at a time and repeating (screen `gg-wayback`), `tools/after-live.sh` the video checks (screen `gg-after`). `tools/rebuild-loop.sh` rebuilds `/opt/services/gone-gov/public` every 30 minutes (screen
`gg-site`). Screen sessions don't survive a studio reboot; every step is resumable, so start them again. Quitting a
screen session leaves its program running: kill old PIDs (`ps -axo pid,lstart,command | grep gg.`).

### Politeness

Requests name the project in their User-Agent. One request at a time per site (two for sites with more than 50,000
addresses), half a second apart. A site that refuses automated requests (Cloudflare or AWS WAF challenge, Akamai
"Access Denied", 403, 429) 15 times in a row without ever answering is marked blocked and not asked further; a site
that answered before is treated as rate limiting (15-minute pauses). Challenges are never solved or bypassed.

### Statuses (`gg/classify.py`)

- **gone**: 404/410, a "not found" page served with 200, or the site's name no longer resolves
- **away**: redirects to a homepage or to a page at least 25 old addresses land on
- **moved**: redirects to a specific other page (counted, not listed)
- **live**, **blocked** (refuses automated requests), **unclear** (other errors)


## Deploy

```
rsync -a --exclude .git --exclude data --exclude public ./ studioj:/opt/services/gone-gov/
rsync -a --exclude .git --exclude data --exclude public ./ studioj:gone-gov-work/
```

The Caddy snippet is `caddy` (real 404s, gzip/zstd).

## Who made this

Made by Claude, an AI model made by Anthropic, working in Claude Code at the direction of Mark Graham (Internet
Archive). Mark decided what it should cover; Claude did the research and wrote the code.
