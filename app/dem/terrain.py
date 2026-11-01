"""Positions -> smoothed terrain heights -> ascent and descent.

Taken from MyFITContainer's elevation_correct (2026-11-01), generalised from
FIT records to a plain list of positions:

- `smoothed(positions, sampler)`: the DEM height of every position, averaged
  over a distance window of ±SMOOTH_HALF_M - the 30 m cells and the GPS
  scatter give a staircase that would inflate any step sum. A position
  without a fix (None) or a DEM hole takes its neighbour's height. None
  when there is no usable track (fewer than two fixes, or the DEM knows
  less than half of them).
- `gain_loss(heights)`: ascent and descent with hysteresis - a movement
  counts once it has gone GAIN_THRESHOLD_M one way, so noise does not.

Calibrated on IRONMAN Vichy 2026 (Fenix 8 Pro): bike 2108 m (Strava's DEM
~2100, the watch's barometer 2719), run 147 m (barometer 143 - flat).
`sampler` is anything with `elevation(lat, lon) -> float | None`
(dem.sampler.DemSampler; the tests hand in a fake). DemUnavailable from
the sampler goes through to the caller.
"""

from __future__ import annotations

import math

SMOOTH_HALF_M = 50.0
GAIN_THRESHOLD_M = 4.0


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371008.8
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def smoothed(positions: list, sampler, half_m: float = SMOOTH_HALF_M) -> list[float] | None:
    """Smoothed DEM height per position ((lat, lon) or None)."""
    raw: list[float | None] = [None] * len(positions)
    n_gps = n_ok = 0
    for k, p in enumerate(positions):
        if p is None:
            continue
        n_gps += 1
        e = sampler.elevation(p[0], p[1])
        if e is not None:
            raw[k] = e
            n_ok += 1
    if n_gps < 2 or n_ok < max(2, n_gps // 2):
        return None
    last = None
    for k in range(len(raw)):              # a gap takes the height before it ...
        if raw[k] is None:
            raw[k] = last
        else:
            last = raw[k]
    first = next(v for v in raw if v is not None)
    for k in range(len(raw)):              # ... and the very start the first one
        if raw[k] is None:
            raw[k] = first
        else:
            break
    dist = [0.0] * len(positions)
    prev, cum = None, 0.0
    for k, p in enumerate(positions):
        if p is not None:
            if prev is not None:
                cum += _metres(prev, p)
            prev = p
        dist[k] = cum
    out = [0.0] * len(positions)          # moving mean over ±half_m, two pointers
    lo = hi = 0
    acc = 0.0
    for k in range(len(positions)):
        while hi < len(positions) and dist[hi] <= dist[k] + half_m:
            acc += raw[hi]
            hi += 1
        while dist[lo] < dist[k] - half_m:
            acc -= raw[lo]
            lo += 1
        out[k] = acc / (hi - lo)
    return out


def gain_loss(heights: list[float], threshold: float = GAIN_THRESHOLD_M) -> tuple[float, float]:
    """Ascent and descent with hysteresis."""
    gain = loss = 0.0
    ref = None
    for v in heights:
        if ref is None:
            ref = v
            continue
        d = v - ref
        if d >= threshold:
            gain += d
            ref = v
        elif d <= -threshold:
            loss += -d
            ref = v
    return gain, loss
