import os
import subprocess
from pathlib import Path

CERTIFICATES_SCRIPT = Path(__file__).parents[1] / "dojo" / "dojo-certificates"


def _write_executable(path, contents):
    path.write_text(contents)
    path.chmod(0o755)


def _generate_certificate(certificate_path, private_key_path, domains):
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:P-256",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-subj",
            f"/CN={domains[0]}",
            "-addext",
            f"subjectAltName={','.join(f'DNS:{domain}' for domain in domains)}",
            "-keyout",
            private_key_path,
            "-out",
            certificate_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_config(data_directory):
    (data_directory / "config.env").write_text(
        "DOJO_ENV=production\n"
        "DOJO_HOST=dojo.example\n"
        "WORKSPACE_HOST=workspace.dojo.example\n"
        "WORKSPACE_NODE=0\n"
    )


def _script_environment(data_directory, runtime_directory, executable_directory=None):
    environment = os.environ.copy()
    if executable_directory:
        environment["PATH"] = f"{executable_directory}:{environment['PATH']}"
    environment.update(
        {
            "DOJO_CERTIFICATES_DATA_DIRECTORY": str(data_directory),
            "DOJO_CERTIFICATES_RUNTIME_DIRECTORY": str(runtime_directory),
        }
    )
    return environment


def test_bootstrap_adopts_legacy_primary_domain_certificate(tmp_path):
    data_directory = tmp_path / "data"
    runtime_directory = tmp_path / "run"
    legacy_directory = data_directory / "acme"
    data_directory.mkdir()
    legacy_directory.mkdir()
    _write_config(data_directory)

    legacy_certificate = legacy_directory / "legacy.crt"
    legacy_private_key = legacy_directory / "legacy.key"
    _generate_certificate(legacy_certificate, legacy_private_key, ["dojo.example"])
    expected_certificate = legacy_certificate.read_bytes()
    expected_private_key = legacy_private_key.read_bytes()

    result = subprocess.run(
        [CERTIFICATES_SCRIPT],
        capture_output=True,
        check=False,
        env=_script_environment(data_directory, runtime_directory),
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    live_directory = data_directory / "acme" / "live"
    live_certificate = live_directory / "fullchain.pem"
    live_private_key = live_directory / "privkey.pem"
    assert live_certificate.read_bytes() == expected_certificate
    assert live_private_key.read_bytes() == expected_private_key
    assert live_certificate.stat().st_mode & 0o777 == 0o644
    assert live_private_key.stat().st_mode & 0o777 == 0o600
    assert (runtime_directory / "tls" / "fullchain.pem").resolve() == live_certificate
    assert (runtime_directory / "tls" / "privkey.pem").resolve() == live_private_key


def test_acme_retries_run_and_reissues_incompatible_certificate(tmp_path):
    data_directory = tmp_path / "data"
    runtime_directory = tmp_path / "run"
    executable_directory = tmp_path / "bin"
    data_directory.mkdir()
    executable_directory.mkdir()
    _write_config(data_directory)

    issued_certificate_source = tmp_path / "issued.crt"
    issued_private_key_source = tmp_path / "issued.key"
    _generate_certificate(
        issued_certificate_source,
        issued_private_key_source,
        ["dojo.example", "future.dojo.example", "workspace.dojo.example"],
    )
    incompatible_certificate = tmp_path / "incompatible.crt"
    incompatible_private_key = tmp_path / "incompatible.key"
    _generate_certificate(
        incompatible_certificate, incompatible_private_key, ["dojo.example"]
    )

    lego_log = tmp_path / "lego.log"
    lego_arguments_log = tmp_path / "lego-arguments.log"
    lego_failed_once = tmp_path / "lego-failed-once"
    systemctl_log = tmp_path / "systemctl.log"
    _write_executable(
        executable_directory / "getent",
        """#!/bin/sh
[ "${UNRESOLVED_DOMAIN:-}" != "$2" ]
""",
    )
    _write_executable(
        executable_directory / "systemctl",
        """#!/bin/sh
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
""",
    )
    _write_executable(
        executable_directory / "lego",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$LEGO_ARGUMENTS_LOG"
lego_path=
lego_action=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --path) lego_path="$2"; shift 2 ;;
        run|renew) lego_action="$1"; break ;;
        *) shift ;;
    esac
done
printf '%s\n' "$lego_action" >> "$LEGO_LOG"
if [ "${LEGO_FAIL_AFTER_WRITE:-false}" = true ]; then
    mkdir -p "$lego_path/certificates"
    cp "$ISSUED_CERTIFICATE_SOURCE" "$lego_path/certificates/dojo.example.crt"
    cp "$ISSUED_PRIVATE_KEY_SOURCE" "$lego_path/certificates/dojo.example.key"
    exit 1
fi
if [ "$lego_action" = run ] && [ ! -e "$LEGO_FAILED_ONCE" ]; then
    mkdir -p "$lego_path/accounts"
    : > "$LEGO_FAILED_ONCE"
    exit 1
fi
mkdir -p "$lego_path/certificates"
cp "$ISSUED_CERTIFICATE_SOURCE" "$lego_path/certificates/dojo.example.crt"
cp "$ISSUED_PRIVATE_KEY_SOURCE" "$lego_path/certificates/dojo.example.key"
""",
    )

    environment = _script_environment(
        data_directory, runtime_directory, executable_directory
    )
    environment.update(
        {
            "ISSUED_CERTIFICATE_SOURCE": str(issued_certificate_source),
            "ISSUED_PRIVATE_KEY_SOURCE": str(issued_private_key_source),
            "LEGO_ARGUMENTS_LOG": str(lego_arguments_log),
            "LEGO_FAILED_ONCE": str(lego_failed_once),
            "LEGO_LOG": str(lego_log),
            "SYSTEMCTL_LOG": str(systemctl_log),
        }
    )

    unresolved_environment = environment.copy()
    unresolved_environment["UNRESOLVED_DOMAIN"] = "future.dojo.example"
    unresolved = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=unresolved_environment,
        text=True,
        timeout=10,
    )
    assert unresolved.returncode != 0
    assert "future.dojo.example" in unresolved.stderr
    assert not lego_log.exists()

    first_attempt = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )
    assert first_attempt.returncode != 0
    assert lego_log.read_text().splitlines() == ["run"]
    assert (data_directory / "acme" / "lego" / "accounts").is_dir()

    second_attempt = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )
    assert second_attempt.returncode == 0, second_attempt.stdout + second_attempt.stderr
    assert lego_log.read_text().splitlines() == ["run", "run"]
    assert (
        data_directory / "acme" / "live" / "fullchain.pem"
    ).read_bytes() == issued_certificate_source.read_bytes()
    assert (
        data_directory / "acme" / "live" / "privkey.pem"
    ).read_bytes() == issued_private_key_source.read_bytes()
    assert systemctl_log.read_text().splitlines() == ["reload dojo-nginx.service"]

    incompatible_environment = environment.copy()
    incompatible_environment.update(
        {
            "ISSUED_CERTIFICATE_SOURCE": str(incompatible_certificate),
            "ISSUED_PRIVATE_KEY_SOURCE": str(incompatible_private_key),
            "LEGO_FAIL_AFTER_WRITE": "true",
        }
    )
    third_attempt = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=incompatible_environment,
        text=True,
        timeout=10,
    )
    assert third_attempt.returncode != 0
    assert lego_log.read_text().splitlines() == ["run", "run", "renew"]
    assert (
        data_directory / "acme" / "live" / "fullchain.pem"
    ).read_bytes() == issued_certificate_source.read_bytes()
    assert systemctl_log.read_text().splitlines() == ["reload dojo-nginx.service"]

    fourth_attempt = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )
    assert fourth_attempt.returncode == 0, fourth_attempt.stdout + fourth_attempt.stderr
    assert lego_log.read_text().splitlines() == ["run", "run", "renew", "run"]

    fifth_attempt = subprocess.run(
        [CERTIFICATES_SCRIPT, "renew"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=10,
    )
    assert fifth_attempt.returncode == 0, fifth_attempt.stdout + fifth_attempt.stderr
    assert lego_log.read_text().splitlines() == [
        "run",
        "run",
        "renew",
        "run",
        "renew",
    ]

    for lego_arguments in lego_arguments_log.read_text().splitlines():
        assert "--domains dojo.example" in lego_arguments
        assert "--domains future.dojo.example" in lego_arguments
        assert "--domains workspace.dojo.example" in lego_arguments
