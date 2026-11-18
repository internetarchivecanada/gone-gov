#!/bin/sh
# Videos per collection once its list exists. (Wayback lookups run separately in tools/wayback-loop.sh.)
cd "$(dirname "$0")/.." || exit 1
for s in covid-gov sea-level-change imls usaid global-change-research-program climate-gov-dashboard fema epa cdc department-of-education; do
  while ! grep -q "^$s merged" data/logs/lists-*.log 2>/dev/null; do sleep 60; done
  /opt/homebrew/bin/python3 -m gg.videos "$s" >> data/logs/videos.log 2>&1
done
