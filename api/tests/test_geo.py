import io
import zipfile

import shapefile
from conftest import fc, square

from app import geo


def test_geojson_valid_and_area():
    feats = geo.parse_geojson(fc(square(-55.0, -12.0, 0.01, id="a")))
    v = geo.validate_batch(feats)[0]
    assert v.status == "valid" and 90 < v.area_ha < 130  # ~0.01 deg ≈ 1.1 km square ≈ 120 ha


def test_bowtie_is_repaired():
    bow = {"type": "Feature", "properties": {"id": "bow"}, "geometry": {"type": "Polygon", "coordinates": [
        [[-55, -12], [-54.99, -11.99], [-54.99, -12], [-55, -11.99], [-55, -12]]]}}
    v = geo.validate_batch(geo.parse_geojson(fc(bow)))[0]
    assert v.status == "fixed" and v.geometry is not None and "repaired" in v.notes[0]


def test_invalid_inputs():
    import pytest
    with pytest.raises(geo.IngestError):
        geo.parse_geojson(b"{not json")
    with pytest.raises(geo.IngestError):
        geo.parse_upload("x.txt", b"")
    with pytest.raises(geo.IngestError):
        geo.parse_shapefile_zip(b"nope")
    zipfile.ZipFile(io.BytesIO(), "w")
    with pytest.raises(geo.IngestError):
        geo.parse_csv(b"a,b\n")
    out_of_range = fc({"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [500, 10]}})
    assert geo.validate_batch(geo.parse_geojson(out_of_range))[0].status == "invalid"


def test_duplicates_and_overlaps_flagged():
    a, b, c = square(-55, -12, id="a"), square(-55, -12, id="b"), square(-55.005, -12.005, id="c")
    items = geo.validate_batch(geo.parse_geojson(fc(a, b, c)))
    assert any("Duplicate" in n for n in items[1].notes)
    assert items[2].status == "flagged" and any("Overlaps" in n for n in items[2].notes)


def test_csv_points_and_bad_rows():
    feats = geo.parse_csv(b"id,lat,lon\nx1,-12.5,-55.1\nx2,abc,1\n")
    v = geo.validate_batch(feats)
    assert v[0].geom_type == "Point" and v[0].status == "valid" and v[0].area_ha is None
    assert v[1].status == "invalid"


def test_shapefile_reprojection():
    buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=buf[0], shx=buf[1], dbf=buf[2])
    w.field("id", "C")
    # UTM 21S square (EPSG:32721) near Mato Grosso
    w.poly([[[500000, 8600000], [501000, 8600000], [501000, 8601000], [500000, 8601000], [500000, 8600000]]])
    w.record("utm1")
    w.close()
    prj = 'PROJCS["WGS 84 / UTM zone 21S",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-57],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",10000000],UNIT["metre",1]]'
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("p.shp", buf[0].getvalue()); zf.writestr("p.shx", buf[1].getvalue())
        zf.writestr("p.dbf", buf[2].getvalue()); zf.writestr("p.prj", prj)
    v = geo.validate_batch(geo.parse_shapefile_zip(z.getvalue()))[0]
    assert v.status == "valid" and 95 < v.area_ha < 105          # 1 km² = 100 ha
    x, y = v.geometry["coordinates"][0][0]
    assert -58 < x < -56 and -14 < y < -10
