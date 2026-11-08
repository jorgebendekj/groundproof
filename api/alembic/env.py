from alembic import context
from app import models  # noqa: F401  (register tables)
from app.config import get_settings
from app.db import Base, make_engine

engine = make_engine(get_settings().database_url)
with engine.connect() as conn:
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
