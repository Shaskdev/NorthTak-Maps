"""Minimal KML/KMZ writer for ATAK overlays (standard library only).

Output is deterministic: the same input features always produce byte-identical
KMZ files (fixed zip timestamps, stable ordering, no "generated at" stamps),
so an unchanged layer never shows up as an update in the plugin.
"""

import struct
import zipfile
import zlib
from xml.sax.saxutils import escape

COORD_DECIMALS = 5  # ~1 m; never simplifies shapes, only trims float noise

# KML colours are aabbggrr
def kml_color(hex_rgb, alpha=0xFF):
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"{alpha:02x}{b}{g}{r}"


def _c(v):
    return f"{round(float(v), COORD_DECIMALS):.{COORD_DECIMALS}f}".rstrip("0").rstrip(".")


def _ring(coords):
    return " ".join(f"{_c(p[0])},{_c(p[1])}" for p in coords)


def geometry_kml(geom, extrude_alt=None):
    """GeoJSON geometry -> KML geometry string (Point, LineString, Polygon, Multi*)."""
    if not geom:
        return ""
    t = geom["type"]
    c = geom.get("coordinates")
    if t == "Point":
        return f"<Point><coordinates>{_c(c[0])},{_c(c[1])}</coordinates></Point>"
    if t == "LineString":
        return f"<LineString><tessellate>1</tessellate><coordinates>{_ring(c)}</coordinates></LineString>"
    if t == "Polygon":
        if not c:
            return ""
        outer = f"<outerBoundaryIs><LinearRing><coordinates>{_ring(c[0])}</coordinates></LinearRing></outerBoundaryIs>"
        inner = "".join(
            f"<innerBoundaryIs><LinearRing><coordinates>{_ring(r)}</coordinates></LinearRing></innerBoundaryIs>"
            for r in c[1:]
        )
        return f"<Polygon><tessellate>1</tessellate>{outer}{inner}</Polygon>"
    if t in ("MultiPoint", "MultiLineString", "MultiPolygon"):
        single = t[5:]
        parts = "".join(geometry_kml({"type": single, "coordinates": p}) for p in c)
        return f"<MultiGeometry>{parts}</MultiGeometry>"
    if t == "GeometryCollection":
        parts = "".join(geometry_kml(g) for g in geom.get("geometries", []))
        return f"<MultiGeometry>{parts}</MultiGeometry>"
    raise ValueError(f"unsupported geometry {t}")


def html_table(rows):
    """[(label, value)] -> small HTML table for the ATAK details view. Skips empty values."""
    out = []
    for k, v in rows:
        if v is None or v == "":
            continue
        val = escape(str(v)).replace("\n", "<br/>")
        out.append(f"<tr><td><b>{escape(k)}</b></td><td>{val}</td></tr>")
    return "<table>" + "".join(out) + "</table>"


class Style:
    def __init__(self, sid, icon=None, icon_scale=1.0, line="#000000", line_width=2,
                 fill=None, fill_alpha=0x55, label_scale=0.8):
        self.sid, self.icon, self.icon_scale = sid, icon, icon_scale
        self.line, self.line_width = line, line_width
        self.fill, self.fill_alpha, self.label_scale = fill, fill_alpha, label_scale

    def kml(self):
        parts = [f'<Style id="{self.sid}">']
        if self.icon:
            parts.append(f"<IconStyle><scale>{self.icon_scale}</scale><Icon><href>icons/{self.icon}</href></Icon></IconStyle>")
        parts.append(f"<LabelStyle><scale>{self.label_scale}</scale></LabelStyle>")
        parts.append(f"<LineStyle><color>{kml_color(self.line)}</color><width>{self.line_width}</width></LineStyle>")
        if self.fill:
            parts.append(f"<PolyStyle><color>{kml_color(self.fill, self.fill_alpha)}</color><fill>1</fill><outline>1</outline></PolyStyle>")
        else:
            parts.append("<PolyStyle><fill>0</fill><outline>1</outline></PolyStyle>")
        parts.append("</Style>")
        return "".join(parts)


class Placemark:
    def __init__(self, name, geometry, style, description="", sort_key=None):
        self.name, self.geometry, self.style = name, geometry, style
        self.description = description
        self.sort_key = sort_key if sort_key is not None else name

    def kml(self):
        desc = f"<description><![CDATA[{self.description}]]></description>" if self.description else ""
        return (f"<Placemark><name>{escape(self.name)}</name>{desc}"
                f"<styleUrl>#{self.style}</styleUrl>{geometry_kml(self.geometry)}</Placemark>")


class Document:
    """A KML document made of named folders of placemarks."""

    def __init__(self, name, description):
        self.name, self.description = name, description
        self.styles = {}
        self.folders = {}  # folder name -> [Placemark]
        self.folder_order = []

    def style(self, st):
        self.styles[st.sid] = st
        return st.sid

    def add(self, folder, placemark):
        if folder not in self.folders:
            self.folders[folder] = []
            self.folder_order.append(folder)
        self.folders[folder].append(placemark)

    def count(self):
        return sum(len(v) for v in self.folders.values())

    def kml(self):
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
               f"<name>{escape(self.name)}</name>",
               f"<description><![CDATA[{self.description}]]></description>"]
        out += [self.styles[k].kml() for k in sorted(self.styles)]
        for f in self.folder_order:
            pms = sorted(self.folders[f], key=lambda p: (str(p.sort_key), p.name))
            out.append(f"<Folder><name>{escape(f)} ({len(pms)})</name>")
            out += [p.kml() for p in pms]
            out.append("</Folder>")
        if not self.folder_order:
            out.append("<Folder><name>No current features</name></Folder>")
        out.append("</Document></kml>")
        return "\n".join(out)

    def icons_used(self):
        return sorted({s.icon for s in self.styles.values() if s.icon})


def write_kmz(path, doc, icon_bytes):
    """Write doc.kml + icons/*.png into a deterministic KMZ."""
    entries = [("doc.kml", doc.kml().encode("utf-8"))]
    for name in doc.icons_used():
        entries.append((f"icons/{name}", icon_bytes[name]))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:  # doc.kml must be first
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, data)


# ---------------------------------------------------------------- icons

def _png(w, h, pixels):
    """pixels: list of rows of (r,g,b,a) tuples -> PNG bytes."""
    raw = b"".join(b"\x00" + b"".join(struct.pack("BBBB", *px) for px in row) for row in pixels)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _rgb(hex_rgb):
    h = hex_rgb.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def circle_icon(fill_hex, size=32, border=(20, 20, 20)):
    r0 = size / 2 - 1
    cx = cy = (size - 1) / 2
    fill = _rgb(fill_hex)
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d <= r0 - 2.5:
                row.append(fill + (255,))
            elif d <= r0:
                row.append(border + (255,))
            else:
                row.append((0, 0, 0, 0))
        rows.append(row)
    return _png(size, size, rows)


def cross_icon(cross_hex="#d32f2f", size=32):
    """White rounded square with a red cross (medical facility)."""
    cross = _rgb(cross_hex)
    rows = []
    a, b = size * 0.38, size * 0.62
    for y in range(size):
        row = []
        for x in range(size):
            edge = x in (0, size - 1) or y in (0, size - 1)
            if edge:
                row.append((60, 60, 60, 255))
            elif (a <= x < b and 5 <= y < size - 5) or (a <= y < b and 5 <= x < size - 5):
                row.append(cross + (255,))
            else:
                row.append((255, 255, 255, 255))
        rows.append(row)
    return _png(size, size, rows)
