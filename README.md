# gta6-r4-shape-fix

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/aboybro/gta6-r4-shape-fix/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/aboybro/gta6-r4-shape-fix/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), given only the first hour's count.

## How it works

Variant R4 — shrunk log-log shape. The previous variant (R1) anchored every
hour to the hour-1 print, but hour 1 of a rolling-midnight launch only
covers the regions unlocked by 01:00 UTC, so a low first hour understates
the whole day: on the practice launch Marvel's Wolverine that cost a
pinball loss of 0.51. Across the rolling comparables, log(hour-1 viewers)
correlates −0.77 with the log evening rise, so the level must be shrunk,
not trusted absolutely.

For each hour h = 2..24, the program regresses log(viewers at h) on
log(viewers at hour 1) over the comparables that unlocked rolling at
midnight local time (the same unlock pattern as GTA VI). A slope below 1
is the shrinkage: a depressed hour 1 lifts the forecast less than
proportionally. The noisy per-hour slope is shrunk 70% of the way toward a
single pooled slope (estimated from all comparable-hour pairs with hour
intercepts removed) and clamped to [0, 1.5], with the intercept refitted at
the shrunk slope. The quantile spread is the residual spread of that
regression per hour, floored at 0.12 and capped at 1.20 log units. Hours
with fewer than five usable comparables fall back to the median-ratio
shape with an IQR-based spread.

Only comparables with the same unlock pattern as GTA VI are used for the
fit: launches that unlocked rolling at midnight local time. Simultaneous
global unlocks, early-access launches and unverified ones are left out,
because their release-day curves peak at a different hour. When fewer than
five rolling comparables have usable data, the pool falls back to all
comparables.

On the four practice launches this scores a mean pinball loss of 0.160
(log scale) — p00 0.188, p01 0.119, p02 0.116, p03 0.217 — against the
house baseline's 0.387 and the previous variant's 0.262.

## Run it

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13, standard library only, no network. Reads every `*.in` in the
input directory and writes one `<id>.out` per case:
`{"hours": [{"hour": h, "q": [q05, q25, q50, q75, q95]}]}` for hours 2..24.
Deterministic; runs in well under 8 seconds per case.

---

<sub>Entered on [make.fun](https://make.fun/?ref=mbyg0687&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>

<!-- SPDX-License-Identifier: MIT -->
