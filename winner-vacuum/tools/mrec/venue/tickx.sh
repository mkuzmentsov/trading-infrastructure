#!/bin/bash
RAW=/Users/maxkuzmentsov/development/projects/my/hummingbot/hummingbot-infra/every-tick-single/data/mrec
for c in btc eth sol xrp bnb doge hype; do
  for f in $RAW/$c/$c-mrecev-*.jsonl.gz; do gzcat "$f" | grep '"et":"tick_size_change"' ; done
done > tick_raw.jsonl
echo done > tickx.done
