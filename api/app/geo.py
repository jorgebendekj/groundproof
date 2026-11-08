"""Plot ingestion: parse GeoJSON / zipped shapefile / CSV, reproject, validate."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import shapefile  # pyshp
from pyproj import CRS, Geod, Transformer
from shapely import transform as _sh_transform
from shapely.geometry import Point, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity, make_valid

GEOD = Geod(ellps="WGS84")
MAX_VERTICES = 20000


class IngestError(ValueError):
    pass


@dataclass
class RawFeature:
    geometry: BaseGeometry | None
    props: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class Validated:
    geometry: dict[str, Any] | None
    geom_type: str
    status: str  # valid | fixed | flagged | invalid
    notes: list[str]
    area_ha: float | None
    external_id: str | None
    props: dict[str, Any]


def area_ha(g: BaseGeometry) -> float:
    if g.is_empty or g.geom_type in ("Point", "MultiPoint"):
        return 0.0
    a, _ = GEOD.geometry_area_perimeter(g)
    return abs(a) / 10_000.0


def parse_geojson(data: bytes) -> list[RawFeature]:
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as e:
        raise IngestError(f"Invalid JSON: {e}") from e
    t = doc.get("type")
    if t == "FeatureCollection":
        feats = doc.get("features", [])
    elif t == "Feature":
        feats = [doc]
    elif t in ("Polygon", "MultiPolygon", "Point"):
        feats = [{"type": "Feature", "geometry": doc, "properties": {}}]
    else:
        raise IngestError("GeoJSON must be a FeatureCollection, Feature or geometry")
    crs = (doc.get("crs") or {}).get("properties", {}).get("name")
    tr = _transformer(CRS.from_user_input(crs)) if crs else None
    out = []
    for f in feats:
        props = dict(f.get("properties") or {})
        try:
            g = shape(f["geometry"]) if f.get("geometry") else None
            if g is not None and tr:
                g = _sh_transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
            out.append(RawFeature(g, props, None if g is not None else "Missing geometry"))
        except Exception as e:  # noqa: BLE001
            out.append(RawFeature(None, props, f"Unreadable geometry: {e}"))
    return out


def _transformer(crs: CRS) -> Transformer | None:
    if crs.to_epsg() == 4326:
        return None
    return Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)


def parse_shapefile_zip(data: bytes) -> list[RawFeature]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise IngestError("Not a valid zip file") from e
    names = {n.lower(): n for n in zf.namelist() if not n.endswith("/")}
    shp = next((n for k, n in names.items() if k.endswith(".shp")), None)
    if not shp:
        raise IngestError("Zip contains no .shp file")
    base = shp[:-4]

    def part(ext: str):
        n = names.get((base + ext).lower())
        return io.BytesIO(zf.read(n)) if n else None

    shx, dbf = part(".shx"), part(".dbf")
    if dbf is None:
        raise IngestError("Zip is missing the .dbf file")
    reader = shapefile.Reader(shp=io.BytesIO(zf.read(shp)), shx=shx, dbf=dbf)
    tr = None
    prj = names.get((base + ".prj").lower())
    if prj:
        try:
            tr = _transformer(CRS.from_wkt(zf.read(prj).decode("utf-8", "ignore")))
        except Exception as e:  # noqa: BLE001
            raise IngestError(f"Unreadable .prj: {e}") from e
    fields = [f[0] for f in reader.fields[1:]]
    out = []
    for sr in reader.shapeRecords():
        props = dict(zip(fields, sr.record, strict=False))
        try:
            g = shape(sr.shape.__geo_interface__)
            if tr:
                g = _sh_transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
            out.append(RawFeature(g, props))
        except Exception as e:  # noqa: BLE001
            out.append(RawFeature(None, props, f"Unreadable geometry: {e}"))
    return out


def parse_csv(data: bytes) -> list[RawFeature]:
    text = data.decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise IngestError("CSV is empty")
    lower = {k.lower().strip(): k for k in rows[0]}
    lat = next((lower[k] for k in ("lat", "latitude", "y") if k in lower), None)
    lon = next((lower[k] for k in ("lon", "lng", "long", "longitude", "x") if k in lower), None)
    if not lat or not lon:
        raise IngestError("CSV needs lat/lon (or latitude/longitude) columns")
    out = []
    for r in rows:
        props = {k: v for k, v in r.items() if k not in (lat, lon)}
        try:
            out.append(RawFeature(Point(float(r[lon]), float(r[lat])), props))
        except (TypeError, ValueError):
            out.append(RawFeature(None, props, "Non-numeric coordinates"))
    return out


def parse_upload(filename: str, data: bytes) -> list[RawFeature]:
    n = filename.lower()
    if n.endswith((".geojson", ".json")):
        return parse_geojson(data)
    if n.endswith(".zip"):
        return parse_shapefile_zip(data)
    if n.endswith(".csv"):
        return parse_csv(data)
    raise IngestError("Unsupported file type; use .geojson, .zip (shapefile) or .csv")


def validate_feature(f: RawFeature, idx: int, max_polygon_ha: float = 50_000.0) -> Validated:
    ext = str(f.props.get("id") or f.props.get("plot_id") or f.props.get("external_id") or f"row-{idx + 1}")
    if f.geometry is None:
        return Validated(None, "None", "invalid", [f.error or "Missing geometry"], None, ext, f.props)
    g = f.geometry
    notes: list[str] = []
    status = "valid"
    if g.is_empty:
        return Validated(None, g.geom_type, "invalid", ["Empty geometry"], None, ext, f.props)
    if g.geom_type not in ("Point", "Polygon", "MultiPolygon"):
        return Validated(None, g.geom_type, "invalid", [f"Unsupported geometry type {g.geom_type}"], None, ext, f.props)
    minx, miny, maxx, maxy = g.bounds
    if not (-180 <= minx and maxx <= 180 and -90 <= miny and maxy <= 90):
        return Validated(None, g.geom_type, "invalid",
                         ["Coordinates outside WGS84 range; check CRS (reprojection needs a .prj/crs)"], None, ext, f.props)
    nverts = len(mapping(g)["coordinates"]) if g.geom_type == "Point" else sum(
        len(c) for c in _coords(g))
    if nverts > MAX_VERTICES:
        return Validated(None, g.geom_type, "invalid", [f"Too many vertices ({nverts})"], None, ext, f.props)
    if g.geom_type != "Point" and not g.is_valid:
        why = explain_validity(g)
        fixed = make_valid(g)
        polys = [p for p in getattr(fixed, "geoms", [fixed]) if p.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return Validated(None, g.geom_type, "invalid", [f"Invalid geometry: {why}"], None, ext, f.props)
        from shapely.ops import unary_union
        g = unary_union(polys)
        status = "fixed"
        notes.append(f"Geometry repaired ({why})")
    a = area_ha(g)
    if g.geom_type == "Point":
        notes.append("Point plot: accepted for small plots (<4 ha); polygon required above that size")
        a_val: float | None = None
    else:
        a_val = round(a, 3)
        if a > max_polygon_ha:
            status = "flagged"
            notes.append(f"Unusually large area ({a:.0f} ha)")
        if a < 0.01:
            status = "flagged"
            notes.append("Area below 0.01 ha")
    return Validated(mapping(g), g.geom_type, status, notes, a_val, ext, f.props)


def _coords(g: BaseGeometry):
    for p in getattr(g, "geoms", [g]):
        yield list(p.exterior.coords)
        for i in p.interiors:
            yield list(i.coords)


def flag_duplicates_and_overlaps(items: list[Validated], overlap_ratio: float = 0.2) -> None:
    """Flag exact duplicates and significant overlaps within the batch (mutates)."""
    geoms = [shape(v.geometry) if v.geometry else None for v in items]
    seen: dict[str, int] = {}
    for i, g in enumerate(geoms):
        if g is None:
            continue
        key = g.wkb_hex
        if key in seen:
            items[i].notes.append(f"Duplicate of {items[seen[key]].external_id}")
            if items[i].status == "valid":
                items[i].status = "flagged"
            continue
        seen[key] = i
    for i, gi in enumerate(geoms):
        if gi is None or gi.geom_type == "Point":
            continue
        for j in range(i + 1, len(geoms)):
            gj = geoms[j]
            if gj is None or gj.geom_type == "Point" or not gi.intersects(gj):
                continue
            inter = gi.intersection(gj).area
            smaller = min(gi.area, gj.area)
            if smaller > 0 and inter / smaller >= overlap_ratio and gi.wkb_hex != gj.wkb_hex:
                for a, b in ((i, j), (j, i)):
                    items[a].notes.append(
                        f"Overlaps {items[b].external_id} ({inter / smaller:.0%} of the smaller plot)")
                    if items[a].status == "valid":
                        items[a].status = "flagged"


def validate_batch(feats: list[RawFeature]) -> list[Validated]:
    items = [validate_feature(f, i) for i, f in enumerate(feats)]
    flag_duplicates_and_overlaps(items)
    return items
