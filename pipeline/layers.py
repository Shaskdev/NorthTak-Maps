"""NorthTak layer builders. Each builder fetches one source and returns a kml.Document.

Every builder takes (fetch_json, fetch_bytes, now) so tests can feed fixtures.
Attribution strings follow each provider's licence requirements; see ATTRIBUTION.md.
"""

import csv
import io
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from kml import Document, Placemark, Style, html_table

LOCAL_TZ = ZoneInfo("America/Edmonton")

# Alberta plus ~1 degree around it, so fires/alerts just over the BC/SK/NWT/MT line show.
REGION = {"west": -121.0, "south": 48.0, "east": -109.0, "north": 61.0}

OGL_CANADA = "https://open.canada.ca/en/open-government-licence-canada"
OGL_ALBERTA = "https://open.alberta.ca/licence"
ECCC_LICENCE = "https://eccc-msc.github.io/open-data/licence/readme_en/"

DISCLAIMER = ("Unofficial overlay built automatically from public open data. "
              "It may be delayed, incomplete or wrong. Always confirm with the official source "
              "and follow instructions from emergency officials.")


def local_time(value):
    """ISO-8601 string or epoch milliseconds -> 'YYYY-MM-DD HH:MM MST' (Alberta time)."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M %Z")
    except (ValueError, OverflowError, OSError):
        return str(value)


def _about(source, licence_name, licence_url, extra=""):
    return (f"<p><b>Source:</b> {source}</p>"
            f"<p><b>Licence:</b> <a href='{licence_url}'>{licence_name}</a></p>"
            f"{extra}<p><i>{DISCLAIMER}</i></p>")


# =================================================================== Alberta wildfires

AB_FIRE_URL = "https://geospatial.alberta.ca/mimas/rest/services/wildfire/alberta_fire_status/MapServer"
AB_FIRE_DONE = {"Extinguished", "Assistance Ended"}
AB_FIRE_COLORS = {
    "Out of Control": "#d50000",
    "Being Held": "#ff8f00",
    "Under Control": "#fdd835",
    "Turned Over": "#8e24aa",
    "Assistance Started": "#1e88e5",
    # municipal layer uses its own statuses: Active / Inactive (not spreading) / Extinguished
    "Active": "#e53935",
    "Inactive": "#fbc02d",
}
AB_FIRE_ORDER = ["Out of Control", "Being Held", "Under Control", "Turned Over", "Assistance Started",
                 "Active", "Inactive"]


def _slug(s):
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in s).strip("_")


def build_alberta_wildfires(fetch_json, fetch_bytes, now, arcgis):
    doc = Document(
        "NorthTak - Alberta Wildfires",
        _about("Alberta Wildfire, Government of Alberta (Alberta Fire Status map service)",
               "Open Government Licence - Alberta", OGL_ALBERTA,
               "<p>Active wildfires in the Forest Protection Area and fires reported by "
               "municipalities. Extinguished and assistance-ended fires are left out. "
               "Official map: <a href='https://www.alberta.ca/wildfire-maps-and-data'>alberta.ca</a></p>"))
    styles = {}
    for status in AB_FIRE_ORDER + ["Other"]:
        color = AB_FIRE_COLORS.get(status, "#757575")
        styles[status] = doc.style(Style(f"fire_{_slug(status)}", icon=f"fire_{_slug(status)}.png",
                                         icon_scale=1.0, line=color, fill=color))
    perim_style = {s: doc.style(Style(f"perim_{_slug(s)}", line=AB_FIRE_COLORS.get(s, "#757575"),
                                      line_width=3, fill=AB_FIRE_COLORS.get(s, "#757575"), fill_alpha=0x40))
                   for s in AB_FIRE_ORDER + ["Other"]}

    def folder_for(status):
        return status if status in AB_FIRE_COLORS else "Other"

    # layer 0: provincial wildfires (Forest Protection Area)
    for f in arcgis(f"{AB_FIRE_URL}/0", fetch=fetch_json):
        p = f["properties"]
        status = p.get("FIRE_STATUS") or "Unknown"
        if status in AB_FIRE_DONE or not f.get("geometry"):
            continue
        name = p.get("LABEL") or p.get("FIRE_NUMBER") or "Wildfire"
        desc = html_table([
            ("Fire", name), ("Status", status), ("Status since", p.get("FIRE_STATUS_DATE")),
            ("Size (ha)", p.get("AREA_ESTIMATE")), ("Size class", p.get("SIZE_CLASS")),
            ("Forest area", p.get("RESP_AREA")), ("Cause", p.get("GENERAL_CAUSE")),
            ("Assessed", local_time(p.get("ASSESSMENT_ASSISTANCE_DATE"))),
            ("Lat, Lon", f"{p.get('LATITUDE')}, {p.get('LONGITUDE')}"),
            ("Source", "Alberta Wildfire"),
        ])
        fo = folder_for(status)
        doc.add(f"Wildfires - {fo}", Placemark(f"{name} ({status})", f["geometry"], styles[fo], desc))

    # layer 2: municipal wildfires reported to the province (different schema)
    for f in arcgis(f"{AB_FIRE_URL}/2", fetch=fetch_json):
        p = f["properties"]
        status = p.get("FireIncidentStatus") or "Unknown"
        if status in AB_FIRE_DONE or not f.get("geometry"):
            continue
        name = p.get("MRFireNumber") or "Municipal wildfire"
        desc = html_table([
            ("Fire", name), ("Status", status), ("Local government", p.get("LocalGovernment")),
            ("Size (ha)", p.get("Hectares")), ("Started (est.)", local_time(p.get("EstimatedStartDate"))),
            ("Mutual aid zone", p.get("MutualAidContactZone")),
            ("Last updated", p.get("GISFeatureLastUpdated_MT")),
            ("Source", "Municipal report to Alberta Forestry and Parks"),
        ])
        fo = folder_for(status)
        doc.add(f"Municipal wildfires - {fo}", Placemark(f"{name} ({status})", f["geometry"], styles[fo], desc))

    # layer 1: mapped perimeters
    for f in arcgis(f"{AB_FIRE_URL}/1", fetch=fetch_json):
        p = f["properties"]
        status = p.get("FIRE_STATUS") or "Unknown"
        if status in AB_FIRE_DONE or not f.get("geometry"):
            continue
        name = p.get("FireNumber") or p.get("IncdtName") or "Perimeter"
        desc = html_table([
            ("Fire", name), ("Incident", p.get("IncdtName")), ("Status", status),
            ("Size (ha)", p.get("AREA_ESTIMATE")), ("Forest area", p.get("RESP_AREA")),
            ("Mapped", local_time(p.get("CaptreDate"))), ("Method", p.get("CreatMethd")),
            ("Source", "Alberta Wildfire"),
        ])
        doc.add("Perimeters", Placemark(f"{name} perimeter", f["geometry"], perim_style[folder_for(status)], desc))

    statuses = AB_FIRE_ORDER + ["Other"]
    order = [f"Wildfires - {s}" for s in statuses] + [f"Municipal wildfires - {s}" for s in statuses] + ["Perimeters"]
    doc.folder_order.sort(key=lambda n: order.index(n) if n in order else 999)
    return doc


# =================================================================== CWFIS perimeters

CWFIS_WFS = [
    "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs",
    "https://geoserver.cwfif.nrcan.gc.ca/geoserver/public/wfs",  # NRCan's newer server
]


def build_cwfis_perimeters(fetch_json, fetch_bytes, now):
    r = REGION
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": "public:m3_polygons_current", "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        # WFS 2.0 with EPSG:4326 URN = lat,lon axis order
        "bbox": f"{r['south']},{r['west']},{r['north']},{r['east']},urn:ogc:def:crs:EPSG::4326",
    }
    data, errors = None, []
    for url in CWFIS_WFS:
        try:
            data = fetch_json(url, params)
            if "features" in data:
                break
        except Exception as e:  # try the next server
            errors.append(f"{url}: {e}")
            data = None
    if data is None or "features" not in data:
        raise RuntimeError("CWFIS perimeters unavailable: " + "; ".join(errors))

    doc = Document(
        "NorthTak - Satellite Fire Perimeters (Alberta region)",
        _about("Canadian Forest Service. Canadian Wildland Fire Information System (CWFIS), "
               "Natural Resources Canada, Canadian Forest Service, Northern Forestry Centre, "
               "Edmonton, Alberta. https://cwfis.cfs.nrcan.gc.ca", "Open Government Licence - Canada",
               OGL_CANADA,
               "<p>Fire extents estimated from satellite hotspots (M3 polygons). These are not "
               "official agency perimeters. Colour shows how recently a hotspot was detected.</p>"))
    bands = [(2, "Hotspot in last 2 days", "#d50000"), (7, "Hotspot in last 7 days", "#ff6d00"),
             (None, "Older (no hotspot in 7 days)", "#9e9e9e")]
    sids = {label: doc.style(Style(f"m3_{i}", line=c, line_width=2, fill=c, fill_alpha=0x40))
            for i, (_, label, c) in enumerate(bands)}
    for f in data["features"]:
        p = f.get("properties", {})
        if not f.get("geometry"):
            continue
        try:
            last = datetime.fromisoformat(p["lastdate"].replace("Z", "+00:00"))
            age = (now - last).total_seconds() / 86400
        except (KeyError, ValueError, AttributeError):
            age = None
        label = bands[-1][1]
        for days, lab, _ in bands[:-1]:
            if age is not None and age <= days:
                label = lab
                break
        area = p.get("area")
        desc = html_table([
            ("Area (ha)", f"{area:,.0f}" if isinstance(area, (int, float)) else area),
            ("First hotspot", local_time(p.get("firstdate"))),
            ("Last hotspot", local_time(p.get("lastdate"))),
            ("Hotspot count", p.get("hcount")),
            ("Source", "NRCan CWFIS (satellite-derived)"),
        ])
        name = f"Satellite fire extent {area:,.0f} ha" if isinstance(area, (int, float)) else "Satellite fire extent"
        doc.add(label, Placemark(name, f["geometry"], sids[label], desc, sort_key=p.get("lastdate", "")))
    return doc


# =================================================================== ECCC weather alerts

ECCC_ALERTS = "https://api.weather.gc.ca/collections/weather-alerts/items"
ALERT_COLORS = {"red": "#d50000", "orange": "#ff6d00", "yellow": "#fdd835"}
ALERT_TYPE_ORDER = ["warning", "watch", "advisory", "statement"]


def build_weather_alerts(fetch_json, fetch_bytes, now):
    r = REGION
    feats, offset = [], 0
    while True:
        d = fetch_json(ECCC_ALERTS, {"f": "json", "limit": 500, "offset": offset,
                                     "bbox": f"{r['west']},{r['south']},{r['east']},{r['north']}"})
        batch = d.get("features", [])
        feats += batch
        if len(batch) < 500:
            break
        offset += len(batch)

    doc = Document(
        "NorthTak - Weather Alerts (Alberta region)",
        _about("Data Source: Environment and Climate Change Canada (MSC GeoMet weather-alerts)",
               "Environment and Climate Change Canada Data Services End-use Licence", ECCC_LICENCE,
               "<p>Alert text is reproduced unaltered as issued. Official alerts: "
               "<a href='https://weather.gc.ca/'>weather.gc.ca</a></p>"))
    sids = {}
    for key, color in list(ALERT_COLORS.items()) + [("none", "#78909c")]:
        sids[key] = doc.style(Style(f"alert_{key}", line=color, line_width=2, fill=color, fill_alpha=0x50))

    for f in feats:
        p = f.get("properties", {})
        if not f.get("geometry"):
            continue
        exp = p.get("expiration_datetime")
        try:
            if exp and datetime.fromisoformat(exp.replace("Z", "+00:00")) < now:
                continue
        except ValueError:
            pass
        if (p.get("status_en") or "").lower() in ("ended", "cancelled"):
            continue
        colour = (p.get("risk_colour_en") or "none").lower()
        colour = colour if colour in ALERT_COLORS else "none"
        atype = (p.get("alert_type") or "other").lower()
        area = p.get("feature_name_en") or ""
        title = p.get("alert_short_name_en") or p.get("alert_name_en") or "Alert"
        name = f"{title} - {area}" if area else title
        desc = html_table([
            ("Alert", (p.get("alert_name_en") or "").title()), ("Area", area),
            ("Province", p.get("province")), ("Colour", p.get("risk_colour_en")),
            ("Status", p.get("status_en")),
            ("Issued", local_time(p.get("publication_datetime"))),
            ("Expires", local_time(exp)),
            ("Impact", p.get("impact_en")), ("Confidence", p.get("confidence_en")),
        ]) + "<hr/>" + (p.get("alert_text_en") or "").replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>")
        folder = atype.capitalize() + "s" if atype in ALERT_TYPE_ORDER else "Other"
        doc.add(folder, Placemark(name, f["geometry"], sids[colour], desc,
                                  sort_key=(ALERT_TYPE_ORDER.index(atype) if atype in ALERT_TYPE_ORDER else 9, area)))
    # stable folder order regardless of feed order
    order = [t.capitalize() + "s" for t in ALERT_TYPE_ORDER] + ["Other"]
    doc.folder_order.sort(key=lambda n: order.index(n) if n in order else 99)
    return doc


# =================================================================== earthquakes

EQ_FDSN = "https://www.earthquakescanada.nrcan.gc.ca/fdsnws/event/1/query"
EQ_DAYS = 30


def build_earthquakes(fetch_json, fetch_bytes, now):
    r = REGION
    start = (now - timedelta(days=EQ_DAYS)).strftime("%Y-%m-%d")
    text = fetch_bytes(EQ_FDSN, {"format": "text", "starttime": start,
                                 "minlatitude": r["south"], "maxlatitude": r["north"],
                                 "minlongitude": r["west"], "maxlongitude": r["east"]}).decode("utf-8")
    doc = Document(
        f"NorthTak - Earthquakes (Alberta region, last {EQ_DAYS} days)",
        _about("Earthquakes Canada, Natural Resources Canada", "Open Government Licence - Canada", OGL_CANADA,
               "<p>Includes events NRCan labels as industry-related or quarry blasts.</p>"))
    classes = [(4.0, "M4+", "#d50000", 1.4), (3.0, "M3-3.9", "#ff6d00", 1.1),
               (2.0, "M2-2.9", "#fdd835", 0.9), (-9, "Under M2", "#9ccc65", 0.7)]
    sids = {lab: doc.style(Style(f"eq_{i}", icon=f"eq_{i}.png", icon_scale=sc, line=c))
            for i, (_, lab, c, sc) in enumerate(classes)}
    blast = doc.style(Style("eq_blast", icon="eq_blast.png", icon_scale=0.7, line="#616161"))
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        cols = line.split("|")
        if len(cols) < 8:
            continue
        ev, t, lat, lon, depth, mtype, mag, place = cols[:8]
        try:
            m = float(mag)
            geom = {"type": "Point", "coordinates": [float(lon), float(lat)]}
        except ValueError:
            continue
        place_en = place.split("/")[0].strip()
        man_made = any(k in place_en.lower() for k in ("blast", "industry-related", "explosion"))
        lab = next(l for th, l, _, _ in classes if m >= th)
        desc = html_table([
            ("Magnitude", f"{m:.1f} {mtype}"), ("Time", local_time(t)), ("Depth (km)", depth),
            ("Location", place_en), ("Event ID", ev),
            ("Details", f"https://www.earthquakescanada.nrcan.gc.ca/stndon/NEDB-BNDS/bulletin-en.php?eventid={ev}"),
        ])
        folder = "Blasts / industry-related" if man_made else lab
        doc.add(folder, Placemark(f"M{m:.1f} {place_en}", geom, blast if man_made else sids[lab], desc,
                                  sort_key=t))
    order = [c[1] for c in classes] + ["Blasts / industry-related"]
    doc.folder_order.sort(key=lambda n: order.index(n))
    return doc


# =================================================================== hospitals

ODHF_ZIP = "https://www150.statcan.gc.ca/n1/pub/13-26-0001/2020001/ODHF.zip"


def build_hospitals(fetch_json, fetch_bytes, now):
    z = zipfile.ZipFile(io.BytesIO(fetch_bytes(ODHF_ZIP)))
    name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    raw = z.read(name)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    doc = Document(
        "NorthTak - Health Facilities (Alberta)",
        _about("Statistics Canada, Open Database of Healthcare Facilities (ODHF) v1.1, 2020",
               "Open Government Licence - Canada", OGL_CANADA,
               "<p>Only facilities with coordinates in the source are shown. The database dates "
               "from 2020: facilities may have opened, closed or changed services since. "
               "Not a list of emergency departments.</p>"))
    sid = doc.style(Style("hosp", icon="hospital.png", icon_scale=0.9))
    sid_other = doc.style(Style("health", icon="health.png", icon_scale=0.7))
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("province") or "").lower() != "ab":
            continue
        try:
            geom = {"type": "Point", "coordinates": [float(row["longitude"]), float(row["latitude"])]}
        except (ValueError, KeyError):
            continue
        ftype = row.get("odhf_facility_type") or "Other"
        nm = (row.get("facility_name") or "Facility").title()
        addr = " ".join(x for x in (row.get("street_no"), (row.get("street_name") or "").title()) if x)
        desc = html_table([
            ("Facility", nm), ("Type", ftype), ("Source type", row.get("source_facility_type")),
            ("Address", addr), ("City", (row.get("city") or "").title()),
            ("Postal code", row.get("postal_code")), ("Data provider", row.get("provider")),
        ])
        doc.add(ftype, Placemark(nm, geom, sid if ftype == "Hospitals" else sid_other, desc))
    return doc


# =================================================================== Alberta 511 (licence unconfirmed)

AB511_FS = "https://services.arcgis.com/wjcPoefzjpzCgffS/ArcGIS/rest/services/Alberta511/FeatureServer"


def build_alberta_511(fetch_json, fetch_bytes, now, arcgis):
    doc = Document(
        "NorthTak - Alberta 511 Road Events",
        _about("Alberta 511 (via Esri Canada Alberta511 feature service)", "Not confirmed",
               "https://511.alberta.ca/",
               "<p>Reuse terms not yet confirmed. For private use only; not published.</p>"))
    pt = doc.style(Style("ev_pt", icon="road.png", icon_scale=0.8))
    closure_ln = doc.style(Style("ev_closed", line="#d50000", line_width=5))
    work_ln = doc.style(Style("ev_work", line="#ff8f00", line_width=4))

    def desc_for(p):
        return html_table([
            ("Road", p.get("RoadwayName")), ("Type", p.get("EventType")), ("Subtype", p.get("EventSubType")),
            ("Direction", p.get("DirectionOfTravel")), ("Lanes", p.get("LanesAffected")),
            ("Description", (p.get("Description") or "").strip()), ("Details", p.get("Details")),
            ("Start", p.get("StartDate")), ("Planned end", p.get("PlannedEndDate")),
            ("Updated", p.get("LastUpdated")),
        ])

    for f in arcgis(f"{AB511_FS}/1", fetch=fetch_json):
        p = f["properties"]
        doc.add((p.get("EventType") or "other").title(),
                Placemark((p.get("RoadwayName") or "Event") + " - " + (p.get("EventSubType") or ""),
                          f.get("geometry"), pt, desc_for(p)))
    for f in arcgis(f"{AB511_FS}/2", fetch=fetch_json):
        p = f["properties"]
        closed = "clos" in ((p.get("EventSubType") or "") + (p.get("Description") or "")).lower()
        doc.add("Affected road segments",
                Placemark((p.get("RoadwayName") or "Segment") + " - " + (p.get("EventSubType") or ""),
                          f.get("geometry"), closure_ln if closed else work_ln, desc_for(p)))
    return doc
