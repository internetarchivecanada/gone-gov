#!/bin/sh
# Per collection: wait for the live check and its retry pass, then Wayback lookups. Videos once lists exist.
cd "$(dirname "$0")/.." || exit 1
for s in covid-gov sea-level-change imls usaid global-change-research-program climate-gov-dashboard fema epa cdc department-of-education; do
  (
    while ! grep -q "^$s merged" data/logs/lists-*.log 2>/dev/null; do sleep 60; done
    /opt/homebrew/bin/python3 -m gg.videos "$s" >> data/logs/videos.log 2>&1
  ) &
  (
    while ! grep -q "^$s pass2 finished" "data/logs/live-$s.log" 2>/dev/null; do sleep 120; done
    /opt/homebrew/bin/python3 -m gg.wayback "$s" >> "data/logs/wayback-$s.log" 2>&1
  ) &
done
wait
