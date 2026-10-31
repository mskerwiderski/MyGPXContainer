import pytest

from app import gpx

GPX11 = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">
<metadata><name>Lake loop</name><desc>Nice and flat</desc></metadata>
<trk><name>ignored</name><trkseg>
<trkpt lat="48.0000" lon="11.0000"><ele>500</ele></trkpt>
<trkpt lat="0" lon="0"><ele>0</ele></trkpt>
<trkpt lat="48.0100" lon="11.0000"><ele>510</ele></trkpt>
</trkseg><trkseg>
<trkpt lat="48.0100" lon="11.0100"><ele>505</ele></trkpt>
<trkpt lat="48.0005" lon="11.0005"><ele>501</ele></trkpt>
</trkseg></trk></gpx>"""

GPX10_ROUTE = b"""<?xml version="1.0"?>
<gpx version="1.0" xmlns="http://www.topografix.com/GPX/1/0">
<rte><name>A to B</name>
<rtept lat="47.5" lon="10.5"/><rtept lat="47.6" lon="10.6"/>
</rte></gpx>"""


def test_parse_gpx11_joins_segments_and_drops_null_island():
    t = gpx.parse(GPX11)
    assert t.name == "Lake loop" and t.description == "Nice and flat"
    assert len(t.points) == 4
    assert (0.0, 0.0, 0.0) not in t.points


def test_route_points_when_no_track():
    t = gpx.parse(GPX10_ROUTE)
    assert t.name == "A to B" and len(t.points) == 2 and t.points[0][2] is None


def test_stats():
    st = gpx.stats(gpx.parse(GPX11))
    assert st["loop"] is True
    assert st["ascent_m"] == 10 and st["descent_m"] == 9
    assert (st["min_ele"], st["max_ele"]) == (500, 510)
    assert 2500 < st["distance_m"] < 3500
    assert st["point_count"] == 4


def test_stats_without_elevation():
    st = gpx.stats(gpx.parse(GPX10_ROUTE))
    assert st["ascent_m"] is None and st["min_ele"] is None and st["loop"] is False


@pytest.mark.parametrize("data", [
    b"not xml at all",
    b"<kml></kml>",
    b"<gpx><trk><trkseg><trkpt lat='1' lon='1'/></trkseg></trk></gpx>",
    b"<gpx><trk><trkseg><trkpt lat='x' lon='1'/><trkpt lat='95' lon='1'/></trkseg></trk></gpx>",
])
def test_invalid_files(data):
    with pytest.raises(gpx.GpxError):
        gpx.parse(data)


def test_entities_are_refused():
    bomb = (b'<?xml version="1.0"?><!DOCTYPE gpx [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><gpx><metadata><name>&b;</name>'
            b'</metadata></gpx>')
    with pytest.raises(gpx.GpxError):
        gpx.parse(bomb)


def test_too_large():
    with pytest.raises(gpx.GpxError):
        gpx.parse(b" " * (gpx.MAX_BYTES + 1))


def test_display_thins_out():
    pts = [(48 + i * 1e-4, 11.0, 500.0 + i % 7) for i in range(5000)]
    d = gpx.display(gpx.Track(points=pts), map_points=300, profile_points=100)
    assert len(d["line"]) == 300 and d["line"][0] == [48.0, 11.0]
    assert len(d["profile"]["km"]) == 100 == len(d["profile"]["lat"])


def test_sketch_keeps_north_up_and_fits_the_box():
    pts = [(48.0, 11.0, None), (48.01, 11.0, None), (48.01, 11.02, None)]
    sk = gpx.sketch(gpx.Track(points=pts))
    coords = [tuple(map(float, c.split())) for c in sk["d"][1:].split(" L")]
    assert all(8 <= v <= 92 for xy in coords for v in xy)
    assert coords[1][1] < coords[0][1]          # north is up
    assert coords[2][0] > coords[1][0]          # east is right
    assert (sk["x"], sk["y"]) == coords[0]
