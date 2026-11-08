#!/usr/bin/env python3
"""Build the NorthTak map layers.

    python3 -I pipeline/build.py --out dist [--previous prev_dir] [--only wildfires,...]
                                 [--include-unconfirmed]

--previous points at the last published output (the `data` branch checkout). When a
source fails, its previous KMZ is kept so a flaky API never wipes a layer, and the
manifest records the error. Unchanged layers keep their old `changed_at`, so a run
with no new data produces a byte-identical tree (and the workflow skips the push).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import traceback
from datetime import datetime, timezone
from functools import partial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kml  # noqa: E402
import layers  # noqa: E402
import net  # noqa: E402

# id, published path (folder shows up in the plugin's Browse view), builder, licence confirmed
LAYERS = [
    ("wildfires", "Alberta/Alberta Wildfires.kmz",
     partial(layers.build_alberta_wildfires, arcgis=net.arcgis_query_all), True),
    ("perimeters", "Alberta/Satellite Fire Perimeters - Alberta Region.kmz", layers.build_cwfis_perimeters, True),
    ("weather", "Alberta/Weather Alerts - Alberta Region.kmz", layers.build_weather_alerts, True),
    ("earthquakes", "Alberta/Earthquakes - Alberta Region.kmz", layers.build_earthquakes, True),
    ("hospitals", "Alberta/Health Facilities - Alberta.kmz", layers.build_hospitals, True),
    ("ab511", "Alberta/Alberta 511 Road Events.kmz",
     partial(layers.build_alberta_511, arcgis=net.arcgis_query_all), False),
]


def icon_set():
    icons = {}
    for status, color in list(layers.AB_FIRE_COLORS.items()) + [("Other", "#757575")]:
        icons[f"fire_{layers._slug(status)}.png"] = kml.circle_icon(color)
    for i, color in enumerate(["#d50000", "#ff6d00", "#fdd835", "#9ccc65"]):
        icons[f"eq_{i}.png"] = kml.circle_icon(color)
    icons["eq_blast.png"] = kml.circle_icon("#9e9e9e")
    icons["hospital.png"] = kml.cross_icon("#d32f2f")
    icons["health.png"] = kml.cross_icon("#1565c0")
    icons["road.png"] = kml.circle_icon("#ff8f00")
    return icons


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--previous")
    ap.add_argument("--only", help="comma-separated layer ids")
    ap.add_argument("--include-unconfirmed", action="store_true",
                    help="also build layers whose reuse licence is not confirmed (private use only)")
    a = ap.parse_args(argv)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    os.makedirs(a.out, exist_ok=True)
    prev_manifest = {}
    if a.previous and os.path.isfile(os.path.join(a.previous, "manifest.json")):
        with open(os.path.join(a.previous, "manifest.json")) as f:
            prev_manifest = {l["id"]: l for l in json.load(f).get("layers", [])}

    icons = icon_set()
    only = set(a.only.split(",")) if a.only else None
    results, failures = [], 0
    for lid, rel, builder, confirmed in LAYERS:
        if only and lid not in only:
            continue
        if not confirmed and not a.include_unconfirmed:
            continue
        dest = os.path.join(a.out, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        prev = prev_manifest.get(lid, {})
        entry = {"id": lid, "path": rel, "licence_confirmed": confirmed}
        try:
            doc = builder(net.get_json, net.get, now)
            kml.write_kmz(dest, doc, icons)
            digest = sha256(dest)
            entry.update(features=doc.count(), sha256=digest, status="ok",
                         changed_at=prev.get("changed_at") if prev.get("sha256") == digest else now.isoformat())
            print(f"[ok]   {lid:12s} {doc.count():5d} features  {rel}")
        except Exception as e:  # keep the last good file
            failures += 1
            traceback.print_exc()
            old = os.path.join(a.previous, rel) if a.previous else None
            if old and os.path.isfile(old) and os.path.abspath(old) != os.path.abspath(dest):
                shutil.copy2(old, dest)
            entry.update({k: prev.get(k) for k in ("features", "sha256", "changed_at")})
            entry.update(status="stale" if old and os.path.isfile(dest) else "missing", error=str(e)[:300])
            print(f"[FAIL] {lid:12s} {e}", file=sys.stderr)
        results.append(entry)

    # Error text and status only change when something actually changes, so the
    # manifest stays stable across quiet runs.
    manifest = {"name": "NorthTak Maps", "region": "Alberta", "layers": results,
                "attribution": "See ATTRIBUTION.md"}
    with open(os.path.join(a.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return 1 if failures == len(results) and results else 0


if __name__ == "__main__":
    sys.exit(main())
