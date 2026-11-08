# NorthTak Maps

Canadian (Alberta-first) open data turned into ATAK-ready KMZ overlays. This
repository is the data side of **NorthTak**; the ATAK plugin that browses and
installs these layers on the device is a separate project.

- `main` – the pipeline (Python standard library only, no installs)
- `data` – the generated layers, one force-pushed commit, rebuilt hourly by
  GitHub Actions ([what's in it](docs/DATA_README.md))

## Layers

Alberta Wildfires · Satellite Fire Perimeters · Weather Alerts · Earthquakes ·
Health Facilities. Sources and licences: [ATTRIBUTION.md](ATTRIBUTION.md).

## Run locally

```sh
python3 -I -m unittest discover -s tests          # offline tests
python3 -I pipeline/build.py --out dist           # build every confirmed layer
python3 -I pipeline/build.py --out dist --only wildfires,weather
python3 -I pipeline/build.py --out dist --include-unconfirmed   # + Alberta 511 (private use only)
```

Requires Python 3.9+. Output is deterministic: an unchanged source produces a
byte-identical KMZ, so the plugin only offers real updates.

## Adding a layer

Write a `build_<name>(fetch_json, fetch_bytes, now)` function in
`pipeline/layers.py` that returns a `kml.Document`, register it in `LAYERS` in
`pipeline/build.py`, confirm the source's licence allows redistribution, and add
it to `ATTRIBUTION.md`. Set the `licence confirmed` flag to `False` until it is.

## Licence

Pipeline code: GPL-3.0-or-later (see `LICENSE`). Generated data keeps the
licence of its source (see `ATTRIBUTION.md`).

Not official. Not for navigation or life-safety decisions on its own.
