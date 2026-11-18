#!/bin/sh
# Start one live-check process per collection once its list is merged. Run inside screen on the studio.
cd "$(dirname "$0")/.." || exit 1
for s in covid-gov sea-level-change imls usaid global-change-research-program climate-gov-dashboard fema epa cdc department-of-education; do
  (
    while ! grep -q "^$s merged" data/logs/lists-*.log 2>/dev/null; do sleep 60; done
    python3 -m gg.live "$s" >> "data/logs/live-$s.log" 2>&1
    python3 -m gg.live --retry "$s" >> "data/logs/live-$s.log" 2>&1
  ) &
done
wait
