"""Routing service of MyGPXContainer: keeps a GraphHopper graph of the map
regions MGC wants and serves it on :8989 (only inside the Docker network).

The volume /data is shared with MGC (mounted there as /routing):
- regions.json  written by MGC: {"regions": [{"id", "name", "pbf"}], "rebuild": "<stamp>"}
- status.json   written here (see `Status`), read by MGC's admin page
- pbf/          the Geofabrik extracts of a running build (gone afterwards:
                Germany alone is 4.6 GB, and each build loads them fresh anyway)
- build/        the merged extract of a build with several regions
- graphs/<dir>  one graph per build; current.txt names the one being served
- places.json   the cities, towns, villages and suburbs of the regions (OSM
                place nodes): MGC names suggested routes with them
                ("Starnberg via Percha") without asking anyone outside
- elevation/    GraphHopper's elevation tiles

A build is due when the wanted regions differ from the built ones, when MGC
asks for one (`rebuild` changed) or - at night only - when the graph is
REFRESH_DAYS old (fresh OSM data). It downloads, merges (osmium) and imports
into a new graph directory while the old graph keeps serving, then restarts
the server on the new one - about a minute without routing. Merge and import
run with low CPU priority: a Germany import keeps all cores busy for half an
hour, and the live requests must still come first. The import keeps the
graph in memory-mapped files (IMPORT_DATAACCESS, MMAP) instead of the Java
heap, so it needs far less memory next to the serving graph (measured
2026-10-30: Germany in the heap peaked at ~18 GB). A failed build leaves the old graph
serving; it is tried again after RETRY_HOURS or as soon as the wish changes.
Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(os.environ.get("ROUTING_DATA", "/data"))
APP = Path(os.environ.get("ROUTING_APP", "/app"))
SERVE_HEAP = os.environ.get("ROUTING_SERVE_HEAP", "6g")
IMPORT_HEAP = os.environ.get("ROUTING_IMPORT_HEAP", "8g")
IMPORT_DATAACCESS = os.environ.get("ROUTING_IMPORT_DATAACCESS", "MMAP")
REFRESH = timedelta(days=float(os.environ.get("ROUTING_REFRESH_DAYS", "30")))
RETRY = timedelta(hours=float(os.environ.get("ROUTING_RETRY_HOURS", "6")))
NIGHT = range(1, 5)            # local hours in which the monthly refresh may start
NICE = ["nice", "-n", "15"]
PLACE_KINDS = ("city", "town", "village", "suburb")
SOURCE = "https://download.geofabrik.de/"
HEALTH = "http://127.0.0.1:8989/health"
ROUTE = "http://127.0.0.1:8989/route"
WARM_PLACES, WARM_PROFILES = 3, ("bike", "foot")
TICK_S = 30
DOWNLOAD_TRIES, DOWNLOAD_PAUSE_S = 3, 30   # Geofabrik answers 502 now and then
START_TIMEOUT_S = 900

_children: list[subprocess.Popen] = []


def log(text: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} run.py - {text}", flush=True)


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def file_name(region_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", region_id)


def wanted() -> tuple[list[dict], str]:
    """The regions MGC wants (only Geofabrik extracts), and its rebuild token."""
    w = read_json(DATA / "regions.json", {})
    regions = [r for r in w.get("regions", []) if isinstance(r, dict)
               and r.get("id") and str(r.get("pbf", "")).startswith(SOURCE)]
    return sorted(regions, key=lambda r: r["id"]), str(w.get("rebuild", ""))


def due(status: dict, ids: list[str], rebuild: str, t: datetime,
        hour: int | None = None) -> str | None:
    """Why a build is due now: "regions" | "asked" | "refresh" - or None.
    `hour`: the local hour (default: of `t`), for the refresh at night."""
    if not ids:
        return None
    failed = parse(status.get("failed_at"))
    if (failed and status.get("attempt_ids") == ids and status.get("attempt_rebuild") == rebuild
            and t - failed < RETRY):
        return None                          # the same wish failed a moment ago
    if status.get("regions") != ids:
        return "regions"
    if rebuild and rebuild != status.get("rebuild_done", ""):
        return "asked"
    built = parse(status.get("built_at"))
    if built is None:
        return "refresh"
    if t - built >= REFRESH and (t.astimezone().hour if hour is None else hour) in NIGHT:
        return "refresh"
    return None


def state(status: dict) -> str:
    """building | serving | failed | empty - for MGC and the health check."""
    if status.get("building"):
        return "building"
    if status.get("serving"):
        return "serving"
    return "failed" if status.get("error") else "empty"


class Status(dict):
    def save(self) -> None:
        self["state"] = state(self)
        self["updated_at"] = iso(now())
        write_json(DATA / "status.json", dict(self))

    def step(self, text: str) -> None:
        log(text)
        self["building"]["step"] = text
        self.save()


# ---------- downloading and merging ----------

def _get(url: str, timeout: int = 60, method: str = "GET"):
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "MyGPXContainer-routing"})
    return urllib.request.urlopen(req, timeout=timeout)


def _again(what: str, fn):
    """fn() - tried again after a pause when the server failed only for a
    moment (5xx, 429, a broken connection); a 404 is final."""
    for attempt in range(1, DOWNLOAD_TRIES + 1):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or attempt == DOWNLOAD_TRIES:
                raise
            problem = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == DOWNLOAD_TRIES:
                raise
            problem = e
        log(f"{what}: {problem} - again in {DOWNLOAD_PAUSE_S * attempt} s")
        time.sleep(DOWNLOAD_PAUSE_S * attempt)


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(region: dict) -> Path:
    """The region's extract, checked against Geofabrik's md5. Big extracts
    (Germany) redirect to a mirror, which has the md5 next to the file - so
    the md5 is taken from where the redirect ends."""
    dest = DATA / "pbf" / f"{file_name(region['id'])}.osm.pbf"
    tmp = dest.with_name(dest.name + ".part")

    def where() -> str:
        with _get(region["pbf"], method="HEAD") as r:
            return r.geturl()

    def md5(url: str) -> str:
        with _get(url + ".md5") as r:
            return r.read().decode().split()[0]

    def load(url: str) -> None:
        with _get(url, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)

    url = _again(region["id"], where)
    remote = _again(region["id"], lambda: md5(url))
    _again(region["id"], lambda: load(url))
    if md5_of(tmp) != remote:
        tmp.unlink()
        raise RuntimeError(f"{region['id']}: download damaged (md5)")
    tmp.replace(dest)
    return dest


def run(what: str, cmd: list) -> None:
    proc = subprocess.Popen([str(c) for c in cmd])
    _children.append(proc)
    try:
        if proc.wait() != 0:
            raise RuntimeError(f"{what} failed (exit {proc.returncode})")
    finally:
        _children.remove(proc)


def merge(files: list[Path]) -> Path:
    if len(files) == 1:
        return files[0]
    out = DATA / "build" / "merged.osm.pbf"
    run("merge", [*NICE, "osmium", "merge", *files, "-o", out, "--overwrite"])
    return out


def import_graph(pbf: Path) -> Path:
    graph = DATA / "graphs" / f"g-{now():%Y%m%d-%H%M%S}"
    run("import", [*NICE, "java", f"-Xmx{IMPORT_HEAP}", f"-Ddw.graphhopper.datareader.file={pbf}",
                   f"-Ddw.graphhopper.graph.location={graph}",
                   f"-Ddw.graphhopper.graph.dataaccess.default_type={IMPORT_DATAACCESS}",
                   "-jar", APP / "graphhopper.jar", "import", APP / "config.yml"])
    if not (graph / "properties").exists():
        raise RuntimeError("import left no graph")
    return graph


def cleanup() -> None:
    """The extracts and the merged file are only needed while building."""
    for d in ("pbf", "build"):
        for f in (DATA / d).iterdir():
            if f.is_file():
                f.unlink()


def parse_places(lines) -> list[list]:
    """[lat, lon, kind, name] from osmium's GeoJSON text sequence of place
    nodes (each line may start with the RFC 8142 record separator)."""
    out = []
    for line in lines:
        line = line.strip().lstrip("\x1e")
        try:
            feature = json.loads(line) if line else None
        except ValueError:
            feature = None
        if not isinstance(feature, dict):
            continue
        props, geom = feature.get("properties") or {}, feature.get("geometry") or {}
        if geom.get("type") == "Point" and props.get("place") in PLACE_KINDS and props.get("name"):
            lon, lat = geom["coordinates"][:2]
            out.append([round(lat, 5), round(lon, 5), props["place"], props["name"]])
    return out


def extract_places(files: list[Path]) -> Path:
    """build/places.json from the extracts (before they are merged and gone)."""
    places: dict = {}
    for i, f in enumerate(files):
        filtered = DATA / "build" / f"places-{i}.osm.pbf"
        seq = DATA / "build" / f"places-{i}.geojsonseq"
        run("places", [*NICE, "osmium", "tags-filter", f, "n/place=" + ",".join(PLACE_KINDS),
                       "-o", filtered, "--overwrite"])
        run("places", [*NICE, "osmium", "export", filtered, "-f", "geojsonseq", "-o", seq,
                       "--overwrite", "--geometry-types=point"])
        with open(seq) as fh:
            for p in parse_places(fh):
                places[(p[3], p[0], p[1])] = p          # extracts may overlap
    out = DATA / "build" / "places.json"
    write_json(out, {"places": list(places.values())})
    return out


def places_due(status: dict, ids: list[str], t: datetime) -> bool:
    """A graph from before the place list (v0.14.0) gets one without a new
    import - unless that failed a moment ago."""
    if (DATA / "places.json").exists() or not status.get("serving") or status.get("regions") != ids:
        return False
    failed = parse(status.get("places_failed_at"))
    return failed is None or t - failed >= RETRY


def places_only(status: "Status", regions: list[dict]) -> None:
    ids = [r["id"] for r in regions]
    status.update(building={"why": "places", "regions": ids, "since": iso(now()), "step": ""})
    try:
        files = []
        for r in regions:
            status.step(f"downloading {r.get('name') or r['id']}")
            files.append(download(r))
        status.step("places")
        extract_places(files).replace(DATA / "places.json")
        status.update(places_failed_at=None,
                      places=len(read_json(DATA / "places.json", {}).get("places", [])))
        log(f"places of {', '.join(ids)}: {status['places']}")
    except Exception as e:             # noqa: BLE001 - the routing goes on without names
        log(f"places failed: {e}")
        status["places_failed_at"] = iso(now())
    finally:
        cleanup()
        status["building"] = None
        status.save()


def size_mb(path: Path) -> int:
    return round(sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6)


# ---------- the server ----------

class Server:
    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, graph: Path) -> None:
        log(f"server on {graph.name}")
        # the whole heap from the start: a heap still growing under the first
        # requests made them take 30 s instead of 1 (live, 2026-10-30)
        self.proc = subprocess.Popen(
            ["java", f"-Xms{SERVE_HEAP}", f"-Xmx{SERVE_HEAP}",
             f"-Ddw.graphhopper.graph.location={graph}",
             "-jar", str(APP / "graphhopper.jar"), "server", str(APP / "config.yml")])
        _children.append(self.proc)
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if not self.alive():
                raise RuntimeError(f"server on {graph.name} stopped (exit {self.proc.returncode})")
            try:
                with _get(HEALTH, timeout=5) as r:
                    if r.status == 200:
                        warm_up()
                        return
            except OSError:
                pass
            time.sleep(2)
        self.stop()
        raise RuntimeError(f"server on {graph.name} did not come up")

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.proc in _children:
            _children.remove(self.proc)
        self.proc = None


def warm_up() -> None:
    """A few round trips right after the start, from towns of the place list:
    a cold server answered MGC's twelve requests at once in 30 s instead of 1
    (live, 2026-10-30). Failures don't matter."""
    towns = [p for p in read_json(DATA / "places.json", {}).get("places", []) if p[2] == "city"]
    t0, done = time.monotonic(), 0
    for p in towns[:WARM_PLACES]:
        for profile in WARM_PROFILES:
            body = {"profile": profile, "points": [[p[1], p[0]]], "algorithm": "round_trip",
                    "round_trip.distance": 20000, "ch.disable": True, "elevation": True,
                    "points_encoded": False, "instructions": False}
            req = urllib.request.Request(ROUTE, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=120).close()
                done += 1
            except OSError:
                pass
    if towns:
        log(f"warmed up: {done} round trips in {time.monotonic() - t0:.0f} s")


def current_graph() -> Path | None:
    name = (DATA / "current.txt").read_text().strip() if (DATA / "current.txt").exists() else ""
    graph = DATA / "graphs" / name if name else None
    return graph if graph and (graph / "properties").exists() else None


def build(status: Status, server: Server, regions: list[dict], rebuild: str, why: str) -> None:
    ids = [r["id"] for r in regions]
    started, t0 = now(), time.monotonic()
    status.update(building={"why": why, "regions": ids, "since": iso(started), "step": ""},
                  attempt_ids=ids, attempt_rebuild=rebuild)
    old = current_graph()
    try:
        files = []
        for r in regions:
            status.step(f"downloading {r.get('name') or r['id']}")
            files.append(download(r))
        status.step("places")
        places = extract_places(files)
        if len(files) > 1:
            status.step("merging")
        pbf = merge(files)
        status.step("importing")
        graph = import_graph(pbf)
        status.step("switching")
        server.stop()
        (DATA / "current.txt").write_text(graph.name)
        places.replace(DATA / "places.json")             # the new towns for warming up
        server.start(graph)
        for d in (DATA / "graphs").iterdir():           # older builds
            if d.is_dir() and d != graph:
                shutil.rmtree(d, ignore_errors=True)
        cleanup()
        status.update(places=len(read_json(DATA / "places.json", {}).get("places", [])),
                      places_failed_at=None)
        status.update(regions=ids, names=[r.get("name") or r["id"] for r in regions],
                      built_at=iso(now()), build_seconds=round(time.monotonic() - t0),
                      graph_mb=size_mb(graph), rebuild_done=rebuild, error="", failed_at=None,
                      serving=True)
        log(f"built {', '.join(ids)} in {status['build_seconds']} s")
    except Exception as e:             # noqa: BLE001 - every failure ends up in status.json
        log(f"build failed: {e}")
        status.update(error=str(e)[:500], failed_at=iso(now()))
        if not server.alive() and old is not None:
            (DATA / "current.txt").write_text(old.name)
            try:
                server.start(old)
            except RuntimeError as e2:
                log(str(e2))
        status["serving"] = server.alive()
        cleanup()
        keep = current_graph()           # only after switching back: never the old one
        for d in (DATA / "graphs").iterdir():           # a half import
            if d.is_dir() and d != keep:
                shutil.rmtree(d, ignore_errors=True)
    finally:
        status["building"] = None
        status.save()


def _stop(signum, frame) -> None:
    for p in list(_children):
        if p.poll() is None:
            p.terminate()
    for p in list(_children):
        try:
            p.wait(60)
        except subprocess.TimeoutExpired:
            p.kill()
    sys.exit(0)


def main() -> None:
    for d in ("pbf", "build", "graphs", "elevation"):
        (DATA / d).mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    status = Status(read_json(DATA / "status.json", {}))
    status.update(building=None, serving=False)
    status.pop("places_failed_at", None)       # a restart tries the place list at once
    server = Server()
    graph = current_graph()
    if graph is not None:
        try:
            server.start(graph)
        except RuntimeError as e:
            status["error"] = str(e)
    status["serving"] = server.alive()
    status.save()
    while True:
        regions, rebuild = wanted()
        why = due(status, [r["id"] for r in regions], rebuild, now())
        if why:
            log(f"build ({why}): {', '.join(r['id'] for r in regions)}")
            build(status, server, regions, rebuild, why)
        elif places_due(status, [r["id"] for r in regions], now()):
            log(f"places only: {', '.join(r['id'] for r in regions)}")
            places_only(status, regions)
        elif status.get("serving") and not server.alive():
            log("server stopped - starting it again")
            graph = current_graph()
            try:
                if graph is None:
                    raise RuntimeError("no graph")
                server.start(graph)
            except RuntimeError as e:
                status["error"] = str(e)
            status["serving"] = server.alive()
            status.save()
        time.sleep(TICK_S)


if __name__ == "__main__":
    main()
