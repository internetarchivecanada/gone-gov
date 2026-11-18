#!/bin/sh
# Rebuild the served site every 30 minutes from the studio data folder (fresh Python process each time).
cd /opt/services/gone-gov || exit 1
while true; do
  GG_DATA=/Volumes/4tb-ext/data/gone-gov /opt/homebrew/bin/python3 -m gg.site /opt/services/gone-gov/public >> /Volumes/4tb-ext/data/gone-gov/logs/site.log 2>&1
  sleep 1800
done
