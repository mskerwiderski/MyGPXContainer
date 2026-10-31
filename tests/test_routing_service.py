"""routing/run.py, the routing container's build loop - without Java, osmium
or the network (download, import and the server are faked)."""

import hashlib
import importlib.util
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

T = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
DE = {"id": "germany", "name": "Germany",
      "pbf": "https://download.geofabrik.de/europe/germany-latest.osm.pbf"}
AT = {"id": "austria", "name": "Austria",
      "pbf": "https://download.geofabrik.de/europe/austria-latest.osm.pbf"}


@pytest.fixture
def rs(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "routing_run", Path(__file__).parent.parent / "routing" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "DATA", tmp_path)
    for d in ("pbf", "build", "graphs", "elevation"):
        (tmp_path / d).mkdir()
    return mod


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_when_a_build_is_due(rs):
    built = {"regions": ["germany"], "built_at": iso(T - timedelta(days=2)), "rebuild_done": "r1"}
    assert rs.due({}, [], "", T) is None                                   # nothing wanted
    assert rs.due({}, ["germany"], "", T) == "regions"                     # first build
    assert rs.due(built, ["germany"], "r1", T) is None
    assert rs.due(built, ["austria", "germany"], "r1", T) == "regions"
    assert rs.due(built, ["germany"], "r2", T) == "asked"                  # admin: rebuild now
    old = {**built, "built_at": iso(T - timedelta(days=31))}
    assert rs.due(old, ["germany"], "r1", T, hour=3) == "refresh"         # fresh OSM data at night
    assert rs.due(old, ["germany"], "r1", T, hour=14) is None              # not in the day
    failed = {**built, "failed_at": iso(T - timedelta(hours=1)),
              "attempt_ids": ["austria", "germany"], "attempt_rebuild": "r1"}
    assert rs.due(failed, ["austria", "germany"], "r1", T) is None         # not again at once
    assert rs.due(failed, ["austria", "germany"], "r1", T + timedelta(hours=6)) == "regions"
    assert rs.due(failed, ["germany", "italy"], "r1", T) == "regions"      # the wish changed


def test_wanted_takes_only_geofabrik_extracts(rs):
    (rs.DATA / "regions.json").write_text(json.dumps({"regions": [
        DE, AT, {"id": "evil", "pbf": "https://example.org/x.pbf"}, {"pbf": DE["pbf"]}],
        "rebuild": "x"}))
    regions, rebuild = rs.wanted()
    assert [r["id"] for r in regions] == ["austria", "germany"] and rebuild == "x"
    (rs.DATA / "regions.json").write_text("not json")
    assert rs.wanted() == ([], "")


def test_state(rs):
    assert rs.state({"building": {"step": "importing"}, "serving": True}) == "building"
    assert rs.state({"serving": True, "error": "old trouble"}) == "serving"
    assert rs.state({"error": "boom"}) == "failed"
    assert rs.state({}) == "empty"


class Answer(io.BytesIO):
    def __init__(self, data=b"", url=""):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


MIRROR = "https://ftp5.gwdg.de/pub/misc/openstreetmap/download.geofabrik.de/germany-latest.osm.pbf"


def fake_geofabrik(monkeypatch, rs, data: bytes, md5: str | None = None):
    """Like Geofabrik for big extracts: the file redirects to a mirror, the md5
    is only there."""
    calls = []

    def get(url, timeout=60, method="GET"):
        calls.append((method, url))
        if method == "HEAD":
            return Answer(url=MIRROR)
        assert url.startswith("https://ftp5.gwdg.de/")
        if url.endswith(".md5"):
            return Answer(f"{md5 or hashlib.md5(data).hexdigest()}  x.osm.pbf\n".encode())
        return Answer(data)
    monkeypatch.setattr(rs, "_get", get)
    return calls


def test_download_from_the_mirror_checks_md5(rs, monkeypatch):
    calls = fake_geofabrik(monkeypatch, rs, b"pbf-1")
    path = rs.download(DE)
    assert path.read_bytes() == b"pbf-1"
    assert calls == [("HEAD", DE["pbf"]), ("GET", MIRROR + ".md5"), ("GET", MIRROR)]
    fake_geofabrik(monkeypatch, rs, b"pbf-2", md5="0" * 32)
    with pytest.raises(RuntimeError, match="md5"):
        rs.download(DE)
    assert path.read_bytes() == b"pbf-1"         # a damaged one never replaces it
    assert not list((rs.DATA / "pbf").glob("*.part"))


class FakeServer:
    def __init__(self, fail_on=()):
        self.graph, self.fail_on, self.started = None, set(fail_on), []

    def alive(self):
        return self.graph is not None

    def start(self, graph):
        self.started.append(graph.name)
        if graph.name in self.fail_on:
            raise RuntimeError("did not come up")
        self.graph = graph

    def stop(self):
        self.graph = None


def graph_dir(rs, name):
    d = rs.DATA / "graphs" / name
    d.mkdir()
    (d / "properties").write_text("x")
    return d


def fake_places(rs, monkeypatch, places=([48.17, 11.35, "town", "Starnberg"],)):
    def extract(files):
        out = rs.DATA / "build" / "places.json"
        out.write_text(json.dumps({"places": list(places)}))
        return out
    monkeypatch.setattr(rs, "extract_places", extract)


def test_build_switches_to_the_new_graph_and_cleans_up(rs, monkeypatch):
    old = graph_dir(rs, "g-old")
    (rs.DATA / "current.txt").write_text("g-old")
    (rs.DATA / "pbf" / "france.osm.pbf").write_text("gone soon")
    merged = []
    monkeypatch.setattr(rs, "download", lambda r: rs.DATA / "pbf" / f"{r['id']}.osm.pbf")
    monkeypatch.setattr(rs, "merge", lambda files: merged.append(files) or files[0])
    monkeypatch.setattr(rs, "import_graph", lambda pbf: graph_dir(rs, "g-new"))
    fake_places(rs, monkeypatch)
    server = FakeServer()
    server.start(old)
    status = rs.Status()
    rs.build(status, server, [AT, DE], "r1", "regions")
    assert server.graph.name == "g-new" and (rs.DATA / "current.txt").read_text() == "g-new"
    assert not old.exists() and not list((rs.DATA / "pbf").iterdir())   # extracts gone
    assert len(merged[0]) == 2
    saved = json.loads((rs.DATA / "status.json").read_text())
    assert saved["state"] == "serving" and saved["regions"] == ["austria", "germany"]
    assert saved["names"] == ["Austria", "Germany"] and saved["rebuild_done"] == "r1"
    assert saved["building"] is None and saved["error"] == "" and saved["places"] == 1
    assert json.loads((rs.DATA / "places.json").read_text())["places"][0][3] == "Starnberg"


def test_a_failed_build_keeps_the_old_graph(rs, monkeypatch):
    old = graph_dir(rs, "g-old")
    (rs.DATA / "current.txt").write_text("g-old")
    monkeypatch.setattr(rs, "download", lambda r: rs.DATA / "pbf" / "x.osm.pbf")
    monkeypatch.setattr(rs, "merge", lambda files: files[0])
    monkeypatch.setattr(rs, "import_graph", lambda pbf: graph_dir(rs, "g-new"))
    fake_places(rs, monkeypatch)
    server = FakeServer(fail_on={"g-new"})       # the new graph does not start
    server.start(old)
    status = rs.Status(regions=["germany"], built_at=iso(T))
    rs.build(status, server, [AT, DE], "", "regions")
    assert server.graph.name == "g-old" and (rs.DATA / "current.txt").read_text() == "g-old"
    assert old.exists() and not (rs.DATA / "graphs" / "g-new").exists()  # the half one goes
    saved = json.loads((rs.DATA / "status.json").read_text())
    assert saved["state"] == "serving" and saved["regions"] == ["germany"]
    assert "did not come up" in saved["error"] and saved["attempt_ids"] == ["austria", "germany"]
    assert rs.due(saved, ["austria", "germany"], "", rs.now()) is None    # waits RETRY_HOURS


def test_first_build_failing_leaves_nothing_serving(rs, monkeypatch):
    def broken(region):
        raise RuntimeError("Geofabrik unreachable")
    monkeypatch.setattr(rs, "download", broken)
    status = rs.Status()
    rs.build(status, FakeServer(), [DE], "", "regions")
    saved = json.loads((rs.DATA / "status.json").read_text())
    assert saved["state"] == "failed" and "unreachable" in saved["error"]


# ---------- the place list for naming routes ----------

def test_parse_places_from_osmium(rs):
    lines = [
        '\x1e{"type":"Feature","geometry":{"type":"Point","coordinates":[11.3537,48.1716]},'
        '"properties":{"place":"town","name":"Starnberg"}}',
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.55,48.19]},'
        '"properties":{"place":"suburb","name":"Milbertshofen"}}',
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.0,48.0]},'
        '"properties":{"place":"hamlet","name":"Too small"}}',
        '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.0,48.0]},'
        '"properties":{"place":"village"}}',
        "", "not json"]
    assert rs.parse_places(lines) == [[48.1716, 11.3537, "town", "Starnberg"],
                                      [48.19, 11.55, "suburb", "Milbertshofen"]]


def test_extract_places_merges_overlapping_extracts(rs, monkeypatch):
    feature = ('{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s]},'
               '"properties":{"place":"%s","name":"%s"}}\n')
    data = {0: feature % (11.35, 48.17, "town", "Starnberg") + feature % (8.4, 47.6, "town", "Grenze"),
            1: feature % (8.4, 47.6, "town", "Grenze")}
    calls = []

    def run(what, cmd):
        calls.append(cmd)
        if cmd[4] == "export":                   # nice -n 15 osmium export <file> …
            i = int(str(cmd[5]).rsplit("-", 1)[1].split(".")[0])
            Path(cmd[cmd.index("-o") + 1]).write_text(data[i])
    monkeypatch.setattr(rs, "run", run)
    out = rs.extract_places([Path("a.osm.pbf"), Path("b.osm.pbf")])
    names = sorted(p[3] for p in json.loads(out.read_text())["places"])
    assert names == ["Grenze", "Starnberg"] and len(calls) == 4
    assert calls[0][4:7] == ["tags-filter", Path("a.osm.pbf"), "n/place=city,town,village,suburb"]


def test_places_for_a_graph_built_before_them(rs, monkeypatch):
    serving = {"serving": True, "regions": ["germany"]}
    assert rs.places_due(serving, ["germany"], T)
    assert not rs.places_due({**serving, "serving": False}, ["germany"], T)
    assert not rs.places_due(serving, ["austria", "germany"], T)        # a build comes first
    assert not rs.places_due({**serving, "places_failed_at": iso(T)}, ["germany"], T)
    monkeypatch.setattr(rs, "download", lambda r: rs.DATA / "pbf" / "germany.osm.pbf")
    (rs.DATA / "pbf" / "germany.osm.pbf").write_text("x")
    fake_places(rs, monkeypatch)
    status = rs.Status(serving)
    rs.places_only(status, [DE])
    assert (rs.DATA / "places.json").exists() and not list((rs.DATA / "pbf").iterdir())
    assert status["places"] == 1 and status["building"] is None
    assert not rs.places_due(status, ["germany"], T)


def test_places_failing_does_not_stop_the_routing(rs, monkeypatch):
    def broken(region):
        raise RuntimeError("Geofabrik unreachable")
    monkeypatch.setattr(rs, "download", broken)
    status = rs.Status(serving=True, regions=["germany"])
    rs.places_only(status, [DE])
    saved = json.loads((rs.DATA / "status.json").read_text())
    assert saved["state"] == "serving" and saved["places_failed_at"] and not saved.get("error")


def test_download_tries_again_when_geofabrik_fails_for_a_moment(rs, monkeypatch):
    import urllib.error
    fake_geofabrik(monkeypatch, rs, b"pbf-1")
    real, failures = rs._get, {"n": 0}

    def flaky(url, timeout=60, method="GET"):
        if method == "GET" and not url.endswith(".md5") and failures["n"] < 2:
            failures["n"] += 1
            raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)
        return real(url, timeout, method)
    pauses = []
    monkeypatch.setattr(rs, "_get", flaky)
    monkeypatch.setattr(rs.time, "sleep", pauses.append)
    assert rs.download(DE).read_bytes() == b"pbf-1"
    assert pauses == [30, 60]
    failures["n"] = -10                          # a 404 is final, no waiting
    def gone(url, timeout=60, method="GET"):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    monkeypatch.setattr(rs, "_get", gone)
    with pytest.raises(urllib.error.HTTPError):
        rs.download(DE)
    assert pauses == [30, 60]


def test_warm_up_from_the_towns_of_the_place_list(rs, monkeypatch):
    (rs.DATA / "places.json").write_text(json.dumps({"places": [
        [48.137, 11.575, "city", "München"], [48.17, 11.35, "town", "Starnberg"],
        [51.507, -0.128, "city", "London"]]}))
    asked = []

    def urlopen(req, timeout=60):
        body = json.loads(req.data)
        asked.append((body["profile"], body["points"][0]))
        if body["points"][0][1] == 51.507:
            raise OSError("no route")             # failures don't matter
        return io.BytesIO(b"{}")
    monkeypatch.setattr(rs.urllib.request, "urlopen", urlopen)
    rs.warm_up()
    assert asked == [("bike", [11.575, 48.137]), ("foot", [11.575, 48.137]),
                     ("bike", [-0.128, 51.507]), ("foot", [-0.128, 51.507])]   # cities only
    (rs.DATA / "places.json").unlink()
    rs.warm_up()                                   # no list: nothing to warm up with
    assert len(asked) == 4
