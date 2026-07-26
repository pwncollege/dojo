from utils import dojo_run


def test_dojo_schema_creation_serializes_first_start():
    result = dojo_run("dojo", "flask", input="""
import threading
import time
import uuid

from flask import current_app
from sqlalchemy import Column, Integer, Table, inspect, text

from CTFd.models import db
from CTFd.plugins import dojo_plugin

app = current_app._get_current_object()
table = Table(
    f"test_dojo_schema_{uuid.uuid4().hex}",
    db.metadata,
    Column("id", Integer, primary_key=True),
)
real_create_all = db.metadata.create_all
create_calls = []
create_calls_lock = threading.Lock()
first_create_entered = threading.Event()
release_first_create = threading.Event()
errors = []

def tracked_create_all(*args, **kwargs):
    with create_calls_lock:
        create_calls.append(threading.get_ident())
        call_number = len(create_calls)
    if call_number == 1:
        first_create_entered.set()
        assert release_first_create.wait(10)
    return real_create_all(*args, **kwargs)

def create_tables():
    try:
        with app.app_context():
            dojo_plugin.create_dojo_tables()
    except BaseException as error:
        errors.append(error)

db.metadata.create_all = tracked_create_all
first_thread = threading.Thread(target=create_tables)
second_thread = threading.Thread(target=create_tables)
try:
    first_thread.start()
    assert first_create_entered.wait(10)
    second_thread.start()
    deadline = time.time() + 10
    waiting_for_lock = False
    while time.time() < deadline:
        with db.engine.connect() as connection:
            waiting_for_lock = bool(connection.execute(
                text(
                    "SELECT COUNT(*) FROM pg_locks "
                    "WHERE locktype = 'advisory' AND NOT granted "
                    "AND classid = :namespace AND objid = :lock_id "
                    "AND objsubid = 2"
                ),
                {
                    "namespace": dojo_plugin.DOJO_SCHEMA_LOCK_NAMESPACE,
                    "lock_id": dojo_plugin.DOJO_SCHEMA_LOCK_ID,
                },
            ).scalar())
        if waiting_for_lock:
            break
        time.sleep(0.01)
    assert waiting_for_lock
    assert len(create_calls) == 1
    release_first_create.set()
    first_thread.join(10)
    second_thread.join(10)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert len(create_calls) == 2
    assert inspect(db.engine).has_table(table.name)
finally:
    release_first_create.set()
    for thread in (first_thread, second_thread):
        if thread.ident is not None:
            thread.join(10)
    db.metadata.create_all = real_create_all
    table.drop(db.engine, checkfirst=True)
    db.metadata.remove(table)

print("DOJO_SCHEMA_CREATION_SERIALIZED")
""", check=False)
    assert result.returncode == 0, result.stderr
    assert "DOJO_SCHEMA_CREATION_SERIALIZED" in result.stdout, (
        result.stdout + result.stderr
    )
