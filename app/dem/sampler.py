"""Copernicus GLO-30 DEM sampler (taken unchanged from MyFITContainer's
app/dem.py, 2026-11-01): elevation lookups for an elevation correction. Tiles (1°x1° Cloud-Optimized GeoTIFFs) come
from the free, unauthenticated AWS Open Data bucket and are cached on disk
forever — a tile never changes, GPS coordinates never leave the server (same
doctrine as geocode.py; the bucket only sees which 1° cell was fetched).

rasterio is imported lazily so the app runs without it until a DEM lookup is
actually requested (tests inject a fake sampler)."""

from __future__ import annotations

import logging
import math
import os

log = logging.getLogger("dem")

_S3_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
# GLO-30 nodata / ocean cells sit at 0.0; genuinely invalid values are far
# below any real elevation (Dead Sea -430 m).
_MIN_VALID_M = -500.0


class DemUnavailable(Exception):
    """Tile could not be loaded (network down, rasterio missing, corrupt file).
    Distinct from "no data here" (elevation() -> None) so callers can treat
    transient failures as non-cacheable."""


def tile_name(lat: float, lon: float) -> str:
    """Bucket tile name of the 1° cell, e.g.
    Copernicus_DSM_COG_10_N46_00_E003_00_DEM (COG_10 = GLO-30)."""
    la, lo = math.floor(lat), math.floor(lon)
    ns = "N" if la >= 0 else "S"
    ew = "E" if lo >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(la):02d}_00_{ew}{abs(lo):03d}_00_DEM"


class DemSampler:
    """elevation(lat, lon) -> height in m or None (no tile/nodata).
    Tile arrays are memoized per instance — an instance lives for one
    correction/preview run, after that the memory is free again."""

    def __init__(self, cache_dir: str, allow_download: bool = True):
        self._cache_dir = cache_dir
        # allow_download=False: only use already cached tiles, otherwise
        # DemUnavailable. For the page build (preview) — a tile download takes
        # ~10-30 s depending on the line and must not block a rendering.
        self._allow_download = allow_download
        self._tiles: dict[str, tuple | None] = {}

    def tile_cached(self, lat: float, lon: float) -> bool:
        """True if the tile of this position is already on disk."""
        return os.path.exists(
            os.path.join(self._cache_dir, f"{tile_name(lat, lon)}.tif"))

    def _download(self, name: str, path: str) -> bool:
        """Load a tile from the S3 bucket into the cache. False on 404 (cell not
        in the dataset, e.g. open ocean), DemUnavailable for anything a later
        retry can heal."""
        import httpx
        url = f"{_S3_BASE}/{name}/{name}.tif"
        tmp = f"{path}.tmp{os.getpid()}"
        try:
            with httpx.stream("GET", url, timeout=httpx.Timeout(180, connect=15)) as r:
                if r.status_code == 404:
                    return False
                r.raise_for_status()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
            os.replace(tmp, path)
            log.info("dem tile %s cached (%.1f MB)", name,
                     os.path.getsize(path) / 1e6)
            return True
        except httpx.HTTPError as exc:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise DemUnavailable(f"tile {name}: {exc}") from exc

    def _tile(self, name: str) -> tuple | None:
        """(band array, inverse affine, nodata) or None (tile does not exist).
        Errors while reading/loading -> DemUnavailable."""
        if name in self._tiles:
            return self._tiles[name]
        path = os.path.join(self._cache_dir, f"{name}.tif")
        if not os.path.exists(path):
            if not self._allow_download:
                raise DemUnavailable(f"tile {name} not cached")
            if not self._download(name, path):
                self._tiles[name] = None
                return None
        try:
            import rasterio
            with rasterio.open(path) as ds:
                arr = ds.read(1)
                inv = ~ds.transform
                nodata = ds.nodata
        except Exception as exc:                       # noqa: BLE001
            # Do not leave a corrupt file behind — the next run downloads again.
            try:
                os.remove(path)
            except OSError:
                pass
            raise DemUnavailable(f"tile {name} unreadable: {exc}") from exc
        self._tiles[name] = (arr, inv, nodata)
        return self._tiles[name]

    def elevation(self, lat: float, lon: float) -> float | None:
        """Bilinearly interpolated terrain height (m). None without tile/nodata.
        Interpolation stays within the tile (edge points are clamped to the
        outermost cell row — negligible with 30 m cells)."""
        t = self._tile(tile_name(lat, lon))
        if t is None:
            return None
        arr, inv, nodata = t
        h, w = arr.shape
        colf, rowf = inv * (lon, lat)
        # Affine returns pixel CORNER coordinates; cell CENTRES lie at +0.5.
        x, y = colf - 0.5, rowf - 0.5
        c0 = min(max(int(math.floor(x)), 0), w - 2)
        r0 = min(max(int(math.floor(y)), 0), h - 2)
        fx = min(max(x - c0, 0.0), 1.0)
        fy = min(max(y - r0, 0.0), 1.0)
        v00, v01 = float(arr[r0, c0]), float(arr[r0, c0 + 1])
        v10, v11 = float(arr[r0 + 1, c0]), float(arr[r0 + 1, c0 + 1])
        vals = (v00, v01, v10, v11)
        if any(math.isnan(v) or v < _MIN_VALID_M
               or (nodata is not None and v == nodata) for v in vals):
            return None
        return ((v00 * (1 - fx) + v01 * fx) * (1 - fy)
                + (v10 * (1 - fx) + v11 * fx) * fy)
