"""Forecast launch-day Twitch viewers hour by hour (R4: shrunk log-log shape).

The failure this fixes: anchoring every hour's forecast to the hour-1
print.  Hour 1 of a rolling-midnight launch covers only the regions that
have unlocked by 01:00 UTC (New Zealand and Australia, mostly), so a
first-hour print can be far below the day's real level -- on the practice
launch Marvel's Wolverine the median comparable shape anchored to hour 1
missed the evening by more than a factor of two in log terms.  A low
hour-1 print is therefore not just "a small game": across the rolling
comparables, log(hour-1 viewers) correlates -0.77 with the log evening
rise, so the level must be shrunk toward the comparables, not trusted
absolutely.

Model, fitted at run time from the case's own comparables only (nothing
is hard-coded from the practice answers):
  * For each release-day hour h = 2..24, regress log(viewers_h) on
    log(viewers_1) over the comparables that unlocked rolling at midnight
    local time (the same unlock pattern as GTA VI).  A slope below 1 is
    the shrinkage: a depressed hour 1 lifts the forecast less than
    proportionally, a strong hour 1 is pulled back toward the pack.
  * The per-hour slope is noisy with only ~13 rolling comparables, so it
    is shrunk 70% of the way toward a single pooled slope estimated from
    all (comparable, hour) pairs with hour intercepts removed, and the
    intercept is refitted at the shrunk slope.
  * The quantile spread is the residual spread of that regression per
    hour (population standard deviation of the residuals), floored at
    0.12 and capped at 1.20 log units, so hours the comparables disagree
    on get wider bands.
  * Hours with fewer than five usable comparables fall back to the
    median-ratio shape (median of viewers_h / viewers_1 across the pool)
    with an IQR-based spread, the same fallback R1 used.

Only comparables whose unlock note says they unlocked rolling at
midnight local time are used: simultaneous global unlocks peak in hour 1
and then fall, which flattens the rolling shape, and early-access and
unverified launches are left out for the same reason.  When fewer than
five rolling comparables have usable data the pool falls back to all
comparables, so the program never fails for lack of a pool.

Python 3.13, standard library only, no network, deterministic.
Reads every *.in in $MAKEFUN_INPUT_DIR (else /input), writes one
/output/<id>.out per case: {"hours": [{"hour": h, "q": [q05, q25, q50,
q75, q95]}]} for h = 2..24.
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0, 0.6744897501960817,
     1.6448536269514722]

# Floor / cap on the log-spread, in log units.
SIGMA_MIN = 0.12
SIGMA_MAX = 1.20
# How far each hour's fitted slope is pulled toward the pooled slope.
SHRINK = 0.7
# Sane bounds for a shrunk slope: a slope below 0 would say a bigger
# hour 1 means a smaller later hour, and above 1.5 would amplify hour 1
# more than any comparable in the practice ever did (fitted slopes there
# ran 0.48 to 1.11).  The clamp never binds on the practice; it only
# guards a future case against one wild per-hour fit.
SLOPE_MIN = 0.0
SLOPE_MAX = 1.5
MIN_POINTS = 5


def parse_time(s):
    """Parse an ISO-8601 UTC timestamp into epoch seconds (float)."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if n == 0:
        return None
    if n % 2 == 1:
        return xs[n // 2]
    return 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def round2(x):
    """Round to 2 decimals, half up (like the house baseline's rounding)."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if float(value).is_integer() else value


def clamp_q(x):
    """Keep a quantile finite, > 0 and <= 1e9, as the format requires."""
    if not math.isfinite(x):
        return 1.0
    if x <= 0:
        return 0.01
    if x > 1e9:
        return 1e9
    return x


def release_day_hours(comp):
    """Return {hour: viewers} for the comparable's release UTC day.

    Hours are 1..24 counted from the comparable's day_start.  Only hours
    with a positive viewer count are kept; a zero or missing hour is left
    out so it never drags a ratio to zero or infinity.
    """
    try:
        start = parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return {}
    hours = {}
    for row in comp.get("hourly") or []:
        try:
            t = parse_time(row["from"])
            v = float(row["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        if v <= 0:
            continue
        h = int((t - start) // 3600) + 1
        if 1 <= h <= 24:
            # If a day holds two points for one hour, keep the first.
            hours.setdefault(h, v)
    return hours


def is_rolling_unlock(comp):
    """True when the comparable unlocked rolling at midnight local time.

    The unlock note is free text; a launch counts as rolling when it says
    so ("rolling") or says consoles unlocked at midnight local.  A launch
    whose note does not say that -- a single simultaneous global unlock,
    an early-access launch, or an unverified one -- is not used for the
    shape, because its release-day curve peaks at a different hour.
    """
    text = str(comp.get("unlock") or "").lower()
    return "rolling" in text or "midnight local" in text


def shape_pool(comparables):
    """The comparables the shape is taken from (rolling unlocks preferred)."""
    rolling = [c for c in (comparables or []) if is_rolling_unlock(c)]
    if len(rolling) >= 5:
        return rolling
    return list(comparables or [])


def ols(xs, ys):
    """Least-squares intercept and slope of y on x."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    if vx <= 0:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx
    return my - b * mx, b


def pooled_slope(by_hour):
    """One slope for all hours, from within-hour demeaned pairs.

    Each hour's points are centred on their own means first, so the
    hour intercepts cannot leak into the slope.
    """
    num = 0.0
    den = 0.0
    for pairs in by_hour.values():
        mx = sum(x for x, _ in pairs) / len(pairs)
        my = sum(y for _, y in pairs) / len(pairs)
        for x, y in pairs:
            num += (x - mx) * (y - my)
            den += (x - mx) ** 2
    return num / den if den > 0 else 1.0


def fallback_shape_sigma(log_ratios):
    """Median-ratio shape and IQR spread for hours short on points."""
    shape = {}
    sigma = {}
    for h, xs in log_ratios.items():
        xs = sorted(xs)
        if len(xs) >= 3:
            shape[h] = math.exp(median(xs))
            q25 = xs[len(xs) // 4]
            q75 = xs[(3 * len(xs)) // 4]
            spread = (q75 - q25) / 1.349 if q75 > q25 else 0.0
            sigma[h] = min(SIGMA_MAX, max(SIGMA_MIN, spread))
        elif xs:
            shape[h] = math.exp(median(xs))
            sigma[h] = 0.35
    known = sorted(shape)
    if not known:
        return {h: 1.0 for h in range(2, 25)}, {h: 0.35 for h in range(2, 25)}
    for h in range(2, 25):
        if h in shape:
            continue
        before = [k for k in known if k < h]
        after = [k for k in known if k > h]
        if before and after:
            lo, hi = before[-1], after[0]
            w = (h - lo) / (hi - lo)
            shape[h] = shape[lo] * (shape[hi] / shape[lo]) ** w
            sigma[h] = sigma[lo] * (1.0 - w) + sigma[hi] * w
        elif before:
            shape[h] = shape[before[-1]]
            sigma[h] = sigma[before[-1]]
        else:
            shape[h] = shape[after[0]]
            sigma[h] = sigma[after[0]]
    return shape, sigma


def forecast_case(case, name):
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, not {LEVELS}")
    known = case.get("known") or []
    first = next((k for k in known if k.get("hour") == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    log_p1 = math.log(p1)

    pool = shape_pool(case.get("comparables"))
    # Release-day hours per comparable, computed once.
    days = [release_day_hours(c) for c in pool]
    by_hour = {h: [] for h in range(2, 25)}
    log_ratios = {h: [] for h in range(2, 25)}
    for hours in days:
        v1 = hours.get(1)
        if not v1:
            continue
        lv1 = math.log(v1)
        for h in range(2, 25):
            v = hours.get(h)
            if v:
                by_hour[h].append((lv1, math.log(v)))
                log_ratios[h].append(math.log(v / v1))
    fb_shape, fb_sigma = fallback_shape_sigma(log_ratios)
    b_pool = pooled_slope({h: ps for h, ps in by_hour.items() if ps})

    rows = []
    for row in case["forecast"]:
        h = int(row["hour"])
        pairs = by_hour[h]
        if len(pairs) >= MIN_POINTS:
            xs = [x for x, _ in pairs]
            ys = [y for _, y in pairs]
            a, b = ols(xs, ys)
            # Shrink the noisy per-hour slope toward the pooled slope,
            # clamp it to the sane range, and refit the intercept at the
            # shrunk slope.
            b = SHRINK * b + (1.0 - SHRINK) * b_pool
            b = min(SLOPE_MAX, max(SLOPE_MIN, b))
            a = sum(y - b * x for x, y in pairs) / len(pairs)
            med = math.exp(a + b * log_p1)
            resid = [y - (a + b * x) for x, y in pairs]
            sig = statistics.pstdev(resid) if len(resid) > 1 else 0.35
            sig = min(SIGMA_MAX, max(SIGMA_MIN, sig))
        else:
            med = p1 * fb_shape[h]
            sig = fb_sigma[h]
        qs = []
        prev = None
        for z in Z:
            q = clamp_q(round2(med * math.exp(z * sig)))
            if prev is not None and q < prev:
                q = prev
            qs.append(q)
            prev = q
        rows.append({"hour": h, "q": qs})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    in_files = sorted(INPUT_DIR.glob("*.in"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in in_files:
        with open(path, "r", encoding="utf-8") as f:
            case = json.load(f)
        out = forecast_case(case, path.name)
        out_path = OUTPUT_DIR / (path.stem + ".out")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"))
            f.write("\n")


if __name__ == "__main__":
    main()
