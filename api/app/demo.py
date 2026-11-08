"""Demo data: 200 synthetic soy plots + a compliant/cleared pair. `python -m app.demo [--out file]`.

Geometry is SYNTHETIC but placed in the Sorriso/Sinop area of Mato Grosso, Brazil, where soy-driven clearing
since 2020 is documented at regional level (MAAP #161); see docs/DECISIONS.md D-10.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select

from .bootstrap import init_db, seed
from .db import SessionLocal
from .models import Organization, Plot, Supplier, User
from .services import run_cutoff, run_monitoring

LON0, LAT0 = -55.72, -12.50
FIXTURE = Path(__file__).resolve().parents[2] / "demo" / "fixtures" / "mato_grosso_demo.geojson"


def _sq(lon: float, lat: float, s: float) -> dict:
    return {"type": "Polygon", "coordinates": [[[lon, lat], [lon + s, lat], [lon + s, lat + s],
                                                [lon, lat + s], [lon, lat]]]}


def build_features() -> list[dict]:
    feats = []
    for i in range(200):
        feats.append({"type": "Feature", "properties": {"id": f"MT-{i:03d}", "commodity": "soy", "country": "BR"},
                      "geometry": _sq(LON0 + (i % 20) * 0.025, LAT0 - (i // 20) * 0.025, 0.012)})
    # the demo pair, side by side
    feats.append({"type": "Feature", "properties": {"id": "DEMO-COMPLIANT", "scenario": "stable_crop",
                                                    "commodity": "soy", "country": "BR"},
                  "geometry": _sq(LON0 + 0.6, LAT0 + 0.05, 0.015)})
    feats.append({"type": "Feature", "properties": {"id": "DEMO-CLEARED", "scenario": "cleared_post_2020",
                                                    "clear_date": "2022-08-15", "commodity": "soy", "country": "BR"},
                  "geometry": _sq(LON0 + 0.62, LAT0 + 0.05, 0.015)})
    return feats


def write_fixture(path: Path = FIXTURE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": build_features()}))
    return path


def load(db, run_checks: bool = True) -> int:
    from . import geo
    org = db.scalars(select(Organization).where(Organization.name == "Demo Importer GmbH")).first()
    if db.scalars(select(Supplier).where(Supplier.name == "Fazenda Demo Sorriso")).first():
        return 0
    sup = Supplier(name="Fazenda Demo Sorriso", country="BR", organization_id=org.id)
    db.add(sup)
    db.flush()
    n = 0
    for v in geo.validate_batch([geo.RawFeature(__import__("shapely.geometry", fromlist=["shape"]).shape(f["geometry"]),
                                                f["properties"]) for f in build_features()]):
        if v.geometry is None:
            continue
        p = Plot(external_id=v.external_id, supplier_id=sup.id, organization_id=org.id, geometry=v.geometry,
                 geom_type=v.geom_type, commodity="soy", country="BR", area_ha=v.area_ha, source_file="demo",
                 properties={k: x for k, x in v.props.items() if isinstance(x, (str, int, float))},
                 validation_status=v.status, validation_notes=v.notes)
        db.add(p)
        n += 1
    db.commit()
    if run_checks:
        admin = db.scalars(select(User).where(User.role == "admin")).first()
        for p in db.scalars(select(Plot).where(Plot.supplier_id == sup.id)).all():
            run_cutoff(db, p, admin)
            run_monitoring(db, p, admin)
    return n


if __name__ == "__main__":
    if "--out" in sys.argv:
        print(write_fixture(Path(sys.argv[sys.argv.index("--out") + 1])))
    else:
        init_db()
        with SessionLocal() as s:
            seed(s)
            print(f"loaded {load(s)} demo plots")
