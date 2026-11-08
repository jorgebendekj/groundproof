"""Schema creation and (optional) demo seeding. Alembic manages production schema; this keeps dev zero-setup."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import Base, engine
from .models import Organization, User
from .security import hash_password

FIXTURES = Path(__file__).resolve().parents[2] / "demo" / "fixtures"


def init_db() -> None:
    Base.metadata.create_all(engine)


def ensure_user(db: Session, email: str, password: str, role: str, org_id: int | None) -> User:
    u = db.scalars(select(User).where(User.email == email)).first()
    if not u:
        u = User(email=email, password_hash=hash_password(password), role=role, organization_id=org_id)
        db.add(u)
        db.flush()
    return u


def seed(db: Session) -> None:
    s = get_settings()
    org = db.scalars(select(Organization).where(Organization.name == "GroundProof Ops")).first()
    if not org:
        org = Organization(name="GroundProof Ops")
        db.add(org)
        db.flush()
    ensure_user(db, s.admin_email, s.admin_password, "admin", org.id)
    if s.demo_seed:
        buyer_org = db.scalars(select(Organization).where(Organization.name == "Demo Importer GmbH")).first()
        if not buyer_org:
            buyer_org = Organization(name="Demo Importer GmbH")
            db.add(buyer_org)
            db.flush()
        ensure_user(db, "analyst@example.com", "demo-analyst", "analyst", org.id)
        ensure_user(db, "buyer@example.com", "demo-buyer", "buyer", buyer_org.id)
        ensure_user(db, "field@example.com", "demo-field", "field_partner", org.id)
    db.commit()
