"""Offline tests: python3 -I -m unittest discover -s tests  (run from repo root)."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))

import build  # noqa: E402
import kml  # noqa: E402
import layers  # noqa: E402

NOW = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def no_net(*a, **k):
    raise AssertionError("network used in test")


def fake_arcgis(by_layer):
    def arcgis(url, fetch=None):
        return by_layer[url.rsplit("/", 1)[1]]
    return arcgis


def pt(lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def read(path, mode="rb"):
    with open(path, mode) as f:
        return f.read()


def doc_xml(doc):
    return ET.fromstring(doc.kml().encode("utf-8"))


class KmlTest(unittest.TestCase):
    def test_color_is_aabbggrr(self):
        self.assertEqual(kml.kml_color("#112233", 0x80), "80332211")

    def test_polygon_with_hole_and_multipolygon(self):
        ring = [[0, 0], [1, 0], [1, 1], [0, 0]]
        g = kml.geometry_kml({"type": "Polygon", "coordinates": [ring, ring]})
        self.assertIn("outerBoundaryIs", g)
        self.assertIn("innerBoundaryIs", g)
        m = kml.geometry_kml({"type": "MultiPolygon", "coordinates": [[ring], [ring]]})
        self.assertEqual(m.count("<Polygon>"), 2)

    def test_kmz_is_deterministic(self):
        d = kml.Document("t", "x")
        sid = d.style(kml.Style("s", icon="a.png"))
        d.add("f", kml.Placemark("p <&>", {"type": "Point", "coordinates": [-113.123456789, 53.5]}, sid))
        icons = {"a.png": kml.circle_icon("#ff0000")}
        with tempfile.TemporaryDirectory() as t:
            a, b = os.path.join(t, "a.kmz"), os.path.join(t, "b.kmz")
            kml.write_kmz(a, d, icons)
            kml.write_kmz(b, d, icons)
            self.assertEqual(read(a), read(b))
            with zipfile.ZipFile(a) as z:
                self.assertEqual(z.namelist()[0], "doc.kml")
                body = z.read("doc.kml")
            ET.fromstring(body)  # escaping produced valid XML
            self.assertIn(b"-113.12346,53.5", body)


class LayerTest(unittest.TestCase):
    def test_wildfires_drop_finished_fires(self):
        arc = fake_arcgis({
            "0": [pt(-115, 55, LABEL="SWF-1", FIRE_STATUS="Out of Control"),
                  pt(-115, 56, LABEL="SWF-2", FIRE_STATUS="Extinguished"),
                  pt(-115, 57, LABEL="SWF-3", FIRE_STATUS="Assistance Ended")],
            "2": [pt(-114, 51, MRFireNumber="M-1", FireIncidentStatus="Active"),
                  pt(-114, 52, MRFireNumber="M-2", FireIncidentStatus="Extinguished")],
            "1": [],
        })
        doc = layers.build_alberta_wildfires(no_net, no_net, NOW, arcgis=arc)
        names = [p.find("{http://www.opengis.net/kml/2.2}name").text
                 for p in doc_xml(doc).iter("{http://www.opengis.net/kml/2.2}Placemark")]
        self.assertEqual(sorted(names), ["M-1 (Active)", "SWF-1 (Out of Control)"])
        self.assertEqual(doc.folder_order, ["Wildfires - Out of Control", "Municipal wildfires - Active"])

    def test_weather_alerts_skip_expired_and_keep_text(self):
        poly = {"type": "Polygon", "coordinates": [[[-114, 51], [-113, 51], [-113, 52], [-114, 51]]]}
        feed = {"features": [
            {"geometry": poly, "properties": {"alert_type": "warning", "risk_colour_en": "yellow",
                                              "alert_short_name_en": "Snowfall", "feature_name_en": "Calgary",
                                              "expiration_datetime": "2026-11-09T00:00:00Z",
                                              "alert_text_en": "15 cm of snow & ice <expected>."}},
            {"geometry": poly, "properties": {"alert_type": "warning", "feature_name_en": "Banff",
                                              "expiration_datetime": "2026-11-08T00:00:00Z"}},
        ]}
        doc = layers.build_weather_alerts(lambda u, p=None: feed, no_net, NOW)
        self.assertEqual(doc.count(), 1)
        k = doc.kml()
        self.assertIn("Snowfall - Calgary", k)
        self.assertIn("15 cm of snow &amp; ice &lt;expected>.", k)

    def test_earthquakes_parse_and_flag_blasts(self):
        text = ("#EventID|Time|Latitude|Longitude|Depth/km|MagType|Magnitude|EventLocationName\n"
                "a|2026-11-05T15:56:06.000Z|54.5|-117.3|3|MLy|3.2|36 km WNW of Fox Creek, AB/fr\n"
                "b|2026-11-04T22:59:36.000Z|52.9|-116.8|0|ML|2.3|Quarry blast, 13 km SSW of Coal Valley Mine, AB/fr\n"
                "c|bad|x|y|0|ML|?|broken\n").encode()
        doc = layers.build_earthquakes(no_net, lambda u, p=None: text, NOW)
        self.assertEqual(doc.folder_order, ["M3-3.9", "Blasts / industry-related"])


class BuildTest(unittest.TestCase):
    def test_failed_source_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as t:
            prev, out = os.path.join(t, "prev"), os.path.join(t, "out")
            rel = "Alberta/x.kmz"
            os.makedirs(os.path.join(prev, "Alberta"))
            with open(os.path.join(prev, rel), "wb") as f:
                f.write(b"old")
            with open(os.path.join(prev, "manifest.json"), "w") as f:
                json.dump({"layers": [{"id": "x", "sha256": "h", "features": 3, "changed_at": "c"}]}, f)

            def boom(*a):
                raise RuntimeError("server down")

            saved = build.LAYERS
            build.LAYERS = [("x", rel, boom, True)]
            try:
                rc = build.main(["--out", out, "--previous", prev])
            finally:
                build.LAYERS = saved
            self.assertEqual(rc, 1)
            self.assertEqual(read(os.path.join(out, rel)), b"old")
            m = json.loads(read(os.path.join(out, "manifest.json"), "r"))["layers"][0]
            self.assertEqual((m["status"], m["features"], m["changed_at"]), ("stale", 3, "c"))


if __name__ == "__main__":
    unittest.main()
