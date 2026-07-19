import importlib.util
import json
import os
import pathlib
import select
import signal
import subprocess

import pytest


CHECKOUT_MODULE_PATH = (
    pathlib.Path(__file__).parents[1] / "dojo_plugin" / "utils" / "checkout.py"
)
CHECKOUT_SPEC = importlib.util.spec_from_file_location(
    "dojo_checkout_under_test",
    CHECKOUT_MODULE_PATH,
)
checkout = importlib.util.module_from_spec(CHECKOUT_SPEC)
CHECKOUT_SPEC.loader.exec_module(checkout)


def create_checkout(path, label):
    path.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True,
    )
    (path / "state").write_text(label)
    subprocess.run(["git", "-C", str(path), "add", "state"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", label],
        check=True,
        capture_output=True,
    )


def create_swap(tmp_path):
    dojo_root = tmp_path / "dojos"
    temp_root = dojo_root / "tmp"
    temp_root.mkdir(parents=True)
    live_path = dojo_root / "12345678"
    staged_path = temp_root / "staged"
    create_checkout(live_path, "old")
    create_checkout(staged_path, "new")
    prepared = checkout.DurableCheckoutSwap.prepare(staged_path)
    prepared_live = checkout.DurableCheckoutSwap.prepare_existing(live_path)
    swap = checkout.DurableCheckoutSwap.begin(
        live_path,
        staged_path,
        temp_root,
        None,
        prepared,
        prepared_live,
        {"transactional_outbox": True},
    )
    return swap, live_path, temp_root


def assert_sigkill(child_action):
    child_pid = os.fork()
    if child_pid == 0:
        child_action()
        os._exit(1)
    _, status = os.waitpid(child_pid, 0)
    assert os.WIFSIGNALED(status)
    assert os.WTERMSIG(status) == signal.SIGKILL


@pytest.mark.parametrize(
    "interrupted_phase",
    ["new_preserved", "old_preserved", "live_installed"],
)
def test_checkout_swap_recovers_interrupt_after_each_rename(
    tmp_path,
    interrupted_phase,
):
    swap, live_path, temp_root = create_swap(tmp_path)
    write_phase = swap._set_phase

    def interrupt_after_rename(phase):
        if phase == interrupted_phase:
            raise KeyboardInterrupt
        write_phase(phase)

    swap._set_phase = interrupt_after_rename
    with pytest.raises(KeyboardInterrupt):
        swap.install()

    checkout.DurableCheckoutSwap.load(live_path, temp_root).rollback()
    assert (live_path / "state").read_text() == "old"
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
@pytest.mark.parametrize(
    ("interrupted_phase", "write_marker"),
    [
        ("new_preserved", False),
        ("new_preserved", True),
        ("old_preserved", False),
        ("old_preserved", True),
        ("live_installed", False),
        ("live_installed", True),
    ],
)
def test_checkout_swap_recovers_sigkill_around_each_rename_marker(
    tmp_path,
    interrupted_phase,
    write_marker,
):
    swap, live_path, temp_root = create_swap(tmp_path)

    def install_until_sigkill():
        child_swap = checkout.DurableCheckoutSwap.load(live_path, temp_root)
        write_phase = child_swap._set_phase

        def kill_around_marker(phase):
            if phase != interrupted_phase:
                write_phase(phase)
                return
            if write_marker:
                write_phase(phase)
            os.kill(os.getpid(), signal.SIGKILL)

        child_swap._set_phase = kill_around_marker
        child_swap.install()

    assert_sigkill(install_until_sigkill)
    checkout.DurableCheckoutSwap.load(live_path, temp_root).rollback()
    assert (live_path / "state").read_text() == "old"
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
@pytest.mark.parametrize(
    ("marker", "recovery_method", "expected_state"),
    [
        ("commit_started", "rollback", "old"),
        ("committed", "finalize", "new"),
    ],
)
def test_checkout_swap_recovers_sigkill_after_commit_markers(
    tmp_path,
    marker,
    recovery_method,
    expected_state,
):
    swap, live_path, temp_root = create_swap(tmp_path)

    def install_until_sigkill():
        child_swap = checkout.DurableCheckoutSwap.load(live_path, temp_root)
        child_swap.install()
        child_swap.mark_commit_started()
        if marker == "committed":
            child_swap.mark_committed()
        os.kill(os.getpid(), signal.SIGKILL)

    assert_sigkill(install_until_sigkill)
    recovered_swap = checkout.DurableCheckoutSwap.load(live_path, temp_root)
    getattr(recovered_swap, recovery_method)()
    assert (live_path / "state").read_text() == expected_state
    assert list(temp_root.iterdir()) == []


def test_checkout_swap_repeated_rollback_survives_interrupt(tmp_path, monkeypatch):
    swap, live_path, temp_root = create_swap(tmp_path)
    swap.install()
    durable_rename = checkout._durable_rename
    interrupted = False

    def interrupt_restoration(source, destination):
        nonlocal interrupted
        durable_rename(source, destination)
        if not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(checkout, "_durable_rename", interrupt_restoration)
    with pytest.raises(KeyboardInterrupt):
        swap.rollback()
    monkeypatch.setattr(checkout, "_durable_rename", durable_rename)

    checkout.DurableCheckoutSwap.load(live_path, temp_root).rollback()
    assert (live_path / "state").read_text() == "old"
    assert list(temp_root.iterdir()) == []


def test_checkout_swap_repeated_finalize_survives_cleanup_interrupt(
    tmp_path,
    monkeypatch,
):
    swap, live_path, temp_root = create_swap(tmp_path)
    swap.install()
    durable_remove = checkout._durable_remove
    interrupted = False

    def interrupt_cleanup(path):
        nonlocal interrupted
        durable_remove(path)
        if pathlib.Path(path) == swap.old_path and not interrupted:
            interrupted = True
            raise KeyboardInterrupt

    monkeypatch.setattr(checkout, "_durable_remove", interrupt_cleanup)
    with pytest.raises(KeyboardInterrupt):
        swap.finalize()
    monkeypatch.setattr(checkout, "_durable_remove", durable_remove)

    checkout.DurableCheckoutSwap.load(live_path, temp_root).finalize()
    assert (live_path / "state").read_text() == "new"
    assert list(temp_root.iterdir()) == []


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
@pytest.mark.parametrize("resolution", ["rollback", "finalize"])
def test_checkout_lock_serializes_terminal_resolution(tmp_path, resolution):
    swap, live_path, temp_root = create_swap(tmp_path)
    ready_read, ready_write = os.pipe()
    release_read, release_write = os.pipe()
    acquired_read, acquired_write = os.pipe()

    owner_pid = os.fork()
    if owner_pid == 0:
        os.close(ready_read)
        os.close(release_write)
        os.close(acquired_read)
        os.close(acquired_write)
        with checkout.checkout_lock(live_path, temp_root):
            owned_swap = checkout.DurableCheckoutSwap.load(
                live_path,
                temp_root,
            )
            owned_swap.install()
            if resolution == "finalize":
                owned_swap.mark_commit_started()
            os.write(ready_write, b"1")
            os.read(release_read, 1)
            if resolution == "finalize":
                owned_swap.mark_committed()
                owned_swap.finalize()
            else:
                owned_swap.rollback()
        os._exit(0)

    os.close(ready_write)
    os.close(release_read)
    assert os.read(ready_read, 1) == b"1"

    recovery_pid = os.fork()
    if recovery_pid == 0:
        os.close(ready_read)
        os.close(release_write)
        os.close(acquired_read)
        with checkout.checkout_lock(live_path, temp_root):
            os.write(acquired_write, b"1")
            assert checkout.DurableCheckoutSwap.load(
                live_path,
                temp_root,
            ) is None
        os._exit(0)

    os.close(acquired_write)
    assert select.select([acquired_read], [], [], 0.2)[0] == []
    os.write(release_write, b"1")
    assert os.read(acquired_read, 1) == b"1"
    _, owner_status = os.waitpid(owner_pid, 0)
    _, recovery_status = os.waitpid(recovery_pid, 0)
    assert os.waitstatus_to_exitcode(owner_status) == 0
    assert os.waitstatus_to_exitcode(recovery_status) == 0
    expected_state = "new" if resolution == "finalize" else "old"
    assert (live_path / "state").read_text() == expected_state


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_checkout_barrier_blocks_writer_after_reader_scan(tmp_path):
    temp_root = tmp_path / "dojos" / "tmp"
    temp_root.mkdir(parents=True)
    reader_ready_read, reader_ready_write = os.pipe()
    release_reader_read, release_reader_write = os.pipe()
    writer_acquired_read, writer_acquired_write = os.pipe()

    reader_pid = os.fork()
    if reader_pid == 0:
        os.close(reader_ready_read)
        os.close(release_reader_write)
        os.close(writer_acquired_read)
        os.close(writer_acquired_write)
        with checkout.checkout_barrier(temp_root, exclusive=False):
            assert checkout.DurableCheckoutSwap.pending_live_names(
                temp_root
            ) == ()
            os.write(reader_ready_write, b"1")
            os.read(release_reader_read, 1)
        os._exit(0)

    os.close(reader_ready_write)
    os.close(release_reader_read)
    assert os.read(reader_ready_read, 1) == b"1"

    writer_pid = os.fork()
    if writer_pid == 0:
        os.close(reader_ready_read)
        os.close(release_reader_write)
        os.close(writer_acquired_read)
        with checkout.checkout_barrier(temp_root, exclusive=True):
            os.write(writer_acquired_write, b"1")
        os._exit(0)

    os.close(writer_acquired_write)
    assert select.select([writer_acquired_read], [], [], 0.2)[0] == []
    os.write(release_reader_write, b"1")
    assert os.read(writer_acquired_read, 1) == b"1"
    _, reader_status = os.waitpid(reader_pid, 0)
    _, writer_status = os.waitpid(writer_pid, 0)
    assert os.waitstatus_to_exitcode(reader_status) == 0
    assert os.waitstatus_to_exitcode(writer_status) == 0


def test_checkout_swap_rejects_unexpected_journal_fields_and_phases(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    journal = json.loads(swap.journal_path.read_text())
    journal["unexpected"] = True
    swap.journal_path.write_text(json.dumps(journal, sort_keys=True))
    with pytest.raises(RuntimeError, match="journal fields"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)

    journal.pop("unexpected")
    journal["phase"] = "unknown"
    swap.journal_path.write_text(json.dumps(journal, sort_keys=True))
    with pytest.raises(RuntimeError, match="journal phase"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)

    journal.pop("live_path")
    swap.journal_path.write_text(json.dumps(journal, sort_keys=True))
    with pytest.raises(RuntimeError, match="journal fields"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)


def test_checkout_swap_rejects_oversized_duplicate_and_noncanonical_json(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    canonical_journal = swap.journal_path.read_text()
    swap.journal_path.write_text(
        " " * (checkout.CHECKOUT_JOURNAL_MAX_BYTES + 1)
    )
    with pytest.raises(RuntimeError, match="too large"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)

    duplicate_journal = canonical_journal[:-1] + ', "phase": "prepared"}'
    swap.journal_path.write_text(duplicate_journal)
    with pytest.raises(RuntimeError, match="Duplicate"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)

    swap.journal_path.write_text(
        json.dumps(json.loads(canonical_journal), sort_keys=True, indent=2)
    )
    with pytest.raises(RuntimeError, match="not canonical"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)


def test_checkout_swap_rejects_self_transition_token(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    journal = json.loads(swap.journal_path.read_text())
    journal["previous_token"] = journal["token"]
    swap.journal_path.write_text(json.dumps(journal, sort_keys=True))

    with pytest.raises(RuntimeError, match="transition to itself"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)


def test_checkout_swap_rejects_managed_symlinks(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    journal_data = swap.journal_path.read_text()
    swap.journal_path.unlink()
    target = temp_root / "journal-target"
    target.write_text(journal_data)
    swap.journal_path.symlink_to(target)

    with pytest.raises(RuntimeError, match="Unsafe managed checkout path"):
        checkout.DurableCheckoutSwap.load(live_path, temp_root)


def test_checkout_swap_rejects_orphaned_and_ambiguous_artifacts(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    orphan_token = "1" * 32
    orphan_path = swap.journal_path.parent / f"87654321-{orphan_token}"
    orphan_path.mkdir()
    with pytest.raises(RuntimeError, match="Orphaned"):
        checkout.DurableCheckoutSwap.pending_live_names(temp_root)

    orphan_path.rmdir()
    ambiguous_path = swap.journal_path.parent / (
        f"{live_path.name}-{orphan_token}"
    )
    ambiguous_path.mkdir()
    with pytest.raises(RuntimeError, match="Ambiguous"):
        checkout.DurableCheckoutSwap.pending_live_names(temp_root)


def test_checkout_swap_caps_all_recovery_artifacts(tmp_path):
    temp_root = tmp_path / "dojos" / "tmp"
    journal_root = temp_root / "updates"
    journal_root.mkdir(parents=True)
    for artifact_index in range(
        checkout.CHECKOUT_RECOVERY_ARTIFACT_LIMIT + 1
    ):
        live_name = f"{artifact_index % 0x100000000:08x}"
        token = f"{artifact_index:032x}"
        (journal_root / f"{live_name}-{token}").mkdir()

    with pytest.raises(RuntimeError, match="Too many checkout recovery artifacts"):
        checkout.DurableCheckoutSwap.pending_live_names(temp_root)


def test_checkout_swap_preserves_both_trees_on_path_ambiguity(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    swap.install()
    (live_path / "state").write_text("unexpected")
    subprocess.run(["git", "-C", str(live_path), "add", "state"], check=True)
    subprocess.run(
        ["git", "-C", str(live_path), "commit", "-m", "unexpected"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(RuntimeError, match="Unexpected live checkout"):
        swap.rollback()
    assert (live_path / "state").read_text() == "unexpected"
    assert (swap.old_path / "state").read_text() == "old"
    assert swap.journal_path.exists()


def test_checkout_swap_rejects_same_head_new_content_mutation(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    swap.install()
    (live_path / "state").write_text("mutated without a commit")

    with pytest.raises(RuntimeError, match="Unexpected live checkout"):
        swap.rollback()
    assert (live_path / "state").read_text() == "mutated without a commit"
    assert (swap.old_path / "state").read_text() == "old"
    assert swap.journal_path.exists()


def test_checkout_swap_rejects_same_head_old_content_mutation(tmp_path):
    swap, live_path, temp_root = create_swap(tmp_path)
    swap.install()
    (swap.old_path / "state").write_text("mutated without a commit")

    with pytest.raises(RuntimeError, match="Preserved checkout"):
        swap.rollback()
    assert (live_path / "state").read_text() == "new"
    assert (swap.old_path / "state").read_text() == (
        "mutated without a commit"
    )
    assert swap.journal_path.exists()


def test_bounded_checkout_probe_kills_and_reaps_process_group(monkeypatch):
    process = subprocess.Popen(
        ["sh", "-c", "sleep 30"],
        start_new_session=True,
    )

    class StartedProcess:
        pid = process.pid
        returncode = None

        def communicate(self, timeout=None):
            try:
                return process.communicate(timeout=timeout)
            finally:
                self.returncode = process.returncode

    monkeypatch.setattr(checkout.subprocess, "Popen", lambda *args, **kwargs: StartedProcess())
    with pytest.raises(subprocess.TimeoutExpired):
        checkout._bounded_output(["ignored"], 0.05)
    assert process.poll() is not None
