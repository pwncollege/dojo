import contextlib
import fcntl
import json
import hashlib
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import uuid


CHECKOUT_SWAP_VERSION = 1
CHECKOUT_HEAD_TIMEOUT = 15
CHECKOUT_JOURNAL_MAX_BYTES = 16384
CHECKOUT_RECOVERY_LIMIT = 16
CHECKOUT_RECOVERY_ARTIFACT_LIMIT = CHECKOUT_RECOVERY_LIMIT * 3
CHECKOUT_SWAP_FIELDS = {
    "version",
    "token",
    "previous_token",
    "phase",
    "live_path",
    "staged_path",
    "operation_path",
    "new_path",
    "old_path",
    "had_live",
    "new_head",
    "new_digest",
    "old_head",
    "old_digest",
    "recalculation_plan",
}
CHECKOUT_SWAP_PHASES = {
    "prepared",
    "new_preserved",
    "old_preserved",
    "live_installed",
    "commit_started",
    "committed",
    "rollback_proven",
    "finalize_proven",
    "events_published",
}


def _lexists(path):
    return os.path.lexists(path)


def _valid_digest(value):
    return (
        isinstance(value, str) and
        len(value) == 64 and
        all(character in "0123456789abcdef" for character in value)
    )


def _valid_recalculation_plan(value):
    return value == {"transactional_outbox": True}


def _assert_plain_path(path, expected_type, missing=False):
    path = pathlib.Path(path)
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        if missing:
            return
        raise RuntimeError(f"Managed checkout path is missing: {path}")
    if stat.S_ISLNK(path_stat.st_mode) or not expected_type(path_stat.st_mode):
        raise RuntimeError(f"Unsafe managed checkout path: {path}")


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _tree_digest(path, *, durable=False):
    _assert_plain_path(path, stat.S_ISDIR)
    digest = hashlib.sha256()
    directory_paths = []
    for root, directories, files in os.walk(path, topdown=True):
        root_path = pathlib.Path(root)
        directories.sort()
        files.sort()
        directory_paths.append(root_path)
        traversed_directories = []
        for directory in directories:
            directory_path = root_path / directory
            relative_path = os.fsencode(
                directory_path.relative_to(path).as_posix()
            )
            if directory_path.is_symlink():
                digest.update(b"L\0" + relative_path + b"\0")
                digest.update(os.fsencode(os.readlink(directory_path)))
            else:
                traversed_directories.append(directory)
        directories[:] = traversed_directories
        for filename in files:
            file_path = root_path / filename
            relative_path = os.fsencode(file_path.relative_to(path).as_posix())
            if file_path.is_symlink():
                digest.update(b"L\0" + relative_path + b"\0")
                digest.update(os.fsencode(os.readlink(file_path)))
                continue
            descriptor = os.open(
                file_path,
                os.O_RDONLY |
                getattr(os, "O_NOFOLLOW", 0) |
                getattr(os, "O_NONBLOCK", 0),
            )
            try:
                file_stat = os.fstat(descriptor)
                if not stat.S_ISREG(file_stat.st_mode):
                    raise RuntimeError("Unsupported staged checkout file type")
                digest.update(b"F\0" + relative_path + b"\0")
                digest.update(str(stat.S_IMODE(file_stat.st_mode)).encode())
                digest.update(b"\0")
                while True:
                    content = os.read(descriptor, 1024 * 1024)
                    if not content:
                        break
                    digest.update(content)
                if durable:
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
        relative_root = os.fsencode(root_path.relative_to(path).as_posix())
        digest.update(b"D\0" + relative_root + b"\0")
    if durable:
        for directory_path in reversed(directory_paths):
            _fsync_directory(directory_path)
    return digest.hexdigest()


def _fsync_tree(path):
    return _tree_digest(path, durable=True)


@contextlib.contextmanager
def _filesystem_lock(lock_path, *, exclusive):
    lock_path = pathlib.Path(lock_path)
    _assert_plain_path(lock_path.parent, stat.S_ISDIR)
    descriptor = os.open(
        lock_path,
        os.O_RDWR |
        os.O_CREAT |
        getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        lock_stat = os.fstat(descriptor)
        path_stat = lock_path.lstat()
        if not (
            stat.S_ISREG(lock_stat.st_mode) and
            lock_stat.st_dev == path_stat.st_dev and
            lock_stat.st_ino == path_stat.st_ino
        ):
            raise RuntimeError("Unsafe checkout lock file")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, operation)
        path_stat = lock_path.lstat()
        if not (
            lock_stat.st_dev == path_stat.st_dev and
            lock_stat.st_ino == path_stat.st_ino
        ):
            raise RuntimeError("Checkout lock file changed while acquiring lock")
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _checkout_lock_root(temp_root):
    temp_root = pathlib.Path(temp_root)
    _assert_plain_path(temp_root, stat.S_ISDIR)
    lock_root = temp_root / "locks"
    lock_root.mkdir(exist_ok=True)
    _assert_plain_path(lock_root, stat.S_ISDIR)
    return lock_root


@contextlib.contextmanager
def checkout_barrier(temp_root, *, exclusive):
    lock_root = _checkout_lock_root(temp_root)
    with _filesystem_lock(
        lock_root / "checkout-barrier.lock",
        exclusive=exclusive,
    ):
        yield


@contextlib.contextmanager
def checkout_lock(live_path, temp_root):
    live_path = pathlib.Path(live_path)
    temp_root = pathlib.Path(temp_root)
    lock_root = _checkout_lock_root(temp_root)
    if (
        live_path.parent != temp_root.parent or
        not re.fullmatch(r"[0-9a-f]{8}", live_path.name)
    ):
        raise RuntimeError("Invalid managed checkout name")
    lock_path = lock_root / f"{live_path.name}.lock"
    with _filesystem_lock(lock_path, exclusive=True):
        yield


def _durable_rename(source, destination):
    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    _assert_plain_path(source, stat.S_ISDIR)
    if _lexists(destination):
        raise RuntimeError(f"Checkout swap destination already exists: {destination}")
    os.rename(source, destination)
    _fsync_directory(source.parent)
    if destination.parent != source.parent:
        _fsync_directory(destination.parent)


def _durable_remove(path):
    path = pathlib.Path(path)
    if not _lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    _fsync_directory(path.parent)


def bounded_run(command, *, env=None, timeout=None, text=False):
    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
        text=text,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode,
            command,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _bounded_output(command, timeout):
    return bounded_run(command, timeout=timeout, text=True).stdout


def _checkout_head(path):
    _assert_plain_path(path, stat.S_ISDIR)
    return _bounded_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        CHECKOUT_HEAD_TIMEOUT,
    ).strip()


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeError("Duplicate checkout swap journal field")
        result[key] = value
    return result


class DurableCheckoutSwap:
    def __init__(self, data, journal_path):
        if not isinstance(data, dict) or set(data) != CHECKOUT_SWAP_FIELDS:
            raise RuntimeError("Invalid checkout swap journal fields")
        path_fields = (
            "live_path",
            "staged_path",
            "operation_path",
            "new_path",
            "old_path",
        )
        if not all(isinstance(data.get(field), str) for field in path_fields):
            raise RuntimeError("Invalid checkout swap journal paths")
        self.data = data
        self.journal_path = pathlib.Path(journal_path)
        self.live_path = pathlib.Path(data["live_path"])
        self.staged_path = pathlib.Path(data["staged_path"])
        self.operation_path = pathlib.Path(data["operation_path"])
        self.new_path = pathlib.Path(data["new_path"])
        self.old_path = pathlib.Path(data["old_path"])
        self.temp_root = self.journal_path.parent.parent

    @classmethod
    def prepare(cls, staged_path):
        staged_path = pathlib.Path(staged_path)
        _assert_plain_path(staged_path, stat.S_ISDIR)
        staged_stat = staged_path.stat()
        new_head = _checkout_head(staged_path)
        new_digest = _fsync_tree(staged_path)
        return {
            "path": str(staged_path),
            "device": staged_stat.st_dev,
            "inode": staged_stat.st_ino,
            "new_head": new_head,
            "new_digest": new_digest,
        }

    @classmethod
    def prepare_existing(cls, live_path):
        live_path = pathlib.Path(live_path)
        if not _lexists(live_path):
            return None
        _assert_plain_path(live_path, stat.S_ISDIR)
        live_stat = live_path.stat()
        old_head = _checkout_head(live_path)
        old_digest = _fsync_tree(live_path)
        return {
            "path": str(live_path),
            "device": live_stat.st_dev,
            "inode": live_stat.st_ino,
            "old_head": old_head,
            "old_digest": old_digest,
        }

    @classmethod
    def journal_path_for(cls, live_path, temp_root):
        return pathlib.Path(temp_root) / "updates" / f"{pathlib.Path(live_path).name}.json"

    @classmethod
    def pending_live_names(cls, temp_root):
        temp_root = pathlib.Path(temp_root)
        _assert_plain_path(temp_root, stat.S_ISDIR)
        journal_root = temp_root / "updates"
        if not _lexists(journal_root):
            return ()
        _assert_plain_path(journal_root, stat.S_ISDIR)
        journal_names = set()
        operation_tokens = {}
        temporary_tokens = {}
        artifact_count = 0
        for path in journal_root.iterdir():
            artifact_count += 1
            if artifact_count > CHECKOUT_RECOVERY_ARTIFACT_LIMIT:
                raise RuntimeError("Too many checkout recovery artifacts")
            if match := re.fullmatch(r"([0-9a-f]{8})\.json", path.name):
                _assert_plain_path(path, stat.S_ISREG)
                journal_names.add(match.group(1))
            elif match := re.fullmatch(
                r"([0-9a-f]{8})-([0-9a-f]{32})",
                path.name,
            ):
                _assert_plain_path(path, stat.S_ISDIR)
                operation_tokens.setdefault(match.group(1), []).append(
                    match.group(2)
                )
            elif match := re.fullmatch(
                r"([0-9a-f]{8})\.json\.([0-9a-f]{32})\.tmp",
                path.name,
            ):
                _assert_plain_path(path, stat.S_ISREG)
                temporary_tokens.setdefault(match.group(1), []).append(
                    match.group(2)
                )
            else:
                raise RuntimeError("Unexpected checkout recovery artifact")
        if len(journal_names) > CHECKOUT_RECOVERY_LIMIT:
            raise RuntimeError("Too many pending checkout recoveries")
        artifact_names = set(operation_tokens) | set(temporary_tokens)
        if not artifact_names <= journal_names:
            raise RuntimeError("Orphaned checkout recovery artifact")
        for live_name in journal_names:
            swap = cls.load(temp_root.parent / live_name, temp_root)
            if any(
                tokens and tokens != [swap.token]
                for tokens in (
                    operation_tokens.get(live_name, []),
                    temporary_tokens.get(live_name, []),
                )
            ):
                raise RuntimeError("Ambiguous checkout recovery artifacts")
        return tuple(sorted(journal_names))

    @classmethod
    def begin(
        cls,
        live_path,
        staged_path,
        temp_root,
        previous_token,
        prepared,
        prepared_live,
        recalculation_plan,
    ):
        live_path = pathlib.Path(live_path)
        staged_path = pathlib.Path(staged_path)
        temp_root = pathlib.Path(temp_root)
        _assert_plain_path(temp_root, stat.S_ISDIR)
        _assert_plain_path(staged_path, stat.S_ISDIR)
        _assert_plain_path(live_path, stat.S_ISDIR, missing=True)
        staged_stat = staged_path.stat()
        if prepared != {
            "path": str(staged_path),
            "device": staged_stat.st_dev,
            "inode": staged_stat.st_ino,
            "new_head": prepared.get("new_head"),
            "new_digest": prepared.get("new_digest"),
        }:
            raise RuntimeError("Staged checkout does not match durable preparation")
        if _checkout_head(staged_path) != prepared["new_head"]:
            raise RuntimeError("Staged checkout changed after durable preparation")
        had_live = _lexists(live_path)
        if had_live != (prepared_live is not None):
            raise RuntimeError("Live checkout changed after durable preparation")
        if had_live:
            live_stat = live_path.stat()
            if prepared_live != {
                "path": str(live_path),
                "device": live_stat.st_dev,
                "inode": live_stat.st_ino,
                "old_head": prepared_live.get("old_head"),
                "old_digest": prepared_live.get("old_digest"),
            }:
                raise RuntimeError("Live checkout does not match durable preparation")
            if _checkout_head(live_path) != prepared_live["old_head"]:
                raise RuntimeError("Live checkout changed after durable preparation")
        journal_path = cls.journal_path_for(live_path, temp_root)
        if _lexists(journal_path):
            raise RuntimeError(f"Unrecovered checkout swap exists for {live_path}")
        journal_path.parent.mkdir(exist_ok=True)
        _assert_plain_path(journal_path.parent, stat.S_ISDIR)
        token = uuid.uuid4().hex
        operation_path = journal_path.parent / f"{live_path.name}-{token}"
        operation_path.mkdir()
        _fsync_directory(temp_root)
        _fsync_directory(journal_path.parent)
        try:
            data = {
                "version": CHECKOUT_SWAP_VERSION,
                "token": token,
                "previous_token": previous_token,
                "phase": "prepared",
                "live_path": str(live_path),
                "staged_path": str(staged_path),
                "operation_path": str(operation_path),
                "new_path": str(operation_path / "new"),
                "old_path": str(operation_path / "old"),
                "had_live": had_live,
                "new_head": prepared["new_head"],
                "new_digest": prepared["new_digest"],
                "old_head": (
                    prepared_live["old_head"] if prepared_live else None
                ),
                "old_digest": (
                    prepared_live["old_digest"] if prepared_live else None
                ),
                "recalculation_plan": recalculation_plan,
            }
            swap = cls(data, journal_path)
            swap._validate()
            swap._write_journal()
        except BaseException:
            _durable_remove(journal_path.with_name(
                f"{journal_path.name}.{token}.tmp"
            ))
            _durable_remove(journal_path)
            _durable_remove(operation_path)
            try:
                journal_path.parent.rmdir()
                _fsync_directory(temp_root)
            except OSError:
                pass
            raise
        return swap

    @classmethod
    def load(cls, live_path, temp_root):
        journal_path = cls.journal_path_for(live_path, temp_root)
        if not _lexists(journal_path):
            return None
        _assert_plain_path(temp_root, stat.S_ISDIR)
        _assert_plain_path(journal_path.parent, stat.S_ISDIR)
        _assert_plain_path(journal_path, stat.S_ISREG)
        descriptor = os.open(
            journal_path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        with os.fdopen(descriptor, "rb") as journal_file:
            journal_data = journal_file.read(CHECKOUT_JOURNAL_MAX_BYTES + 1)
        if len(journal_data) > CHECKOUT_JOURNAL_MAX_BYTES:
            raise RuntimeError("Checkout swap journal is too large")
        try:
            journal_text = journal_data.decode("utf-8")
            data = json.loads(
                journal_text,
                object_pairs_hook=_unique_json_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("Invalid checkout swap journal JSON") from error
        if not isinstance(data, dict):
            raise RuntimeError("Checkout swap journal must be an object")
        if journal_text != json.dumps(data, sort_keys=True):
            raise RuntimeError("Checkout swap journal is not canonical")
        swap = cls(data, journal_path)
        swap._validate()
        return swap

    @property
    def token(self):
        return self.data["token"]

    def _validate(self):
        if set(self.data) != CHECKOUT_SWAP_FIELDS:
            raise RuntimeError("Invalid checkout swap journal fields")
        if self.data.get("version") != CHECKOUT_SWAP_VERSION:
            raise RuntimeError("Unsupported checkout swap journal version")
        if self.data.get("phase") not in CHECKOUT_SWAP_PHASES:
            raise RuntimeError("Invalid checkout swap journal phase")
        try:
            token = uuid.UUID(hex=self.data["token"]).hex
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("Invalid checkout swap token") from error
        previous_token = self.data.get("previous_token")
        if previous_token is not None:
            try:
                previous_token = uuid.UUID(hex=previous_token).hex
            except (TypeError, ValueError) as error:
                raise RuntimeError("Invalid previous checkout swap token") from error
        if previous_token == token:
            raise RuntimeError("Checkout swap token cannot transition to itself")
        expected_journal_path = (
            self.temp_root / "updates" / f"{self.live_path.name}.json"
        )
        expected_operation_path = (
            expected_journal_path.parent / f"{self.live_path.name}-{token}"
        )
        valid = all((
            self.journal_path == expected_journal_path,
            self.operation_path == expected_operation_path,
            self.new_path == expected_operation_path / "new",
            self.old_path == expected_operation_path / "old",
            self.staged_path.parent == self.temp_root,
            self.live_path.parent == self.temp_root.parent,
            type(self.data.get("had_live")) is bool,
            isinstance(self.data.get("new_head"), str),
            _valid_digest(self.data.get("new_digest")),
            (
                isinstance(self.data.get("old_head"), str) and
                _valid_digest(self.data.get("old_digest"))
            ) if self.data.get("had_live") else (
                self.data.get("old_head") is None and
            self.data.get("old_digest") is None
            ),
            _valid_recalculation_plan(self.data.get("recalculation_plan")),
            previous_token == self.data.get("previous_token"),
            all(
                path.is_absolute() and str(path) == self.data[field]
                for field, path in (
                    ("live_path", self.live_path),
                    ("staged_path", self.staged_path),
                    ("operation_path", self.operation_path),
                    ("new_path", self.new_path),
                    ("old_path", self.old_path),
                )
            ),
        ))
        if not valid:
            raise RuntimeError("Invalid checkout swap journal paths")
        _assert_plain_path(self.temp_root, stat.S_ISDIR)
        _assert_plain_path(self.journal_path.parent, stat.S_ISDIR)
        _assert_plain_path(self.journal_path, stat.S_ISREG, missing=True)
        _assert_plain_path(self.operation_path, stat.S_ISDIR, missing=True)
        for path in (
            self.staged_path,
            self.new_path,
            self.old_path,
            self.live_path,
        ):
            _assert_plain_path(path, stat.S_ISDIR, missing=True)

    def _write_journal(self):
        temporary_path = self.journal_path.with_name(
            f"{self.journal_path.name}.{self.token}.tmp"
        )
        if _lexists(temporary_path):
            _assert_plain_path(temporary_path, stat.S_ISREG)
            _durable_remove(temporary_path)
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w") as journal_file:
            json.dump(self.data, journal_file, sort_keys=True)
            journal_file.flush()
            os.fsync(journal_file.fileno())
        os.replace(temporary_path, self.journal_path)
        _fsync_directory(self.journal_path.parent)

    def _set_phase(self, phase):
        self.data["phase"] = phase
        self._write_journal()

    def install(self):
        _durable_rename(self.staged_path, self.new_path)
        self._set_phase("new_preserved")
        if self.data["had_live"]:
            _durable_rename(self.live_path, self.old_path)
            self._set_phase("old_preserved")
        elif _lexists(self.live_path):
            raise RuntimeError("Checkout appeared while installing update")
        _durable_rename(self.new_path, self.live_path)
        self._set_phase("live_installed")

    def mark_commit_started(self):
        self._set_phase("commit_started")

    def mark_committed(self):
        self._set_phase("committed")

    def _path_matches(self, path, expected_head, expected_digest):
        if (
            not _lexists(path) or
            expected_head is None or
            expected_digest is None
        ):
            return False
        try:
            return (
                _checkout_head(path) == expected_head and
                _tree_digest(path) == expected_digest
            )
        except (OSError, subprocess.SubprocessError):
            return False

    def rollback(self):
        if self.data["had_live"]:
            if _lexists(self.old_path):
                if not self._path_matches(
                    self.old_path,
                    self.data["old_head"],
                    self.data["old_digest"],
                ):
                    raise RuntimeError("Preserved checkout does not match journal")
                if _lexists(self.live_path):
                    if _lexists(self.new_path):
                        raise RuntimeError("Multiple updated checkout candidates exist")
                    if not self._path_matches(
                        self.live_path,
                        self.data["new_head"],
                        self.data["new_digest"],
                    ):
                        raise RuntimeError("Unexpected live checkout during recovery")
                    _durable_rename(self.live_path, self.new_path)
                _durable_rename(self.old_path, self.live_path)
            elif not _lexists(self.live_path):
                raise RuntimeError("Original checkout is missing during recovery")
            if not self._path_matches(
                self.live_path,
                self.data["old_head"],
                self.data["old_digest"],
            ):
                raise RuntimeError("Restored checkout does not match journal")
        elif _lexists(self.live_path):
            if not self._path_matches(
                self.live_path,
                self.data["new_head"],
                self.data["new_digest"],
            ):
                raise RuntimeError("Unexpected checkout exists during recovery")
            if _lexists(self.new_path):
                raise RuntimeError("Multiple updated checkout candidates exist")
            _durable_rename(self.live_path, self.new_path)
        if self.data["had_live"]:
            if not self._path_matches(
                self.live_path,
                self.data["old_head"],
                self.data["old_digest"],
            ):
                raise RuntimeError("Restored checkout does not match journal")
        elif _lexists(self.live_path):
            raise RuntimeError("Unexpected live checkout during recovery")
        if self.data["phase"] != "rollback_proven":
            self._validate_artifacts()
            self._set_phase("rollback_proven")
        self._remove_artifacts()

    def prove_finalize(self):
        if not self._path_matches(
            self.live_path,
            self.data["new_head"],
            self.data["new_digest"],
        ):
            candidate = next(
                (
                    path
                    for path in (self.new_path, self.staged_path)
                    if self._path_matches(
                        path,
                        self.data["new_head"],
                        self.data["new_digest"],
                    )
                ),
                None,
            )
            if candidate is None:
                raise RuntimeError("Committed checkout is missing during recovery")
            if _lexists(self.live_path):
                if _lexists(self.old_path):
                    raise RuntimeError("Multiple original checkout candidates exist")
                if not self._path_matches(
                    self.live_path,
                    self.data["old_head"],
                    self.data["old_digest"],
                ):
                    raise RuntimeError("Unexpected live checkout during recovery")
                _durable_rename(self.live_path, self.old_path)
            _durable_rename(candidate, self.live_path)
        if not self._path_matches(
            self.live_path,
            self.data["new_head"],
            self.data["new_digest"],
        ):
            raise RuntimeError("Installed checkout does not match journal")
        if self.data["phase"] not in {"finalize_proven", "events_published"}:
            self._validate_artifacts()
            self._set_phase("finalize_proven")

    def mark_events_published(self):
        if self.data["phase"] == "events_published":
            return
        if self.data["phase"] != "finalize_proven":
            raise RuntimeError("Checkout finalization is not proven")
        self._set_phase("events_published")

    def finalize(self):
        self.prove_finalize()
        self._remove_artifacts()

    def _validate_artifacts(self):
        for path in (self.staged_path, self.new_path):
            if _lexists(path) and not self._path_matches(
                path,
                self.data["new_head"],
                self.data["new_digest"],
            ):
                raise RuntimeError("Updated checkout artifact does not match journal")
        if _lexists(self.old_path) and not self._path_matches(
            self.old_path,
            self.data["old_head"],
            self.data["old_digest"],
        ):
            raise RuntimeError("Original checkout artifact does not match journal")
        self._validate_artifact_names()

    def _validate_artifact_names(self):
        if not _lexists(self.operation_path):
            return
        unexpected_paths = {
            path.name
            for path in self.operation_path.iterdir()
            if path not in {self.new_path, self.old_path}
        }
        if unexpected_paths:
            raise RuntimeError("Checkout swap contains unexpected artifacts")

    def _remove_artifacts(self):
        self._validate_artifact_names()
        for path in (self.staged_path, self.new_path, self.old_path):
            if path != self.live_path:
                _durable_remove(path)
        _durable_remove(self.operation_path)
        _durable_remove(self.journal_path.with_name(
            f"{self.journal_path.name}.{self.token}.tmp"
        ))
        _durable_remove(self.journal_path)
        try:
            self.journal_path.parent.rmdir()
            _fsync_directory(self.temp_root)
        except OSError:
            pass
