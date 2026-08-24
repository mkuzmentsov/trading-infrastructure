Pre-EVERYBAR-experiment snapshot, 2026-08-15 22:25 Kyiv.
These six yamls are the config that was LIVE before the every-bar
experiment (thresh 0.5, halt $15, $5 orders, 9sh).
The shared overlay every-tick-single/chart/bots/crypto.secret.yaml had
liveMaxDailyLossUsd: "15" at snapshot time (experiment sets it to "999").
REVERT = cp these over chart/bots/, sed overlay halt back to "15",
then: cd winner-vacuum && for n in eth bnb btc sol xrp hype; do
./deploy.sh $n live vacmaker; done
