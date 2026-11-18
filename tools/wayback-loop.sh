#!/bin/sh
# Look up Wayback copies for every address currently classed gone / redirected away, one collection at a time,
# without waiting for the live checks to finish; repeat so newly found ones are added. Resumable. Screen: gg-wayback.
cd "$(dirname "$0")/.." || exit 1
PY=/opt/homebrew/bin/python3
while true; do
  for s in global-change-research-program usaid covid-gov sea-level-change imls cdc epa department-of-education fema climate-gov-dashboard; do
    $PY -m gg.wayback "$s" >> "data/logs/wayback-$s.log" 2>&1
  done
  sleep 1800
done
