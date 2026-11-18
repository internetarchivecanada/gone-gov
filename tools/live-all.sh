#!/bin/sh
# One live-check process per collection: a full pass (rechecking every earlier refusal/error), then an hour's rest
# and a slower retry pass. Run inside screen on the studio.
cd "$(dirname "$0")/.." || exit 1
PY=/opt/homebrew/bin/python3
for s in covid-gov sea-level-change imls usaid global-change-research-program climate-gov-dashboard fema epa cdc department-of-education; do
  (
    while ! grep -q "^$s merged" data/logs/lists-*.log 2>/dev/null; do sleep 60; done
    GG_RECHECK_AGE=0 $PY -m gg.live "$s" >> "data/logs/live-$s.log" 2>&1
    echo "$s pass1 finished $(date)" >> "data/logs/live-$s.log"
    sleep 3600
    GG_RECHECK_AGE=1800 $PY -m gg.live --retry "$s" >> "data/logs/live-$s.log" 2>&1
    echo "$s pass2 finished $(date)" >> "data/logs/live-$s.log"
  ) &
done
wait
