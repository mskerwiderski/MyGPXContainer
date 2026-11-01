"""dem v1.0.0 - terrain heights from the Copernicus GLO-30 elevation model.

A MyCommons building block, copied into its users by MyCommons/sync.sh:
MyFITContainer (app/dem/, its DEM elevation correction of FIT files),
MyGPXContainer (app/dem/, heights and climb of every route).
Never edit a copy; change it in MyCommons, run its tests, bump the version,
sync again. `dem.sampler` loads and reads the 1° tiles (from the free AWS
Open Data bucket, cached on disk forever - positions never leave the
server, only which 1° cell is fetched); `dem.terrain` turns positions into
smoothed heights and ascent/descent (calibrated on MyFITContainer's
references, IRONMAN Vichy 2026). Needs `rasterio` (imported only when a
tile is read) and `httpx`.
"""

from .sampler import DemSampler, DemUnavailable, tile_name  # noqa: F401 - the old app/dem.py API

__version__ = "1.0.0"
