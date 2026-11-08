"""HTTP helpers with retries (standard library only)."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "NorthTak-Maps/0.1 (+https://github.com/Shaskdev/NorthTak-Maps)"


def get(url, params=None, timeout=90, retries=3):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and 400 <= e.code < 500 and e.code != 429:
                break
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET failed: {url}: {last}")


def get_json(url, params=None, **kw):
    return json.loads(get(url, params, **kw).decode("utf-8"))


def arcgis_query_all(layer_url, where="1=1", page=1000, fetch=get_json):
    """All features of an ArcGIS REST layer as GeoJSON features, paging past maxRecordCount."""
    feats, offset = [], 0
    while True:
        d = fetch(layer_url + "/query", {
            "where": where, "outFields": "*", "f": "geojson", "outSR": 4326,
            "resultOffset": offset, "resultRecordCount": page, "orderByFields": "OBJECTID",
        })
        if "error" in d:
            raise RuntimeError(f"ArcGIS error from {layer_url}: {d['error']}")
        batch = d.get("features", [])
        feats.extend(batch)
        more = d.get("exceededTransferLimit") or (d.get("properties") or {}).get("exceededTransferLimit")
        if not batch or not more:
            return feats
        offset += len(batch)
