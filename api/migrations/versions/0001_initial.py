"""initial schema (generated from the current models; later changes use `alembic revision --autogenerate`)"""
from alembic import op

from app import models  # noqa: F401
from app.db import Base

revision = "0001"
down_revision = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
