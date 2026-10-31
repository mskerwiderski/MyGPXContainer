"""Reading GPX files: track (or route) points, name, description, and the
figures shown for a route.

Parsed with defusedxml (no entity expansion, no external entities). Elements
are matched by local name, so GPX 1.0 and 1.1 both work. All track segments of
all tracks are joined in file order; a file without a track uses its route
(`rte`). Waypoints are ignored. Points without a valid position - and (0,0),
which some devices write before they have a fix - are dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from defusedxml import ElementTree

from .i18n import N_

MAX_BYTES = 10 * 1024 * 1024
LOOP_M = 200            # start and finish closer than this: a loop


class GpxError(ValueError):
    pass


@dataclass
class Track:
    name: str = ""
    description: str = ""
    points: list[tuple[float, float, float | None]] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str) -> str:
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def _point(el) -> tuple[float, float, float | None] | None:
    try:
        lat, lon = float(el.get("lat")), float(el.get("lon"))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    try:
        ele = float(_child_text(el, "ele"))
    except ValueError:
        ele = None
    if ele is not None and not math.isfinite(ele):
        ele = None
    return lat, lon, ele


def parse(data: bytes) -> Track:
    if len(data) > MAX_BYTES:
        raise GpxError(N_("The file is larger than 10 MB."))
    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:   # defusedxml raises its own types besides ParseError
        raise GpxError(N_("This is not a valid GPX file.")) from exc
    if _local(root.tag) != "gpx":
        raise GpxError(N_("This is not a valid GPX file."))
    track = Track()
    trk_points, rte_points = [], []
    meta_name = meta_desc = ""
    for el in root:
        kind = _local(el.tag)
        if kind == "metadata":
            meta_name, meta_desc = _child_text(el, "name"), _child_text(el, "desc")
        elif kind in ("trk", "rte"):
            track.name = track.name or _child_text(el, "name")
            track.description = track.description or _child_text(el, "desc")
            target = trk_points if kind == "trk" else rte_points
            want = "trkpt" if kind == "trk" else "rtept"
            for p in el.iter():
                if _local(p.tag) == want and (pt := _point(p)):
                    target.append(pt)
    track.points = trk_points or rte_points
    track.name = meta_name or track.name
    track.description = meta_desc or track.description
    if len(track.points) < 2:
        raise GpxError(N_("The file has no track with at least two points."))
    return track


def haversine(a, b) -> float:
    r = 6371008.8
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(min(1.0, h)))


def distances(points) -> list[float]:
    """Cumulative distance in metres at every point."""
    out = [0.0]
    for i in range(1, len(points)):
        out.append(out[-1] + haversine(points[i - 1], points[i]))
    return out


def _climb(eles: list[float]) -> tuple[float, float]:
    """Ascent and descent as the plain sum of the steps, like Komoot and
    Garmin courses show it (Gravel 90: 223 m both). Planned routes come with
    smooth model heights; any smoothing here cost 10-20 %. A recorded track
    with noisy heights comes out too high - a DEM is the fix for that, later."""
    up = down = 0.0
    for a, b in zip(eles, eles[1:]):
        if b > a:
            up += b - a
        else:
            down += a - b
    return up, down


def stats(track: Track) -> dict:
    pts = track.points
    eles = [p[2] for p in pts if p[2] is not None]
    has_ele = len(eles) >= len(pts) / 2
    up, down = _climb(eles) if has_ele else (None, None)
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    return {
        "distance_m": round(distances(pts)[-1], 1),
        "ascent_m": round(up) if up is not None else None,
        "descent_m": round(down) if down is not None else None,
        "min_ele": round(min(eles)) if has_ele else None,
        "max_ele": round(max(eles)) if has_ele else None,
        "start_lat": pts[0][0], "start_lon": pts[0][1],
        "min_lat": min(lats), "min_lon": min(lons), "max_lat": max(lats), "max_lon": max(lons),
        "loop": haversine(pts[0], pts[-1]) < LOOP_M,
        "point_count": len(pts),
    }


def _thin(n: int, limit: int) -> list[int]:
    if n <= limit:
        return list(range(n))
    step = (n - 1) / (limit - 1)
    return sorted({round(i * step) for i in range(limit)})


def display(track: Track, map_points: int = 3000, profile_points: int = 1000) -> dict:
    """What the detail page draws: the line for the map ([lat, lon]) and the
    elevation profile ([km], [m]), both thinned out."""
    pts = track.points
    dist = distances(pts)
    line = [[round(pts[i][0], 6), round(pts[i][1], 6)] for i in _thin(len(pts), map_points)]
    idx = [i for i in _thin(len(pts), profile_points) if pts[i][2] is not None]
    return {"line": line,
            "profile": {"km": [round(dist[i] / 1000, 3) for i in idx],
                        "ele": [round(pts[i][2], 1) for i in idx],
                        "lat": [round(pts[i][0], 6) for i in idx],
                        "lon": [round(pts[i][1], 6) for i in idx]}}


def write(name: str, points, description: str = "") -> bytes:
    """A GPX 1.1 track from points (lat, lon, ele|None) - for sources that
    deliver coordinates instead of a file (Komoot)."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="MyGPXContainer" xmlns="http://www.topografix.com/GPX/1/1">',
           f"<metadata><name>{escape(name)}</name>"
           + (f"<desc>{escape(description)}</desc>" if description else "") + "</metadata>",
           f"<trk><name>{escape(name)}</name><trkseg>"]
    for lat, lon, ele in points:
        e = f"<ele>{ele:.1f}</ele>" if ele is not None else ""
        out.append(f"<trkpt lat={quoteattr(f'{lat:.6f}')} lon={quoteattr(f'{lon:.6f}')}>{e}</trkpt>")
    out.append("</trkseg></trk></gpx>")
    return ("\n".join(out) + "\n").encode()


def outline(track: Track, points: int = 200) -> list[list[float]]:
    """A coarse line of the whole route for the overview map."""
    pts = track.points
    return [[round(pts[i][0], 5), round(pts[i][1], 5)] for i in _thin(len(pts), points)]


def sketch(track: Track, points: int = 80, size: int = 100, pad: int = 8) -> dict:
    """The route's shape for a small SVG (viewBox 0 0 size size): north up,
    longitude scaled by cos(latitude), centred. {"d": path, "x"/"y": start}."""
    pts = [track.points[i] for i in _thin(len(track.points), points)]
    k = math.cos(math.radians(sum(p[0] for p in pts) / len(pts)))
    xs, ys = [p[1] * k for p in pts], [-p[0] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    scale = (size - 2 * pad) / (max(w, h) or 1e-9)
    ox = (size - w * scale) / 2 - min(xs) * scale
    oy = (size - h * scale) / 2 - min(ys) * scale
    xy = [(round(x * scale + ox, 1), round(y * scale + oy, 1)) for x, y in zip(xs, ys)]
    d = "M" + " L".join(f"{x} {y}" for x, y in xy)
    return {"d": d, "x": xy[0][0], "y": xy[0][1]}
