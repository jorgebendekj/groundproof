"""Daily monitoring job. `python -m workers.scheduler --once` or run as a loop (compose service `worker`).

Decision D-03: a plain scheduler loop is used instead of Prefect/Celery for the MVP (no extra broker needed,
one process, idempotent runs). Swap for Celery beat when volume requires horizontal scaling.
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta

from sqlalchemy import select

from app.bootstrap import init_db, seed
from app.db import SessionLocal
from app.models import Plot, User
from app.services import run_monitoring

INTERVAL_S = 24 * 3600


def run_daily() -> dict[str, int]:
    init_db()
    created = checked = failed = 0
    with SessionLocal() as db:
        seed(db)
        admin = db.scalars(select(User).where(User.role == "admin")).first()
        for p in db.scalars(select(Plot)).all():
            try:
                _, alert = run_monitoring(db, p, admin, since=date.today() - timedelta(days=30))
                created += bool(alert)
                checked += 1
            except Exception as e:  # noqa: BLE001  one bad plot must not stop the batch
                db.rollback()
                failed += 1
                print(f"plot {p.id} failed: {e}", file=sys.stderr)
    return {"checked": checked, "alerts_created": created, "failed": failed}


if __name__ == "__main__":
    if "--once" in sys.argv:
        print(run_daily())
    else:
        while True:
            print(run_daily(), flush=True)
            time.sleep(INTERVAL_S)
