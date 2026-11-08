# NorthTak Maps – data branch

KMZ overlays for ATAK (and Google Earth), rebuilt every hour from Canadian
open data. Everything here is generated; edit the pipeline on `main`, not this branch.

| File | What it shows |
|---|---|
| `Alberta/Alberta Wildfires.kmz` | Active Alberta Wildfire incidents, municipal wildfires, mapped perimeters (colour = status) |
| `Alberta/Satellite Fire Perimeters - Alberta Region.kmz` | NRCan satellite-hotspot fire extents in and around Alberta (colour = days since last hotspot) |
| `Alberta/Weather Alerts - Alberta Region.kmz` | Current ECCC warnings, watches, advisories and statements (full alert text in each shape) |
| `Alberta/Earthquakes - Alberta Region.kmz` | Last 30 days of Earthquakes Canada events, blasts/industry-related split out |
| `Alberta/Health Facilities - Alberta.kmz` | StatCan ODHF hospitals and health facilities (2020 data) |

`manifest.json` lists each layer's feature count, hash, last change time and any
fetch error (a failed fetch keeps the previous file and marks it `stale`).

**Use in ATAK without the plugin:** download a KMZ to the device and open it with
Import Manager, or add it as a KML network link to the file's raw URL.

Not official. Data may be delayed or wrong; confirm with the official source.
Sources and licences: [ATTRIBUTION.md](ATTRIBUTION.md).
