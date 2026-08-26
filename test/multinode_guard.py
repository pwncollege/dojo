from pathlib import Path

import pytest

from tiers import MULTINODE_TESTS


REQUIRED_TESTS = frozenset({
    "test_homefs_semantics.py::test_multinode_homes_are_lazy_worker_local_btrfs_volumes",
    "test_homefs_semantics.py::test_multinode_home_quota_is_enforced_on_owning_worker",
    "test_homefs_semantics.py::test_multinode_home_persists_and_snapshots_through_coordinator",
    "test_homefs_semantics.py::test_multinode_cross_node_overlay_is_current_isolated_and_ephemeral",
    "test_homefs_semantics.py::test_multinode_coordinator_rejects_competing_active_host",
    "test_homefs_semantics.py::test_multinode_legacy_active_owner_reconciles_without_replacing_subvolume",
})

if not REQUIRED_TESTS <= MULTINODE_TESTS:
    missing_markers = sorted(REQUIRED_TESTS - MULTINODE_TESTS)
    raise pytest.UsageError(f"Required multinode tests lack the multinode marker: {missing_markers}")

passed_tests = set()


def test_key(nodeid):
    parts = nodeid.split("::", 2)
    if len(parts) < 2:
        return ""
    return f"{Path(parts[0]).name}::{parts[1].split('[', 1)[0]}"


def pytest_runtest_logreport(report):
    if report.when == "call" and report.passed:
        passed_tests.add(test_key(report.nodeid))


def pytest_sessionfinish(session, exitstatus):
    missing_tests = sorted(REQUIRED_TESTS - passed_tests)
    if not missing_tests:
        return
    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is not None:
        terminal_reporter.write_sep("=", "required multinode homefs tests did not pass")
        for missing_test in missing_tests:
            terminal_reporter.write_line(missing_test)
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
