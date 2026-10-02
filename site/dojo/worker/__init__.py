import logging
import time

from sqlalchemy import text

from ..models import db

logger = logging.getLogger(__name__)


def wait_for_schema(timeout=600):
    deadline = time.monotonic() + timeout
    while True:
        try:
            ready = db.session.execute(text(
                "SELECT to_regclass('public.dojos') IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM config WHERE key = 'setup' AND value IN ('1', 'true'))"
            )).scalar()
        except Exception:
            ready = False
        finally:
            db.session.rollback()
        if ready:
            return
        if time.monotonic() > deadline:
            raise RuntimeError("database schema is not bootstrapped")
        logger.info("Waiting for the web container to bootstrap the database...")
        time.sleep(2)
