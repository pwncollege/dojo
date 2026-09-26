import sys
import time

from .app import create_app
from .models import Users, db, get_config, set_config


def wait_for_database(app):
    with app.app_context():
        while True:
            try:
                db.engine.raw_connection().close()
                return
            except Exception as e:
                print(f"Waiting for database: {e}", file=sys.stderr, flush=True)
                time.sleep(1)


def main():
    app = create_app()
    wait_for_database(app)
    with app.app_context():
        db.create_all()
        if not get_config("setup"):
            if not Users.query.filter_by(name="admin").first():
                db.session.add(Users(name="admin", email="admin@example.com", password="admin", type="admin", hidden=True))
                db.session.commit()
            set_config("setup", True)


if __name__ == "__main__":
    main()
