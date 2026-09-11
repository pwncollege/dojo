import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, Mock, call

import docker
import pytest
from requests import Response


spec = importlib.util.spec_from_file_location("image_gc", Path(__file__).with_name("docker_gc_images.py"))
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)
ID = "sha256:" + "a" * 64
OTHER_ID = "sha256:" + "b" * 64
DIGEST = "sha256:" + "c" * 64


@pytest.mark.parametrize("reference,expected", [
    ("example/course", "docker.io/example/course:latest"),
    ("example/course:latest", "docker.io/example/course:latest"),
    ("index.docker.io/example/course", "docker.io/example/course:latest"),
    ("registry-1.docker.io/example/course", "docker.io/example/course:latest"),
    ("ubuntu", "docker.io/library/ubuntu:latest"),
    ("docker.io/ubuntu", "docker.io/library/ubuntu:latest"),
    ("registry.example:5000/course:V2", "registry.example:5000/course:V2"),
    ("example/course:old@" + DIGEST, "docker.io/example/course@" + DIGEST),
    (ID, ID), (ID[7:19], ID[:19]),
])
def test_normalization(reference, expected):
    assert gc.normalize_reference(reference) == expected


def image(tags=None, *, image_id=ID, digests=None, labels=None):
    return {"Id": image_id, "RepoTags": tags or [], "RepoDigests": digests or [], "Labels": labels or {}}


def client_for(item):
    client = Mock()
    client.api.images.return_value = [item]
    client.api.containers.return_value = []
    client.api.inspect_image.return_value = item
    return client


@pytest.mark.parametrize("item,refs,used_ids", [
    (image(["example/course:latest", "example/old:v1"]), {"example/course"}, set()),
    (image(digests=["example/course@" + DIGEST]), {"example/course@" + DIGEST}, set()),
    (image(), {ID[:19]}, set()),
    (image(), set(), {ID}),
    (image(labels={"com.docker.compose.project": "dojo"}), set(), set()),
    (image(labels={"pwn.college.gc.keep": ""}), set(), set()),
])
def test_protection(item, refs, used_ids):
    assert gc.protected(item, {gc.normalize_reference(ref) for ref in refs}, used_ids)


def test_db_references_and_default_image():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(None,), ("",), ("example/course",), ("mac:desktop",)]
    assert gc.challenge_references(connection) == {gc.normalize_reference(gc.LEGACY_IMAGE), gc.normalize_reference("example/course")}
    cursor.execute.assert_called_once_with("SELECT DISTINCT data->'image' FROM dojo_challenges")


@pytest.mark.parametrize("rows", [[], [(False,)], [("invalid reference",)]])
def test_invalid_db_inventory_aborts(rows):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = rows
    with pytest.raises(ValueError):
        gc.challenge_references(connection)


@pytest.mark.parametrize("tags", [[], ["example/old:v1"], ["example/old:v1", "example/old:v2"]])
def test_dry_run_and_nonforce_removal(tags):
    client = client_for(image(tags))
    gc.collect_images(client, lambda: set())
    client.api.remove_image.assert_not_called()
    gc.collect_images(client, lambda: set(), apply=True)
    assert client.api.remove_image.call_args_list == [call(target, force=False, noprune=True) for target in tags or [ID]]


def test_stopped_container_preserves_image_and_configured_tag():
    client = client_for(image(["example/old:v1"]))
    client.api.images.return_value.append(image(["example/current:latest"], image_id=OTHER_ID))
    client.api.containers.return_value = [{"ImageID": ID, "Image": "example/current", "State": "exited"}]
    gc.collect_images(client, lambda: set(), apply=True)
    client.api.containers.assert_called_with(all=True)
    client.api.remove_image.assert_not_called()


def test_reference_added_between_alias_removals():
    client = client_for(image(["example/old:v1", "example/old:v2"]))
    refs = Mock(side_effect=[set(), set(), {gc.normalize_reference("example/old:v2")}])
    gc.collect_images(client, refs, apply=True)
    client.api.remove_image.assert_called_once_with("example/old:v1", force=False, noprune=True)


def test_moved_tag_is_skipped():
    client = client_for(image(["example/old:v1"]))
    client.api.inspect_image.return_value = image(["example/old:v1"], image_id=OTHER_ID)
    gc.collect_images(client, lambda: set(), apply=True)
    client.api.remove_image.assert_not_called()


def test_new_container_is_protected():
    client = client_for(image(["example/old:v1"]))
    client.api.containers.side_effect = [[], [{"ImageID": ID, "Image": "example/old:v1"}]]
    gc.collect_images(client, lambda: set(), apply=True)
    client.api.remove_image.assert_not_called()


def test_failed_db_refresh_prevents_deletion():
    client = client_for(image(["example/old:v1"]))
    with pytest.raises(RuntimeError):
        gc.collect_images(client, Mock(side_effect=[set(), RuntimeError("DB unavailable")]), apply=True)
    client.api.remove_image.assert_not_called()


@pytest.mark.parametrize("status", [404, 409, 500])
def test_docker_errors_are_not_retried_or_forced(status):
    client = client_for(image(["example/old:v1"]))
    response = Response()
    response.status_code = status
    client.api.remove_image.side_effect = docker.errors.APIError("failed", response=response)
    if status == 500:
        with pytest.raises(docker.errors.APIError):
            gc.collect_images(client, lambda: set(), apply=True)
    else:
        gc.collect_images(client, lambda: set(), apply=True)
    assert client.api.remove_image.call_count == 1


def test_overlapping_run_does_not_connect(tmp_path, monkeypatch):
    path = tmp_path / "gc.lock"
    monkeypatch.setattr(gc, "LOCK_PATH", str(path))
    monkeypatch.setattr(gc.argparse.ArgumentParser, "parse_args", lambda _: Mock())
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(gc.psycopg2, "connect", connect)
    with path.open("a") as lock:
        gc.fcntl.flock(lock, gc.fcntl.LOCK_EX | gc.fcntl.LOCK_NB)
        assert gc.main() == 0
    connect.assert_not_called()


@pytest.mark.parametrize("nodes,urls", [
    ('{}', ["unix:///var/run/docker.sock"]),
    ('{"1": {}, "2": {}}', ["tcp://192.168.42.2:2375", "tcp://192.168.42.3:2375"]),
])
def test_main_uses_direct_read_only_db_connection(tmp_path, monkeypatch, nodes, urls):
    monkeypatch.setattr(gc, "LOCK_PATH", str(tmp_path / "gc.lock"))
    monkeypatch.setattr(gc.argparse.ArgumentParser, "parse_args", lambda _: Mock(apply=False))
    monkeypatch.setattr(gc.Path, "read_text", lambda _: nodes)
    connection = Mock()
    connect = Mock(return_value=connection)
    factory = MagicMock()
    collect = Mock()
    monkeypatch.setattr(gc.psycopg2, "connect", connect)
    monkeypatch.setattr(gc.docker, "DockerClient", factory)
    monkeypatch.setattr(gc, "collect_images", collect)
    assert gc.main() == 0
    connect.assert_called_once_with(connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=10000")
    assert connection.autocommit is True
    connection.close.assert_called_once()
    assert factory.call_args_list == [call(base_url=url, timeout=60) for url in urls]
    assert collect.call_count == len(urls)
