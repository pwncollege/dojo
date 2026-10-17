import base64
import contextlib
import json
import os
import random
import socket
import string
import struct
import subprocess
import tempfile
import time
import types

import pytest
import requests

from utils import (
    DOJO_SSH_HOST,
    DOJO_URL,
    db_sql,
    dojo_run,
    flask_exec,
    get_outer_container_for,
    get_user_id,
    login,
    parse_csrf_token,
    remove_workspace_container,
    remove_workspace_home,
    start_challenge,
    workspace_run,
)

SSH_KEY_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/ssh_key"
DOJOS_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/dojos"
DOCKER_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/docker"
REGISTER_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/auth/register"

SSH_PORT = int(os.getenv("DOJO_SSH_PORT", "22"))
SSH_BASE_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "PasswordAuthentication=no",
    "-o", "ConnectTimeout=10",
]

ENTER_COMMAND = "/opt/sshd/enter.py"


def random_name(prefix):
    return prefix + "".join(random.choices(string.ascii_lowercase, k=12))


def add_ssh_key(session, ssh_key):
    return session.post(SSH_KEY_ENDPOINT, json={"ssh_key": ssh_key})


def delete_ssh_key(session, ssh_key):
    return session.delete(SSH_KEY_ENDPOINT, json={"ssh_key": normalized(ssh_key)})


def normalized(public_key):
    return " ".join(public_key.split()[:2])


def key_count(user_name):
    return int(db_sql(f"SELECT count(*) FROM ssh_keys WHERE user_id = {get_user_id(user_name)}"))


def stored_key_values(user_name):
    output = db_sql(f"SELECT value FROM ssh_keys WHERE user_id = {get_user_id(user_name)}")
    return output.splitlines()


def authorized_keys_lines():
    return dojo_run("docker", "exec", "sshd", "/opt/sshd/auth.py").stdout.splitlines()


def sshd_agent_sockets():
    result = dojo_run(
        "docker", "exec", "sshd", "find", "/tmp", "-type", "s",
        "-path", "/tmp/ssh-*/agent.*", "-print",
    )
    assert result.returncode == 0, result.stderr
    return set(result.stdout.splitlines())


def offered_key_line(public_key):
    key_type, key_base64 = normalized(public_key).split()
    return dojo_run(
        "docker", "exec", "sshd", "/opt/sshd/auth.py", key_type, key_base64
    ).stdout.strip()


def forced_command_line(user_id, public_key):
    return f'command="{ENTER_COMMAND} user_{user_id}" {normalized(public_key)}'


def assert_onboarding_rejects_command(result):
    assert result.returncode != 0, f"an unlinked key ran a command: {result.stdout!r}"
    combined = result.stdout + result.stderr
    assert "not linked to a pwn.college account" in combined, combined
    assert "hacker" not in result.stdout, result.stdout


def generate_ssh_keys(directory):
    keys = {}
    for name, keygen_args in [
        ("rsa", ["-t", "rsa", "-b", "2048"]),
        ("ed25519", ["-t", "ed25519"]),
        ("ecdsa", ["-t", "ecdsa", "-b", "256"]),
    ]:
        path = os.path.join(directory, name)
        subprocess.run(
            ["ssh-keygen", *keygen_args, "-f", path, "-N", "", "-C", f"{name}@dojo-test-host"],
            check=True, capture_output=True,
        )
        with open(f"{path}.pub") as f:
            keys[name] = {"private_file": path, "public": f.read().strip()}
    return keys


def ssh_run(private_key_file, command=None, *, login_user="hacker", options=(), timeout=45,
            stdin_data=None, term=None):
    args = [
        "ssh", *SSH_BASE_OPTIONS,
        "-i", private_key_file,
        "-p", str(SSH_PORT),
        *options,
        f"{login_user}@{DOJO_SSH_HOST}",
    ]
    if command is not None:
        args.append(command)
    kwargs = dict(capture_output=True, text=True, timeout=timeout)
    if stdin_data is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_data
    if term is not None:
        kwargs["env"] = {**os.environ, "TERM": term}
    return subprocess.run(args, **kwargs)


def openssh_certificate(directory):
    ca = os.path.join(directory, "cert_ca")
    user = os.path.join(directory, "cert_user")
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", ca], check=True, capture_output=True)
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", user], check=True, capture_output=True)
    subprocess.run(["ssh-keygen", "-s", ca, "-I", "dojo-test", "-n", "hacker", f"{user}.pub"],
                   check=True, capture_output=True)
    with open(f"{user}-cert.pub") as f:
        return f.read().strip()


def security_key_line(ed25519_public_key):
    blob = base64.b64decode(ed25519_public_key.split()[1])
    key_type = b"sk-ssh-ed25519@openssh.com"
    remainder = blob[4 + len(b"ssh-ed25519"):]
    raw = struct.pack(">I", len(key_type)) + key_type + remainder
    return f"sk-ssh-ed25519@openssh.com {base64.b64encode(raw).decode()}"


def rfc4716_key(key_type, ecdsa_public_key):
    """Re-wrap an ECDSA key in RFC 4716 form, declaring whatever key type is asked for.

    RFC 4716 carries no plaintext key type beside the blob, so this is the one input
    format where the declared type is not cross-checked against anything.
    """
    blob = base64.b64decode(ecdsa_public_key.split()[1])
    body = blob[4 + len(b"ecdsa-sha2-nistp256"):]
    raw = struct.pack(">I", len(key_type)) + key_type + body
    return ("---- BEGIN SSH2 PUBLIC KEY ----\n"
            + base64.b64encode(raw).decode()
            + "\n---- END SSH2 PUBLIC KEY ----")


def short_rsa_public_key(directory):
    def mpint(value):
        raw = value.to_bytes((value.bit_length() + 8) // 8, "big")
        return struct.pack(">I", len(raw)) + raw

    pem = os.path.join(directory, "short_rsa.pem")
    subprocess.run(["openssl", "genrsa", "-out", pem, "768"], check=True, capture_output=True)
    modulus = subprocess.run(["openssl", "rsa", "-in", pem, "-noout", "-modulus"],
                             check=True, capture_output=True, text=True).stdout.strip().split("=", 1)[1]
    blob = struct.pack(">I", 7) + b"ssh-rsa" + mpint(65537) + mpint(int(modulus, 16))
    return f"ssh-rsa {base64.b64encode(blob).decode()}"


_MINT_TOKEN_SCRIPT = """
import json, os, sys, time
import itsdangerous
from itsdangerous.url_safe import URLSafeTimedSerializer

payload = json.loads(sys.argv[1])
secret = sys.argv[2] or os.environ["DOJO_SSH_SERVICE_KEY"]
backdate = int(sys.argv[3])

class BackdatedSigner(itsdangerous.TimestampSigner):
    def get_timestamp(self):
        return int(time.time()) - backdate

signer = BackdatedSigner if backdate else itsdangerous.TimestampSigner
print(URLSafeTimedSerializer(secret, signer=signer).dumps(payload))
"""

_SSHD_REGISTER_SCRIPT = """
import importlib.util, json, os, sys

spec = importlib.util.spec_from_file_location("onboard", "/opt/sshd/onboard.py")
onboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(onboard)
client = onboard.OnboardingClient(sys.argv[4], sys.argv[5])
result = client.register(sys.argv[1], sys.argv[2], sys.argv[3])
print(json.dumps({
    "api_base": client.api_base,
    "dojo_api": os.environ.get("DOJO_API"),
    "dojo_env": os.environ.get("DOJO_ENV"),
    "scheme": client.scheme,
    "result": result,
}))
"""


def mint_ssh_token(payload, *, secret="", backdate=0):
    result = dojo_run("docker", "exec", "site", "python3", "-c", _MINT_TOKEN_SCRIPT,
                      json.dumps(payload), secret, str(backdate))
    return result.stdout.strip()


def ssh_token_header(payload, **kwargs):
    return {"Authorization": f"Bearer sk-ssh-service-{mint_ssh_token(payload, **kwargs)}"}


def register_request(*, headers, payload, session=None):
    return raw_register_request(headers=headers, session=session, json=payload)


def raw_register_request(*, headers, session=None, **kwargs):
    client = session or requests
    for _ in range(10):
        response = client.post(REGISTER_ENDPOINT, headers=headers, **kwargs)
        if response.status_code != 429:
            return response
        time.sleep(1)
    return response


def user_count(name=None):
    where = "" if name is None else f" WHERE name = '{name}'"
    return int(db_sql(f"SELECT count(*) FROM users{where}"))


def ssh_key_count(value):
    return int(db_sql(f"SELECT count(*) FROM ssh_keys WHERE value = '{normalized(value)}'"))


def config_values(keys):
    output = flask_exec(
        "import json\n"
        "from dojo.models import get_config\n"
        f"print(json.dumps({{key: get_config(key) for key in {keys!r}}}))\n"
    )
    return json.loads(output.strip().splitlines()[-1])


def set_config_values(values):
    flask_exec(
        "from dojo.models import set_config\n"
        f"for key, value in {values!r}.items():\n"
        "    set_config(key, value)\n"
    )


@contextlib.contextmanager
def server_config(**overrides):
    original = config_values(list(overrides))
    set_config_values(overrides)
    if config_values(list(overrides)) != overrides:
        set_config_values(original)
        pytest.skip("this deployment does not propagate config changes made outside the server")
    try:
        yield
    finally:
        set_config_values(original)


def transcript_text(path):
    return path.read_bytes().decode(errors="replace") if path.exists() else ""


def await_transcript(path, expected, process, *, start=0, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        transcript = transcript_text(path)
        if expected in transcript[start:]:
            return transcript
        assert process.poll() is None, transcript[-2000:]
        time.sleep(0.2)
    pytest.fail(f"timed out waiting for {expected!r}: {transcript_text(path)[-2000:]}")


def send_ssh_input(process, value):
    assert process.poll() is None
    process.stdin.write(value)
    process.stdin.flush()


def await_transcript_quiescence(
    transcript, process, *, previous_size=None, quiet_seconds=0.4, timeout=15
):
    last_size = transcript.stat().st_size
    last_change = time.monotonic()
    rendered = previous_size is None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, transcript_text(transcript)[-2000:]
        current_size = transcript.stat().st_size
        if current_size != last_size:
            last_size = current_size
            last_change = time.monotonic()
        if previous_size is not None and current_size > previous_size:
            rendered = True
        if rendered and time.monotonic() - last_change >= quiet_seconds:
            return
        time.sleep(0.1)
    pytest.fail(f"SSH interface did not settle: {transcript_text(transcript)[-2000:]}")


def send_ssh_key_and_await_render(process, transcript, key, timeout=15):
    previous_size = transcript.stat().st_size
    send_ssh_input(process, key)
    await_transcript_quiescence(
        transcript, process, previous_size=previous_size, timeout=timeout
    )


def register_user():
    # Registration is rate limited per client IP and the whole suite shares one IP,
    # so a burst of fixtures can transiently be refused; retry with a fresh name.
    last_error = None
    for _ in range(8):
        name = random_name("sshsem")
        try:
            return name, login(name, name, register=True)
        except AssertionError as error:
            last_error = error
            time.sleep(2)
    raise AssertionError(f"could not register a test user: {last_error}")


@pytest.fixture
def ssh_keys():
    with tempfile.TemporaryDirectory() as directory:
        yield generate_ssh_keys(directory)


@pytest.fixture
def dojo_user():
    yield register_user()


@pytest.fixture
def second_user():
    yield register_user()


@pytest.fixture(scope="module")
def workspace_ssh_user(example_dojo):
    name, session = register_user()
    with tempfile.TemporaryDirectory() as directory:
        keys = generate_ssh_keys(directory)
        for key_type, key in keys.items():
            response = add_ssh_key(session, key["public"])
            assert response.status_code == 200, f"failed to register {key_type} key: {response.text}"
        start_challenge(example_dojo, "hello", "apple", session=session)
        warmup = ssh_run(keys["ed25519"]["private_file"], "true", timeout=60)
        assert warmup.returncode == 0, f"workspace never became reachable over ssh: {warmup.stderr}"
        yield types.SimpleNamespace(name=name, session=session, keys=keys)
    remove_workspace_container(name)


def test_key_normalization_strips_comments_options_and_whitespace(dojo_user, ssh_keys):
    name, session = dojo_user
    rsa = ssh_keys["rsa"]["public"]

    response = add_ssh_key(session, f"  {rsa}  user@laptop with spaces  \n")
    assert response.status_code == 200, f"expected the key to be accepted, got {response.text}"

    values = stored_key_values(name)
    assert values == [normalized(rsa)], f"key was not stored canonicalized: {values}"
    assert len(values[0].split()) == 2, f"stored key is not exactly '<type> <blob>': {values[0]!r}"

    ed25519 = ssh_keys["ed25519"]["public"]
    response = add_ssh_key(session, f'command="/bin/sh -c id > /tmp/pwned",no-pty {ed25519}')
    assert response.status_code == 200, f"expected option-prefixed key to be accepted, got {response.text}"

    values = stored_key_values(name)
    assert sorted(values) == sorted([normalized(rsa), normalized(ed25519)]), values
    assert not any("command=" in value or "no-pty" in value for value in values), \
        f"authorized_keys options survived normalization: {values}"

    response = add_ssh_key(session, f"  {normalized(rsa)}   bob@host-two  ")
    assert response.status_code == 400, "the same key with a different comment must be a duplicate"
    assert "already in use" in response.json()["error"], response.json()
    assert key_count(name) == 2, "duplicate submission must not create another row"


def test_invalid_key_material_rejected(dojo_user, ssh_keys, tmp_path):
    name, session = dojo_user
    ed25519_blob = ssh_keys["ed25519"]["public"].split()[1]

    rejected = {
        "garbage": "not a valid ssh key",
        "type only": "ssh-rsa",
        "truncated blob": "ssh-rsa AAAAB3NzaC1yc2EA",
        "truncated dss blob": "ssh-dss AAAAB3NzaC1kc3MA",
        "non base64": "ssh-rsa AAAAB3NzaC1yc2EA!!!",
        "unknown option": f'totally-bogus-option=1 {ssh_keys["rsa"]["public"]}',
        "type/blob mismatch": f"ssh-rsa {ed25519_blob}",
        "openssh certificate": openssh_certificate(str(tmp_path)),
        "security key": security_key_line(ssh_keys["ed25519"]["public"]),
        "768-bit rsa": short_rsa_public_key(str(tmp_path)),
    }

    for description, key in rejected.items():
        response = add_ssh_key(session, key)
        assert response.status_code == 400, f"{description} should be rejected, got {response.status_code}"
        assert response.json()["success"] is False, f"{description}: {response.json()}"
        assert "Invalid SSH Key" in response.json()["error"], f"{description}: {response.json()}"

    assert key_count(name) == 0, "a rejected key was still committed"

    response = add_ssh_key(session, f"ssh-ed25519 {ed25519_blob}")
    assert response.status_code == 200, "the blob itself was valid; only the declared type was wrong"
    assert key_count(name) == 1


def test_newline_injection_cannot_add_a_second_key(dojo_user, ssh_keys):
    name, session = dojo_user
    victim = ssh_keys["rsa"]["public"]
    attacker = ssh_keys["ed25519"]["public"]
    attacker_blob = attacker.split()[1]

    add_ssh_key(session, f"{victim}\n{attacker}")

    values = stored_key_values(name)
    assert all(len(value.split()) <= 2 for value in values), f"stored value has extra fields: {values}"
    assert not any(attacker_blob in value for value in values), \
        f"the smuggled second key was stored: {values}"
    assert not any(attacker_blob in line for line in authorized_keys_lines()), \
        "the smuggled second key reached sshd's authorized_keys stream"

    result = ssh_run(ssh_keys["ed25519"]["private_file"], "whoami", timeout=30)
    assert_onboarding_rejects_command(result)


def test_declared_key_type_cannot_extend_the_authorized_keys_line(dojo_user, ssh_keys):
    name, session = dojo_user
    ecdsa = ssh_keys["ecdsa"]["public"]

    rejected = {
        "newline": b"ecdsa-sha2-nistp256\nssh-ed25519 AAAAsmuggled attacker",
        "space": b"ecdsa-sha2-nistp256 extra-field",
        "tab": b"ecdsa-sha2-nistp256\textra-field",
        "carriage return": b"ecdsa-sha2-nistp256\rextra-field",
        "comma": b"ecdsa-sha2-nistp256,extra-field",
        "control character": b"ecdsa-sha2-nistp256\x00extra-field",
        "non-ascii": b"ecdsa-sha2-nistp256\xff\xfe",
        "over 64 characters": b"ecdsa-sha2-" + b"n" * 64,
    }

    for description, key_type in rejected.items():
        response = add_ssh_key(session, rfc4716_key(key_type, ecdsa))
        assert response.status_code == 400, \
            f"a {description} in the key type should be rejected, got {response.status_code}"
        assert response.json()["success"] is False, f"{description}: {response.json()}"

    assert key_count(name) == 0, "a rejected key type was still committed"
    assert not any("smuggled" in line for line in authorized_keys_lines()), \
        "a smuggled key type reached sshd's authorized_keys stream"

    response = add_ssh_key(session, rfc4716_key(b"ecdsa-sha2-nistp256", ecdsa))
    assert response.status_code == 200, \
        f"an RFC 4716 key declaring an honest type must still be accepted: {response.text}"
    assert stored_key_values(name) == [normalized(ecdsa)], \
        "the RFC 4716 round trip did not canonicalize to the OpenSSH form"


def test_auth_py_emits_only_well_formed_authorized_keys_lines(dojo_user, ssh_keys):
    name, session = dojo_user
    rsa = ssh_keys["rsa"]["public"]
    assert add_ssh_key(session, rsa).status_code == 200, "failed to register the well-formed key"
    user_id = get_user_id(name)

    # A row that did not come through the API, standing in for anything that could
    # reach the table without being canonicalized first.
    db_sql("INSERT INTO ssh_keys (user_id, value) VALUES "
           rf"({user_id}, E'ssh-ed25519 AAAAsmuggled\nssh-rsa AAAAattacker unrestricted')")
    try:
        lines = authorized_keys_lines()
        assert all(line.startswith(f'command="{ENTER_COMMAND} ') for line in lines), \
            f"auth.py emitted a line without the forced command: {lines}"
        assert not any("AAAAattacker" in line for line in lines), \
            f"a malformed stored value reached the authorized_keys stream: {lines}"
        assert forced_command_line(user_id, rsa) in lines, \
            "the well-formed key was dropped along with the malformed one"
    finally:
        db_sql(f"DELETE FROM ssh_keys WHERE user_id = {user_id} AND value LIKE '%attacker%'")


def test_auth_py_routes_unknown_keys_to_onboarding(ssh_keys):
    public_key = ssh_keys["ed25519"]["public"]
    key_type, key_base64 = normalized(public_key).split()
    line = offered_key_line(public_key)

    assert line.startswith('command="/opt/sshd/onboard.py --key-type '), line
    assert line.endswith(normalized(public_key)), line
    assert dojo_run(
        "docker", "exec", "sshd", "/opt/sshd/auth.py", key_type
    ).stdout == ""
    assert dojo_run(
        "docker", "exec", "sshd", "/opt/sshd/auth.py", key_type, key_base64, "extra"
    ).stdout == ""
    assert dojo_run(
        "docker", "exec", "sshd", "/opt/sshd/auth.py", "", ""
    ).stdout == ""

    result = ssh_run(ssh_keys["ed25519"]["private_file"], "whoami", timeout=30)
    assert_onboarding_rejects_command(result)


def test_auth_py_rejects_malformed_offered_key_arguments(ssh_keys):
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    malformed = {
        "empty type": ("", key_base64),
        "empty data": (key_type, ""),
        "space in type": (f"{key_type} extra", key_base64),
        "tab in type": (f"{key_type}\textra", key_base64),
        "newline in type": (f"{key_type}\nssh-rsa", key_base64),
        "comma in type": (f"{key_type},option", key_base64),
        "overlong type": ("x" * 65, key_base64),
        "invalid data character": (key_type, f"{key_base64}!"),
        "invalid data padding": (key_type, f"{key_base64}==="),
        "newline in data": (key_type, f"{key_base64}\nAAAA"),
    }

    for description, (offered_type, offered_data) in malformed.items():
        result = dojo_run(
            "docker", "exec", "sshd", "/opt/sshd/auth.py", offered_type, offered_data
        )
        assert result.stdout == "", f"{description} produced an authorized_keys line: {result.stdout!r}"


def test_unknown_key_can_open_and_quit_onboarding(ssh_keys):
    started = time.time()
    result = ssh_run(
        ssh_keys["ed25519"]["private_file"],
        options=["-tt"],
        stdin_data="q\n",
        term="xterm-256color",
        timeout=60,
    )
    assert time.time() - started < 55, "SSH onboarding hung"
    assert result.returncode == 0, result.stderr
    assert "\x1b[" in result.stdout or "Set up SSH access" in result.stdout, result.stdout[-400:]


@pytest.mark.timeout(300)
def test_unknown_key_onboards_starts_a_challenge_and_enters_workspace(ssh_keys, example_dojo, tmp_path):
    name = random_name("sshlive")
    password = random_name("password")
    key = ssh_keys["ed25519"]
    transcript = tmp_path / "onboarding.log"
    process = None

    try:
        with transcript.open("w") as output:
            process = subprocess.Popen(
                [
                    "ssh", *SSH_BASE_OPTIONS, "-tt", "-i", key["private_file"],
                    "-p", str(SSH_PORT), f"hacker@{DOJO_SSH_HOST}",
                ],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "TERM": "xterm-256color"},
            )
            await_transcript(transcript, "Set up SSH access", process)
            send_ssh_input(process, "c")
            await_transcript(transcript, "Enter username", process)
            send_ssh_input(process, f"{name}\r")
            await_transcript(transcript, "Enter email", process)
            send_ssh_input(process, f"{name}@example.com\r")
            await_transcript(transcript, "Enter password", process)
            send_ssh_input(process, f"{password}\r")
            await_transcript(transcript, "Account created", process, timeout=60)
            browser_start = len(transcript_text(transcript))

            user_id = get_user_id(name)
            assert stored_key_values(name) == [normalized(key["public"])]
            catalog_response = requests.get(
                DOJOS_ENDPOINT,
                headers=ssh_token_header([user_id, "ssh-tui"]),
            )
            assert catalog_response.status_code == 200, catalog_response.text
            section_order = {
                "welcome": 0,
                "topic": 1,
                "public": 2,
                "course": 3,
                "private": 4,
                "hidden": 5,
                "example": 6,
            }
            indexed_dojos = list(enumerate(catalog_response.json()["dojos"]))
            dojos = [
                dojo for _, dojo in sorted(
                    indexed_dojos,
                    key=lambda item: (section_order.get(item[1].get("type"), 100), item[0]),
                )
            ]
            dojo_index = next(index for index, dojo in enumerate(dojos) if dojo["id"] == example_dojo)
            modules_response = requests.get(
                f"{DOJOS_ENDPOINT}/{example_dojo}/modules",
                headers=ssh_token_header([user_id, "ssh-tui"]),
            )
            assert modules_response.status_code == 200, modules_response.text
            modules = modules_response.json()["modules"]
            module_index = next(index for index, module in enumerate(modules) if module["id"] == "hello")
            challenges = modules[module_index]["challenges"]
            challenge_index = next(
                index for index, challenge in enumerate(challenges) if challenge["id"] == "apple"
            )

            await_transcript(
                transcript, "Challenge Browser", process, start=browser_start, timeout=60
            )
            await_transcript(
                transcript,
                "Use arrows to browse and enter to start",
                process,
                start=browser_start,
                timeout=60,
            )
            await_transcript_quiescence(transcript, process)
            for _ in range(dojo_index):
                send_ssh_key_and_await_render(process, transcript, "j")
            navigation_start = len(transcript_text(transcript))
            send_ssh_input(process, "l")
            await_transcript(
                transcript,
                "Use arrows to browse and enter to start",
                process,
                start=navigation_start,
            )
            await_transcript_quiescence(transcript, process)
            send_ssh_key_and_await_render(process, transcript, "l")
            for _ in range(module_index):
                send_ssh_key_and_await_render(process, transcript, "j")
            send_ssh_key_and_await_render(process, transcript, "l")
            challenge_start = len(transcript_text(transcript))
            send_ssh_input(process, "l")
            await_transcript(
                transcript,
                "Enter opens mode picker",
                process,
                start=challenge_start,
            )
            await_transcript_quiescence(transcript, process)
            for _ in range(challenge_index):
                send_ssh_key_and_await_render(process, transcript, "j")
            picker_start = len(transcript_text(transcript))
            send_ssh_input(process, "\r")
            await_transcript(
                transcript,
                "Choose a mode: s starts standard",
                process,
                start=picker_start,
            )
            await_transcript_quiescence(transcript, process)
            start_offset = len(transcript_text(transcript))
            send_ssh_input(process, "s")
            await_transcript(transcript, "Starting apple...", process, start=start_offset)
            await_transcript(transcript, "Connected!", process, start=start_offset, timeout=120)
            send_ssh_input(process, "printf 'ONBOARD_WORKSPACE=%s\\n' \"$(hostname)\"\nexit\n")
            result_code = process.wait(timeout=30)

        output = transcript_text(transcript)
        assert result_code == 0, output[-2000:]
        assert "ONBOARD_WORKSPACE=hello~apple" in output, output[-2000:]
        login(name, password)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        if process is not None and process.stdin:
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass
        if user_count(name):
            user_id = get_user_id(name)
            remove_workspace_container(name)
            remove_workspace_home(user_id)


def test_empty_key_value_rejected(dojo_user, second_user):
    name, session = dojo_user
    other_name, other_session = second_user
    try:
        for payload in [{"ssh_key": "   "}, {"ssh_key": ""}, {}]:
            response = session.post(SSH_KEY_ENDPOINT, json=payload)
            assert response.status_code == 400, f"{payload} should be rejected, got {response.status_code}"
            assert response.json()["success"] is False, response.json()
            assert key_count(name) == 0, f"{payload} created an ssh_keys row"

        response = other_session.post(SSH_KEY_ENDPOINT, json={"ssh_key": ""})
        assert response.status_code == 400, response.status_code
        assert "already in use" not in response.json().get("error", ""), \
            "one user's empty value consumed the global unique-digest slot"
        assert key_count(other_name) == 0
    finally:
        db_sql("DELETE FROM ssh_keys WHERE value = ''")


def test_malformed_request_body_rejected(dojo_user):
    name, session = dojo_user
    for method in (session.post, session.delete):
        for description, kwargs in [
            ("non-json body", dict(data="not json", headers={"Content-Type": "text/plain"})),
            ("no body at all", dict()),
        ]:
            response = method(SSH_KEY_ENDPOINT, **kwargs)
            assert 400 <= response.status_code < 500, \
                f"{method.__name__} with {description} returned {response.status_code}"
    assert key_count(name) == 0, "a malformed request created an ssh_keys row"


def test_non_string_key_values_are_rejected_cleanly(dojo_user):
    name, session = dojo_user
    expected = {"success": False, "error": "ssh_key must be a string"}

    for value in (None, True, 123, [], {}):
        for method in (session.post, session.delete):
            response = method(SSH_KEY_ENDPOINT, json={"ssh_key": value})
            assert response.status_code == 400, \
                f"{method.__name__} accepted {value!r}: {response.status_code} {response.text}"
            assert response.json() == expected, response.json()
    assert key_count(name) == 0


def test_key_stays_bound_to_the_first_registering_user(workspace_ssh_user, dojo_user):
    other_name, other_session = dojo_user
    owner_key = workspace_ssh_user.keys["rsa"]

    response = add_ssh_key(other_session, owner_key["public"])
    assert response.status_code == 400, response.status_code
    assert "already in use" in response.json()["error"], response.json()
    assert key_count(other_name) == 0

    owner_id = get_user_id(workspace_ssh_user.name)
    owner = db_sql(f"SELECT user_id FROM ssh_keys WHERE value = '{normalized(owner_key['public'])}'").strip()
    assert owner == str(owner_id), f"key ownership changed: {owner}"

    result = ssh_run(owner_key["private_file"], "hostname")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hello~apple", \
        "the key must still enter its owner's workspace, not the second user's"


def test_delete_matches_the_normalized_value_and_frees_the_key(dojo_user, second_user, ssh_keys):
    name, session = dojo_user
    other_name, other_session = second_user
    rsa = ssh_keys["rsa"]["public"]

    assert add_ssh_key(session, f"{normalized(rsa)} me@laptop").status_code == 200

    response = session.delete(SSH_KEY_ENDPOINT, json={"ssh_key": f"{normalized(rsa)} me@laptop"})
    assert response.status_code == 400, "delete must match the stored (normalized) value"
    assert "does not exist" in response.json()["error"], response.json()
    assert key_count(name) == 1

    response = session.delete(SSH_KEY_ENDPOINT, json={"ssh_key": normalized(rsa)})
    assert response.status_code == 200, response.text
    assert key_count(name) == 0

    assert add_ssh_key(session, rsa).status_code == 200, "a deleted key must be registerable again"
    assert key_count(name) == 1
    assert delete_ssh_key(session, rsa).status_code == 200

    assert add_ssh_key(other_session, rsa).status_code == 200, \
        "deleting a key must release the global unique-digest slot"
    assert key_count(other_name) == 1


def test_delete_other_users_key_forbidden(dojo_user, second_user, ssh_keys, admin_session):
    name, session = dojo_user
    _, other_session = second_user
    user_id = get_user_id(name)
    rsa = ssh_keys["rsa"]["public"]

    assert add_ssh_key(session, rsa).status_code == 200

    for description, attacker in [("another user", other_session), ("an admin", admin_session)]:
        response = attacker.delete(SSH_KEY_ENDPOINT, json={"ssh_key": normalized(rsa)})
        assert response.status_code == 400, f"{description} deleted someone else's key"
        assert "does not exist" in response.json()["error"], response.json()

    assert key_count(name) == 1
    assert forced_command_line(user_id, rsa) in authorized_keys_lines(), \
        "the owner's key stopped being served"


def test_key_api_requires_auth_and_csrf(dojo_user, ssh_keys):
    name, session = dojo_user
    rsa = normalized(ssh_keys["rsa"]["public"])

    anonymous = requests.Session()
    no_csrf = requests.Session()
    no_csrf.cookies.update(session.cookies)

    assert anonymous.post(SSH_KEY_ENDPOINT, json={"ssh_key": rsa}).status_code == 403
    assert no_csrf.post(SSH_KEY_ENDPOINT, json={"ssh_key": rsa}).status_code == 403
    assert key_count(name) == 0, "an unauthenticated or CSRF-less request registered a key"

    assert add_ssh_key(session, rsa).status_code == 200, "the only difference should be the CSRF header"
    assert key_count(name) == 1

    assert anonymous.delete(SSH_KEY_ENDPOINT, json={"ssh_key": rsa}).status_code == 403
    assert no_csrf.delete(SSH_KEY_ENDPOINT, json={"ssh_key": rsa}).status_code == 403
    assert key_count(name) == 1, "an unauthenticated or CSRF-less request deleted a key"

    assert delete_ssh_key(session, rsa).status_code == 200


def test_key_attaches_to_the_session_user_only(dojo_user, ssh_keys, admin_session):
    name, _ = dojo_user
    rsa = normalized(ssh_keys["rsa"]["public"])

    response = admin_session.post(
        SSH_KEY_ENDPOINT,
        json={"ssh_key": rsa, "user_id": get_user_id(name), "user": name},
    )
    assert response.status_code == 200, response.text
    try:
        owner = db_sql(f"SELECT user_id FROM ssh_keys WHERE value = '{rsa}'").strip()
        assert owner == str(get_user_id("admin")), \
            f"body fields overrode the session user: key belongs to {owner}"
        assert key_count(name) == 0
    finally:
        admin_session.delete(SSH_KEY_ENDPOINT, json={"ssh_key": rsa})


def test_commands_run_in_the_workspace_not_the_sshd_container(workspace_ssh_user):
    result = ssh_run(
        workspace_ssh_user.keys["ed25519"]["private_file"],
        "hostname; cat /etc/environment 2>/dev/null; ls /opt/sshd 2>/dev/null; "
        "echo WORKSPACE_BIN=$(ls /run/dojo/bin | head -1)",
    )
    assert result.returncode == 0, result.stderr
    assert "DATABASE_URL" not in result.stdout, "sshd's environment file was readable over ssh"
    assert "auth.py" not in result.stdout, "sshd's own files were readable over ssh"
    assert "hello~apple" in result.stdout, f"landed in the wrong container: {result.stdout!r}"
    workspace_bin = [line for line in result.stdout.splitlines() if line.startswith("WORKSPACE_BIN=")]
    assert workspace_bin and workspace_bin[0] != "WORKSPACE_BIN=", \
        f"/run/dojo/bin was empty, so this was not a workspace: {result.stdout!r}"


def test_stdio_is_forwarded_between_client_and_workspace(workspace_ssh_user):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]

    result = ssh_run(private_key, "echo OUTPUT_MARKER; echo ERROR_MARKER >&2")
    assert result.returncode == 0, result.stderr
    assert "OUTPUT_MARKER" in result.stdout and "OUTPUT_MARKER" not in result.stderr
    assert "ERROR_MARKER" in result.stderr and "ERROR_MARKER" not in result.stdout

    payload = "hello-from-stdin"
    result = ssh_run(private_key, "cat > /home/hacker/ssh_stdin_test", stdin_data=f"{payload}\n")
    assert result.returncode == 0, result.stderr
    assert workspace_run("cat /home/hacker/ssh_stdin_test",
                         user=workspace_ssh_user.name).stdout.strip() == payload
    assert ssh_run(private_key, "cat /home/hacker/ssh_stdin_test").stdout.strip() == payload


def test_remote_exit_status_is_propagated(workspace_ssh_user):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]
    assert ssh_run(private_key, "true").returncode == 0
    assert ssh_run(private_key, "false").returncode == 1
    assert ssh_run(private_key, "exit 42").returncode == 42


def test_interactive_session_gets_a_login_shell(workspace_ssh_user):
    result = ssh_run(
        workspace_ssh_user.keys["ed25519"]["private_file"],
        options=["-tt"],
        stdin_data="echo SHELL_MARKER=$0; echo FLAGS_MARKER=$-; echo TERM_MARKER=$TERM; exit\n",
        term="xterm-256color",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    shell = next((line.split("=", 1)[1].strip()
                  for line in result.stdout.splitlines() if line.startswith("SHELL_MARKER=")), None)
    assert shell and shell.lstrip("-").endswith("bash"), f"unexpected login shell: {result.stdout!r}"
    flags = next((line.split("=", 1)[1] for line in result.stdout.splitlines()
                  if line.startswith("FLAGS_MARKER=")), "")
    assert "i" in flags, f"the shell was not interactive: {flags!r}"
    assert "TERM_MARKER=xterm-256color" in result.stdout, \
        f"TERM was not propagated into the workspace: {result.stdout!r}"


def test_only_hacker_logins_and_only_publickey_auth_are_accepted(workspace_ssh_user):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]
    assert ssh_run(private_key, "whoami").returncode == 0

    for login_user in ("root", "admin"):
        result = ssh_run(private_key, "whoami", login_user=login_user, timeout=30)
        assert result.returncode == 255, f"{login_user} login was accepted: {result.stdout!r}"
        assert "Permission denied" in result.stderr, result.stderr

    result = subprocess.run(
        ["ssh", *SSH_BASE_OPTIONS,
         "-o", "PubkeyAuthentication=no",
         "-o", "PreferredAuthentications=password,keyboard-interactive",
         "-o", "NumberOfPasswordPrompts=1",
         "-p", str(SSH_PORT), f"hacker@{DOJO_SSH_HOST}", "whoami"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 255, "password authentication was offered"
    assert "Permission denied (publickey" in result.stderr, result.stderr


def test_x11_and_tcp_forwarding_are_refused(workspace_ssh_user):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]

    result = ssh_run(private_key, "echo DISPLAY=[$DISPLAY]", options=["-X", "-o", "ForwardX11=yes"])
    assert result.returncode == 0, result.stderr
    assert "DISPLAY=[]" in result.stdout, f"an X11 forwarding channel was established: {result.stdout!r}"

    result = ssh_run(private_key, options=[
        "-o", "ExitOnForwardFailure=yes", "-R", "127.0.0.1:12345:127.0.0.1:80", "-N",
    ], timeout=30)
    assert result.returncode != 0, "remote port forwarding was allowed"
    assert "forwarding failed" in result.stderr or "administratively prohibited" in result.stderr, \
        result.stderr


def test_agent_forwarding_is_refused(workspace_ssh_user, tmp_path):
    agent_socket = tmp_path / "agent.sock"
    existing_server_sockets = sshd_agent_sockets()
    agent = subprocess.Popen(
        ["ssh-agent", "-D", "-a", str(agent_socket)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not agent_socket.exists() and agent.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if not agent_socket.exists():
            if agent.poll() is None:
                agent.terminate()
            _, stderr = agent.communicate(timeout=5)
            pytest.fail(f"ssh-agent did not create its socket: {stderr}")
        agent_env = {**os.environ, "SSH_AUTH_SOCK": str(agent_socket)}
        added = subprocess.run(
            ["ssh-add", workspace_ssh_user.keys["ed25519"]["private_file"]],
            env=agent_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert added.returncode == 0, added.stderr

        connection = subprocess.Popen(
            [
                "ssh", *SSH_BASE_OPTIONS, "-A",
                "-i", workspace_ssh_user.keys["ed25519"]["private_file"],
                "-p", str(SSH_PORT), f"hacker@{DOJO_SSH_HOST}",
                "if test -S \"${SSH_AUTH_SOCK:-}\"; then echo AGENT_FORWARDED; "
                "else echo AGENT_BLOCKED; fi; sleep 10",
            ],
            env=agent_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        output = connection.stdout.readline().strip()
        assert output == "AGENT_BLOCKED", output
        assert not sshd_agent_sockets() - existing_server_sockets
        stdout, stderr = connection.communicate(timeout=20)
        assert connection.returncode == 0, stderr
        assert "AGENT_FORWARDED" not in stdout, stdout
    finally:
        if "connection" in locals() and connection.poll() is None:
            connection.terminate()
            connection.communicate(timeout=10)
        if agent.poll() is None:
            agent.terminate()
        agent.communicate(timeout=10)


@pytest.mark.timeout(90)
def test_unused_authenticated_connection_is_closed_within_configured_timeout(workspace_ssh_user):
    started = time.monotonic()
    try:
        result = subprocess.run(
            [
                "ssh", *SSH_BASE_OPTIONS, "-N",
                "-i", workspace_ssh_user.keys["ed25519"]["private_file"],
                "-p", str(SSH_PORT), f"hacker@{DOJO_SSH_HOST}",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=82,
        )
    except subprocess.TimeoutExpired as error:
        pytest.fail(f"unused authenticated connection remained open past 82 seconds: {error}")
    elapsed = time.monotonic() - started
    assert 50 <= elapsed < 82, \
        f"unused connection closed after {elapsed:.1f}s instead of the configured 60s: {result.stderr}"


def test_sshd_effective_config_limits_unused_connections_and_passes_offered_keys():
    effective_config = dojo_run(
        "docker", "exec", "sshd", "/usr/sbin/sshd.pam", "-T", "-f", "/opt/sshd/sshd_config",
        "-C", "user=hacker,host=localhost,addr=127.0.0.1",
    ).stdout.splitlines()
    assert "unusedconnectiontimeout 60" in effective_config
    assert "authorizedkeyscommand /opt/sshd/auth.py %t %k" in effective_config
    assert "disableforwarding yes" in effective_config
    assert "allowagentforwarding no" in effective_config


def test_unknown_key_cannot_forward_docker_socket(ssh_keys, tmp_path):
    effective_config = dojo_run(
        "docker", "exec", "sshd", "/usr/sbin/sshd.pam", "-T", "-f", "/opt/sshd/sshd_config",
        "-C", "user=hacker,host=localhost,addr=127.0.0.1",
    ).stdout
    assert "disableforwarding yes" in effective_config.splitlines()

    forwarded_socket = tmp_path / "docker.sock"
    process = subprocess.Popen(
        [
            "ssh", *SSH_BASE_OPTIONS,
            "-i", ssh_keys["ed25519"]["private_file"],
            "-p", str(SSH_PORT),
            "-N", "-L", f"{forwarded_socket}:/var/run/docker.sock",
            f"hacker@{DOJO_SSH_HOST}",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    response = b""
    stderr = ""
    try:
        deadline = time.monotonic() + 15
        while not forwarded_socket.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if not forwarded_socket.exists():
            if process.poll() is None:
                process.terminate()
            _, stderr = process.communicate(timeout=10)
            pytest.fail(f"SSH did not create the forwarding socket: {stderr}")
        time.sleep(2)
        assert process.poll() is None, process.communicate(timeout=10)[1]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5)
            try:
                client.connect(str(forwarded_socket))
                client.sendall(b"GET /_ping HTTP/1.0\r\n\r\n")
                while chunk := client.recv(4096):
                    response += chunk
            except OSError:
                pass
    finally:
        if process.poll() is None:
            process.terminate()
        _, stderr = process.communicate(timeout=10)
    assert "open failed" in stderr, stderr
    assert b"200 OK" not in response, "an unknown SSH key forwarded the Docker socket"


def test_sftp_transfer_round_trips(workspace_ssh_user, tmp_path):
    payload = b"sftp-payload\x00round-trip\n"
    source = tmp_path / "sftp_payload.txt"
    source.write_bytes(payload)
    destination = tmp_path / "sftp_down.txt"
    batch = tmp_path / "batch"
    batch.write_text(
        f"put {source} /home/hacker/sftp_up.txt\n"
        f"get /home/hacker/sftp_up.txt {destination}\n"
    )

    started = time.time()
    result = subprocess.run(
        ["sftp", *SSH_BASE_OPTIONS, "-P", str(SSH_PORT),
         "-i", workspace_ssh_user.keys["ed25519"]["private_file"],
         "-b", str(batch), f"hacker@{DOJO_SSH_HOST}"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
    )
    elapsed = time.time() - started
    assert elapsed < 30, f"the sftp session hung for {elapsed:.1f}s"
    assert result.returncode == 0, result.stderr
    assert workspace_run("base64 -w0 /home/hacker/sftp_up.txt",
                         user=workspace_ssh_user.name).stdout == base64.b64encode(payload).decode()
    assert destination.read_bytes() == payload


@pytest.mark.parametrize("protocol_options", [
    pytest.param([], id="sftp"),
    pytest.param(["-O"], id="legacy"),
])
def test_scp_transfer_round_trips(workspace_ssh_user, tmp_path, protocol_options):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]
    payload = b"scp-payload\x00round-trip\n"
    source = tmp_path / "scp_up.txt"
    source.write_bytes(payload)

    upload = subprocess.run(
        ["scp", *protocol_options, *SSH_BASE_OPTIONS, "-P", str(SSH_PORT), "-i", private_key,
         str(source), f"hacker@{DOJO_SSH_HOST}:/home/hacker/scp_up.txt"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert upload.returncode == 0, upload.stderr
    assert workspace_run("base64 -w0 /home/hacker/scp_up.txt",
                         user=workspace_ssh_user.name).stdout == base64.b64encode(payload).decode()

    destination = tmp_path / "scp_down.txt"
    download = subprocess.run(
        ["scp", *protocol_options, *SSH_BASE_OPTIONS, "-P", str(SSH_PORT), "-i", private_key,
         f"hacker@{DOJO_SSH_HOST}:/home/hacker/scp_up.txt", str(destination)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert download.returncode == 0, download.stderr
    assert destination.read_bytes() == payload


def test_ssh_requires_the_users_own_running_workspace(workspace_ssh_user, dojo_user, ssh_keys, example_dojo):
    name, session = dojo_user
    private_key = ssh_keys["ed25519"]["private_file"]
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200
    remove_workspace_container(name)

    try:
        started = time.time()
        result = ssh_run(private_key, "hostname", timeout=30)
        assert result.returncode == 1, \
            f"expected the 'no active session' exit, got rc={result.returncode}: {result.stderr!r}"
        assert "hello~apple" not in result.stdout, "the key reached another user's workspace"
        assert time.time() - started < 30, "the connection hung instead of exiting"

        start_challenge(example_dojo, "hello", "apple", session=session)
        result = ssh_run(private_key, "test -f /run/dojo/var/ready && echo READY; hostname", timeout=60)
        assert result.returncode == 0, result.stderr
        assert "READY" in result.stdout, "the session started before the workspace was initialized"
        assert "hello~apple" in result.stdout, result.stdout
    finally:
        remove_workspace_container(name)


def test_container_removal_ends_access_and_restart_restores_it(dojo_user, ssh_keys, example_dojo):
    name, session = dojo_user
    private_key = ssh_keys["ed25519"]["private_file"]
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        result = ssh_run(private_key, "whoami", timeout=60)
        assert result.returncode == 0 and "hacker" in result.stdout, result.stderr

        remove_workspace_container(name)
        result = ssh_run(private_key, "whoami", timeout=30)
        assert result.returncode == 1, f"expected exit 1 after removal, got {result.returncode}"
        assert "hacker" not in result.stdout, "a shell was still reachable after container removal"

        start_challenge(example_dojo, "hello", "apple", session=session)
        result = ssh_run(private_key, "whoami", timeout=60)
        assert result.returncode == 0 and "hacker" in result.stdout, result.stderr
    finally:
        remove_workspace_container(name)


def test_new_key_authenticates_on_the_next_connection(dojo_user, ssh_keys, example_dojo):
    name, session = dojo_user
    private_key = ssh_keys["rsa"]["private_file"]

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        result = ssh_run(private_key, "whoami", timeout=30)
        assert_onboarding_rejects_command(result)

        submitted = f'command="/bin/sh -c \'touch /tmp/pwned-{name}\'",no-pty {ssh_keys["rsa"]["public"]}'
        assert add_ssh_key(session, submitted).status_code == 200
        result = ssh_run(private_key, "whoami", timeout=60)
        assert result.returncode == 0, f"a freshly added key did not work immediately: {result.stderr}"
        assert "hacker" in result.stdout, \
            "a key submitted with authorized_keys options must still land in the workspace"
        assert f"pwned-{name}" not in dojo_run("docker", "exec", "sshd", "ls", "/tmp").stdout, \
            "a user-supplied forced command ran on login"
    finally:
        remove_workspace_container(name)


def test_deleting_a_key_revokes_only_that_key_immediately(dojo_user, ssh_keys, example_dojo):
    name, session = dojo_user
    rsa = ssh_keys["rsa"]
    ed25519 = ssh_keys["ed25519"]

    assert add_ssh_key(session, rsa["public"]).status_code == 200
    assert add_ssh_key(session, ed25519["public"]).status_code == 200

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        assert ssh_run(rsa["private_file"], "whoami", timeout=60).returncode == 0
        assert ssh_run(ed25519["private_file"], "whoami").returncode == 0

        assert delete_ssh_key(session, rsa["public"]).status_code == 200
        assert key_count(name) == 1

        result = ssh_run(rsa["private_file"], "whoami", timeout=30)
        assert_onboarding_rejects_command(result)

        result = ssh_run(ed25519["private_file"], "whoami")
        assert result.returncode == 0 and "hacker" in result.stdout, \
            "deleting one key revoked the user's other key"

        assert add_ssh_key(session, rsa["public"]).status_code == 200
        result = ssh_run(rsa["private_file"], "whoami", timeout=60)
        assert result.returncode == 0 and "hacker" in result.stdout, \
            "a re-added key did not restore access"
    finally:
        remove_workspace_container(name)


def test_ssh_session_targets_the_current_challenge(dojo_user, ssh_keys, example_dojo):
    name, session = dojo_user
    private_key = ssh_keys["ed25519"]["private_file"]
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        result = ssh_run(private_key, "hostname", timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "hello~apple", result.stdout

        assert ssh_run(private_key, "touch /tmp/ssh_challenge_marker").returncode == 0
        result = ssh_run(private_key, "test -e /tmp/ssh_challenge_marker && echo PRESENT || echo GONE")
        assert "PRESENT" in result.stdout, result.stdout

        start_challenge(example_dojo, "hello", "banana", session=session)
        result = ssh_run(private_key, "hostname", timeout=60)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "hello~banana", \
            f"ssh entered the old challenge's container: {result.stdout!r}"

        result = ssh_run(private_key, "test -e /tmp/ssh_challenge_marker && echo PRESENT || echo GONE")
        assert "GONE" in result.stdout, "state from the previous challenge container survived"
    finally:
        remove_workspace_container(name)


def test_interactive_ssh_reconnects_when_the_challenge_is_replaced(dojo_user, ssh_keys, example_dojo, tmp_path):
    name, session = dojo_user
    key = ssh_keys["ed25519"]
    assert add_ssh_key(session, key["public"]).status_code == 200
    transcript = tmp_path / "ssh-session.log"
    process = None

    def await_output(expected):
        deadline = time.monotonic() + 45
        while expected not in transcript.read_text():
            assert process.poll() is None, transcript.read_text()
            assert time.monotonic() < deadline, transcript.read_text()
            time.sleep(0.2)

    try:
        start_challenge(example_dojo, "hello", "apple", session=session)
        with transcript.open("w") as output:
            process = subprocess.Popen(
                [
                    "ssh", *SSH_BASE_OPTIONS, "-tt", "-i", key["private_file"],
                    "-p", str(SSH_PORT), f"hacker@{DOJO_SSH_HOST}",
                ],
                stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                text=True, env={**os.environ, "TERM": "xterm-256color"},
            )
            process.stdin.write("printf '\\nINITIAL_HOST=%s\\n' \"$(hostname)\"\n")
            process.stdin.flush()
            await_output("INITIAL_HOST=hello~apple")

            start_challenge(example_dojo, "hello", "banana", session=session)
            process.stdin.write("printf '\\nRECONNECTED_HOST=%s\\n' \"$(hostname)\"\n")
            process.stdin.flush()
            await_output("RECONNECTED_HOST=hello~banana")

            process.stdin.write("exit\n")
            process.stdin.flush()
            assert process.wait(timeout=15) == 0, transcript.read_text()
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            process.stdin.close()
        remove_workspace_container(name)


def test_banned_user_cannot_ssh(dojo_user, ssh_keys):
    name, session = dojo_user
    user_id = get_user_id(name)
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200

    db_sql(f"UPDATE users SET banned = true WHERE id = {user_id}")
    try:
        assert forced_command_line(user_id, ssh_keys["ed25519"]["public"]) not in authorized_keys_lines(), \
            "a banned user's key is still served to sshd"
        assert offered_key_line(ssh_keys["ed25519"]["public"]) == "", \
            "a banned user's key was routed into onboarding"
        result = ssh_run(ssh_keys["ed25519"]["private_file"], "whoami", timeout=30)
        assert result.returncode == 255, \
            f"a banned user's key still authenticated (rc={result.returncode})"
        assert "Permission denied" in result.stderr, result.stderr
    finally:
        db_sql(f"UPDATE users SET banned = false WHERE id = {user_id}")


def test_interactive_session_without_a_workspace_offers_the_challenge_tui(dojo_user, ssh_keys):
    name, session = dojo_user
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200
    remove_workspace_container(name)

    started = time.time()
    result = ssh_run(ssh_keys["ed25519"]["private_file"], options=["-tt"], stdin_data="q\n",
                     term="xterm-256color", timeout=60)
    assert time.time() - started < 55, "the interactive session hung"
    assert result.returncode == 1, f"expected exit 1 after quitting the tui, got {result.returncode}"

    combined = result.stdout + result.stderr
    assert "No active challenge session; start a challenge!" in combined, repr(combined[-400:])
    assert "\x1b[" in result.stdout or "Failed to launch challenge tui" in combined, \
        "no full-screen tui was rendered for an interactive session without a workspace"


def test_ssh_onboarding_registration_rejects_non_object_bodies_atomically():
    before = user_count()
    expected = {"success": False, "errors": ["Invalid request body"]}
    cases = [
        ("missing", {}),
        ("invalid json", {"data": "{", "headers": {"Content-Type": "application/json"}}),
        ("list", {"json": [{"name": random_name("sshbody")}]}),
        ("null", {"data": "null", "headers": {"Content-Type": "application/json"}}),
    ]

    for description, kwargs in cases:
        headers = ssh_token_header("ssh-onboarding")
        headers.update(kwargs.pop("headers", {}))
        response = raw_register_request(headers=headers, **kwargs)
        assert response.status_code == 400, f"{description}: {response.status_code} {response.text}"
        assert response.json() == expected, f"{description}: {response.json()}"
        assert user_count() == before, f"{description} created a user"


def test_ssh_onboarding_registration_rejects_malformed_key_fields_atomically(ssh_keys):
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    cases = {
        "missing type": {"key_base64": key_base64},
        "missing data": {"key_type": key_type},
        "null type": {"key_type": None, "key_base64": key_base64},
        "null data": {"key_type": key_type, "key_base64": None},
        "non-string type": {"key_type": [key_type], "key_base64": key_base64},
        "non-string data": {"key_type": key_type, "key_base64": {"data": key_base64}},
        "type and blob mismatch": {"key_type": "ssh-rsa", "key_base64": key_base64},
        "space in type": {"key_type": f"{key_type} extra", "key_base64": key_base64},
        "tab in type": {"key_type": f"{key_type}\textra", "key_base64": key_base64},
        "type injection": {"key_type": f"{key_type}\nssh-rsa", "key_base64": key_base64},
        "space in data": {"key_type": key_type, "key_base64": f"{key_base64} extra"},
        "tab in data": {"key_type": key_type, "key_base64": f"{key_base64}\textra"},
        "carriage return in data": {"key_type": key_type, "key_base64": f"{key_base64}\rssh-rsa AAAA"},
        "data injection": {"key_type": key_type, "key_base64": f"{key_base64}\nssh-rsa AAAA"},
    }
    before_keys = ssh_key_count(ssh_keys["ed25519"]["public"])

    for description, key_fields in cases.items():
        name = random_name("sshbadkey")
        response = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload={
                "name": name,
                "email": f"{name}@example.com",
                "password": random_name("password"),
                **key_fields,
            },
        )
        assert response.status_code == 400, f"{description}: {response.status_code} {response.text}"
        assert response.json()["success"] is False, f"{description}: {response.json()}"
        assert any(error.startswith("Invalid SSH key:") for error in response.json()["errors"]), \
            f"{description}: {response.json()}"
        assert user_count(name) == 0, f"{description} created a user"
        assert ssh_key_count(ssh_keys["ed25519"]["public"]) == before_keys, \
            f"{description} created an SSH key"


def test_ssh_onboarding_registration_rejects_non_string_account_fields_atomically(ssh_keys):
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    cases = {
        "numeric name": ("name", 42),
        "list email": ("email", ["user@example.com"]),
        "object password": ("password", {"password": "secret"}),
        "list website": ("website", ["https://example.com"]),
        "object affiliation": ("affiliation", {"name": "example"}),
        "numeric country": ("country", 42),
        "null registration code": ("registration_code", None),
        "boolean registration code": ("registration_code", False),
    }

    for description, (field, value) in cases.items():
        name = random_name("sshbadfield")
        payload = {
            "name": name,
            "email": f"{name}@example.com",
            "password": random_name("password"),
            "key_type": key_type,
            "key_base64": key_base64,
            field: value,
        }
        before_users = user_count()
        before_keys = ssh_key_count(ssh_keys["ed25519"]["public"])
        response = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload=payload,
        )
        assert response.status_code == 400, \
            f"{description}: {response.status_code} {response.text}"
        assert response.json() == {"success": False, "errors": ["Invalid request body"]}
        assert user_count() == before_users, f"{description} created a user"
        assert ssh_key_count(ssh_keys["ed25519"]["public"]) == before_keys, \
            f"{description} created an SSH key"


def test_ssh_onboarding_registration_accumulates_key_and_account_errors_atomically():
    before_users = user_count()
    before_keys = int(db_sql("SELECT count(*) FROM ssh_keys"))
    response = register_request(
        headers=ssh_token_header("ssh-onboarding"),
        payload={
            "name": "   ",
            "email": random_name("not-an-email-"),
            "password": "   ",
        },
    )
    assert response.status_code == 400, response.text
    errors = response.json()["errors"]
    assert errors[0].startswith("Invalid SSH key:"), errors
    assert errors[1:] == [
        "Please provide a username",
        "Please enter a valid email address",
        "Please provide a password",
    ], errors
    assert user_count() == before_users
    assert int(db_sql("SELECT count(*) FROM ssh_keys")) == before_keys


def test_registration_separates_catalog_tokens_from_public_bearer_headers(dojo_user, ssh_keys):
    token_name, _ = dojo_user
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()

    rejected_headers = {
        "catalog token": ssh_token_header([get_user_id(token_name), "ssh-tui"]),
        "empty service token": {"Authorization": "Bearer sk-ssh-service-"},
    }
    for description, headers in rejected_headers.items():
        name = random_name("sshwrongscope")
        response = register_request(
            headers=headers,
            payload={
                "name": name,
                "email": f"{name}@example.com",
                "password": random_name("password"),
                "key_type": key_type,
                "key_base64": key_base64,
            },
        )
        assert response.status_code == 401, f"{description}: {response.status_code} {response.text}"
        assert response.json() == {
            "success": False,
            "error": "Failed to authenticate SSH service token.",
        }
        assert user_count(name) == 0

    public_name = random_name("sshpublicbearer")
    password = random_name("password")
    public_session = requests.Session()
    public_session.headers["CSRF-Token"] = parse_csrf_token(
        public_session.get(f"{DOJO_URL}/register").text
    )
    response = register_request(
        session=public_session,
        headers={"Authorization": "Bearer nonsense"},
        payload={
            "name": public_name,
            "email": f"{public_name}@example.com",
            "password": password,
            "key_type": key_type,
            "key_base64": key_base64,
        },
    )
    assert response.status_code == 200, response.text
    assert key_count(public_name) == 0
    identity = public_session.get(f"{DOJO_URL}/pwncollege_api/v1/users/me")
    assert identity.status_code == 200, identity.text
    assert identity.json()["name"] == public_name


def test_deployed_sshd_onboarding_client_reaches_internal_registration_api(ssh_keys):
    name = random_name("sshinternal")
    password = random_name("password")
    key_type, key_base64 = normalized(ssh_keys["ecdsa"]["public"]).split()

    result = dojo_run(
        "docker", "exec", "sshd", "python3", "-c", _SSHD_REGISTER_SCRIPT,
        name, f"{name}@example.com", password, key_type, key_base64,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    site_env = dojo_run(
        "docker", "exec", "site", "python3", "-c",
        "import os; print(os.environ.get('DOJO_ENV', ''))",
    ).stdout.strip()
    assert payload["api_base"] == "http://site:8000/pwncollege_api/v1", payload
    assert payload["dojo_api"] == payload["api_base"], payload
    assert payload["dojo_env"] == site_env, payload
    assert payload["scheme"] == ("https" if site_env == "production" else "http"), payload
    assert payload["result"]["success"] is True, payload
    assert stored_key_values(name) == [normalized(ssh_keys["ecdsa"]["public"])]
    login(name, password)


@pytest.mark.parametrize(
    "verify_emails, expected_kind, expected_verified",
    [
        (True, "verification_email", False),
        (False, "successful_registration_email", True),
    ],
)
def test_ssh_onboarding_email_uses_forwarded_public_origin(
    ssh_keys, verify_emails, expected_kind, expected_verified
):
    name = random_name("sshemail")
    password = random_name("password")
    public_key = normalized(ssh_keys["ed25519"]["public"])
    key_type, key_base64 = public_key.split()
    code = f"""
from flask import current_app
from itsdangerous.url_safe import URLSafeTimedSerializer
from unittest.mock import patch
from dojo.api.v1 import auth as auth_api
from dojo.config import DOJO_SSH_SERVICE_KEY
from dojo.models import SSHKeys, Users, db

app = current_app._get_current_object()
client = app.test_client()
deliveries = []
real_get_config = auth_api.get_config
configured = lambda key, *args, **kwargs: {verify_emails!r} if key == "verify_emails" else real_get_config(key, *args, **kwargs)
token = URLSafeTimedSerializer(DOJO_SSH_SERVICE_KEY).dumps("ssh-onboarding")
try:
    with patch.object(auth_api, "get_config", side_effect=configured), \
         patch.object(auth_api, "can_send_mail", return_value=True), \
         patch.object(auth_api.email, "notify", side_effect=lambda kind, addr, url: deliveries.append((kind, addr, url))):
        response = client.post(
            "/pwncollege_api/v1/auth/register",
            headers={{
                "Authorization": f"Bearer sk-ssh-service-{{token}}",
                "Host": "dojo.example",
                "X-Forwarded-Proto": "https",
            }},
            json={{
                "name": {name!r},
                "email": {f'{name}@example.com'!r},
                "password": {password!r},
                "key_type": {key_type!r},
                "key_base64": {key_base64!r},
            }},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        user = Users.query.filter_by(name={name!r}).one()
        assert user.verified is {expected_verified!r}
        assert [key.value for key in SSHKeys.query.filter_by(user_id=user.id)] == [{public_key!r}]
        assert response.get_json()["data"]["verified"] is {expected_verified!r}
        with client.session_transaction() as browser_session:
            assert "id" not in browser_session
        assert len(deliveries) == 1, deliveries
        assert deliveries[0][0] == {expected_kind!r}, deliveries
        assert deliveries[0][1] == {f'{name}@example.com'!r}, deliveries
        assert deliveries[0][2].startswith("https://dojo.example/"), deliveries
finally:
    user = Users.query.filter_by(name={name!r}).first()
    if user:
        db.session.delete(user)
        db.session.commit()
print("SSH-EMAIL-CASE-PASSED")
"""
    output = flask_exec(code)
    assert "SSH-EMAIL-CASE-PASSED" in output.splitlines(), output


def test_ssh_onboarding_registration_obeys_registration_policy(ssh_keys):
    keys = [ssh_keys[name]["public"] for name in ("rsa", "ed25519", "ecdsa")]

    disabled_name = random_name("sshdisabled")
    disabled_type, disabled_blob = normalized(keys[0]).split()
    with server_config(registration_visibility="private"):
        response = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload={
                "name": disabled_name,
                "email": f"{disabled_name}@example.com",
                "password": random_name("password"),
                "key_type": disabled_type,
                "key_base64": disabled_blob,
            },
        )
    assert response.status_code == 403, response.text
    assert response.json() == {"success": False, "errors": ["Registration is currently disabled"]}
    assert user_count(disabled_name) == 0
    assert ssh_key_count(keys[0]) == 0

    limited_name = random_name("sshlimited")
    limited_type, limited_blob = normalized(keys[1]).split()
    limit = int(db_sql("SELECT count(*) FROM users WHERE banned = false AND hidden = false"))
    with server_config(num_users=limit):
        response = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload={
                "name": limited_name,
                "email": f"{limited_name}@example.com",
                "password": random_name("password"),
                "key_type": limited_type,
                "key_base64": limited_blob,
            },
        )
    assert response.status_code == 403, response.text
    assert response.json() == {"success": False, "errors": [f"Reached maximum users ({limit})"]}
    assert user_count(limited_name) == 0
    assert ssh_key_count(keys[1]) == 0

    coded_name = random_name("sshcoded")
    coded_type, coded_blob = normalized(keys[2]).split()
    coded_payload = {
        "name": coded_name,
        "email": f"{coded_name}@example.com",
        "password": random_name("password"),
        "key_type": coded_type,
        "key_base64": coded_blob,
    }
    with server_config(registration_code="SeCrEt"):
        missing = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload=coded_payload,
        )
        assert missing.status_code == 400, missing.text
        assert missing.json()["errors"] == ["Invalid registration code"]
        assert user_count(coded_name) == 0
        accepted = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload={**coded_payload, "registration_code": "secret"},
        )
    assert accepted.status_code == 200, accepted.text
    assert stored_key_values(coded_name) == [normalized(keys[2])]


def test_ssh_onboarding_registration_creates_account_and_key(ssh_keys):
    name = random_name("sshonboard")
    password = random_name("password")
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    session = requests.Session()

    response = register_request(
        session=session,
        headers=ssh_token_header("ssh-onboarding"),
        payload={
            "name": name,
            "email": f"{name}@example.com",
            "password": password,
            "key_type": key_type,
            "key_base64": key_base64,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True, response.json()
    assert stored_key_values(name) == [normalized(ssh_keys["ed25519"]["public"])]
    login(name, password)

    settings = session.get(f"{DOJO_URL}/settings", allow_redirects=False)
    assert settings.status_code == 302, \
        f"onboarding registration left a usable browser session: {settings.status_code}"
    assert "/login" in settings.headers.get("Location", ""), settings.headers


def test_ssh_onboarding_registration_is_atomic(dojo_user, ssh_keys):
    owner_name, owner_session = dojo_user
    public_key = ssh_keys["rsa"]["public"]
    key_type, key_base64 = normalized(public_key).split()
    assert add_ssh_key(owner_session, public_key).status_code == 200

    attempts = [
        (
            random_name("sshduplicate"),
            key_base64,
            ["SSH key, username, or email is already in use"],
        ),
        (random_name("sshinvalid"), "not-base64", None),
    ]
    for name, offered_key, expected_errors in attempts:
        response = register_request(
            headers=ssh_token_header("ssh-onboarding"),
            payload={
                "name": name,
                "email": f"{name}@example.com",
                "password": random_name("password"),
                "key_type": key_type,
                "key_base64": offered_key,
            },
        )
        assert response.status_code == 400, response.text
        if expected_errors is not None:
            assert response.json() == {"success": False, "errors": expected_errors}
        else:
            assert response.json()["errors"][0].startswith("Invalid SSH key:")
        assert db_sql(f"SELECT count(*) FROM users WHERE name = '{name}'").strip() == "0"

    assert stored_key_values(owner_name) == [normalized(public_key)]


def test_public_registration_integrity_conflict_is_reported_cleanly(dojo_user):
    name, _ = dojo_user
    code = f"""
from flask import current_app
from unittest.mock import patch
from dojo.api.v1 import auth as auth_api
from dojo.models import Users

app = current_app._get_current_object()
client = app.test_client()
with client.session_transaction() as browser_session:
    browser_session["nonce"] = "test-nonce"
client.environ_base["HTTP_CSRF_TOKEN"] = "test-nonce"
with patch.object(auth_api, "registration_errors", return_value=set()):
    response = client.post(
        "/pwncollege_api/v1/auth/register",
        json={{
            "name": {name!r},
            "email": {f'{name}@example.com'!r},
            "password": "password",
        }},
    )
assert response.status_code == 400, response.get_data(as_text=True)
assert response.get_json() == {{
    "success": False,
    "errors": ["Username or email is already in use"],
}}
assert Users.query.filter_by(name={name!r}).count() == 1
with client.session_transaction() as browser_session:
    assert "id" not in browser_session
print("PUBLIC-INTEGRITY-CONFLICT-PASSED")
"""
    output = flask_exec(code)
    assert "PUBLIC-INTEGRITY-CONFLICT-PASSED" in output.splitlines(), output


def test_ssh_onboarding_registration_rejects_invalid_tokens(ssh_keys):
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    headers = {
        "wrong tag": ssh_token_header("ssh-tui"),
        "wrong secret": ssh_token_header("ssh-onboarding", secret="not-the-key"),
        "expired": ssh_token_header("ssh-onboarding", backdate=3600),
    }
    for description, header in headers.items():
        name = random_name("sshbadtoken")
        response = register_request(
            headers=header,
            payload={
                "name": name,
                "email": f"{name}@example.com",
                "password": random_name("password"),
                "key_type": key_type,
                "key_base64": key_base64,
            },
        )
        assert response.status_code == 401, f"{description} was accepted: {response.text}"
        assert db_sql(f"SELECT count(*) FROM users WHERE name = '{name}'").strip() == "0"


def test_public_registration_ignores_onboarding_key_fields(ssh_keys):
    name = random_name("sshpublic")
    key_type, key_base64 = normalized(ssh_keys["ed25519"]["public"]).split()
    session = requests.Session()
    session.headers["CSRF-Token"] = parse_csrf_token(session.get(f"{DOJO_URL}/register").text)
    response = register_request(
        session=session,
        headers={},
        payload={
            "name": name,
            "email": f"{name}@example.com",
            "password": random_name("password"),
            "key_type": key_type,
            "key_base64": key_base64,
        },
    )
    assert response.status_code == 200, response.text
    assert key_count(name) == 0


def test_ssh_service_token_authenticates_and_respects_dojo_access(
    dojo_user, example_dojo, random_private_dojo, admin_session
):
    name, _ = dojo_user
    user_id = get_user_id(name)

    response = requests.get(DOJOS_ENDPOINT, headers=ssh_token_header([user_id, "ssh-tui"]))
    assert response.status_code == 200, response.text
    assert response.json()["success"] is True
    visible = [dojo["id"] for dojo in response.json()["dojos"]]
    assert example_dojo in visible, visible
    assert random_private_dojo not in visible, "a private dojo leaked to a token user without access"

    response = requests.get(DOJOS_ENDPOINT, headers=ssh_token_header([get_user_id("admin"), "ssh-tui"]))
    assert response.status_code == 200
    assert random_private_dojo in [dojo["id"] for dojo in response.json()["dojos"]], \
        "dojo visibility is not being computed per token user"

    response = requests.post(
        DOCKER_ENDPOINT,
        headers=ssh_token_header([user_id, "ssh-tui"]),
        json={"dojo": random_private_dojo, "module": "test-module",
              "challenge": "test-challenge", "practice": False},
    )
    assert response.json()["success"] is False, response.json()
    assert response.json()["error"] == "Invalid dojo", response.json()
    with pytest.raises(RuntimeError):
        get_outer_container_for(f"user_{user_id}")


def test_ssh_service_token_starts_a_challenge_for_its_own_user(dojo_user, example_dojo):
    name, _ = dojo_user
    user_id = get_user_id(name)
    remove_workspace_container(name)

    try:
        response = requests.post(
            DOCKER_ENDPOINT,
            headers=ssh_token_header([user_id, "ssh-tui"]),
            json={"dojo": example_dojo, "module": "hello", "challenge": "banana", "practice": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True, response.json()

        node = get_outer_container_for(f"user_{user_id}")
        label = dojo_run("docker", "inspect", "-f", '{{index .Config.Labels "dojo.user_id"}}',
                         f"user_{user_id}", container=node).stdout.strip()
        assert label == str(user_id), f"the container was started for user {label}, not {user_id}"
        assert workspace_run("hostname", user=name).stdout.strip() == "hello~banana"
    finally:
        remove_workspace_container(name)


def test_ssh_service_token_rejects_forged_stale_and_unknown_tokens(dojo_user):
    name, _ = dojo_user
    user_id = get_user_id(name)

    unauthorized = {
        "garbage signature": "WyIxIiwic3NoLXR1aSJd.aaaa.bbbb",
        "wrong secret": mint_ssh_token([user_id, "ssh-tui"], secret="not-the-key"),
        "wrong tag": mint_ssh_token([user_id, "cli-auth-token"]),
        "non-list payload": mint_ssh_token(user_id),
        "empty list": mint_ssh_token([]),
        "short list": mint_ssh_token([user_id]),
        "long list": mint_ssh_token([user_id, "ssh-tui", "extra"]),
        "string user id": mint_ssh_token([str(user_id), "ssh-tui"]),
        "boolean user id": mint_ssh_token([True, "ssh-tui"]),
        "expired": mint_ssh_token([user_id, "ssh-tui"], backdate=3600),
    }
    for description, token in unauthorized.items():
        response = requests.get(DOJOS_ENDPOINT,
                                headers={"Authorization": f"Bearer sk-ssh-service-{token}"})
        assert response.status_code == 401, f"{description} was accepted: {response.status_code}"
        assert response.json() == {"success": False,
                                   "error": "Failed to authenticate ssh service token."}, response.json()

    missing_user_id = int(db_sql("SELECT COALESCE(MAX(id), 0) + 1000 FROM users"))
    response = requests.get(DOJOS_ENDPOINT, headers=ssh_token_header([missing_user_id, "ssh-tui"]))
    assert response.status_code == 404, response.status_code
    assert response.json() == {"success": False, "error": "User not found."}, response.json()

    response = requests.get(DOJOS_ENDPOINT, headers=ssh_token_header([user_id, "ssh-tui"]))
    assert response.status_code == 200 and response.json()["success"] is True, \
        "a freshly minted token for the same user should still work"


def test_ssh_service_token_rejects_banned_user(dojo_user):
    name, _ = dojo_user
    user_id = get_user_id(name)
    db_sql(f"UPDATE users SET banned = true WHERE id = {user_id}")
    try:
        response = requests.get(DOJOS_ENDPOINT, headers=ssh_token_header([user_id, "ssh-tui"]))
        assert response.status_code == 404, response.text
        assert response.json() == {"success": False, "error": "User not found."}
    finally:
        db_sql(f"UPDATE users SET banned = false WHERE id = {user_id}")


def test_ssh_service_token_leaves_no_reusable_session(dojo_user, ssh_keys):
    name, _ = dojo_user
    user_id = get_user_id(name)
    session = requests.Session()

    response = session.get(DOJOS_ENDPOINT, headers=ssh_token_header([user_id, "ssh-tui"]))
    assert response.status_code == 200 and response.json()["success"] is True

    response = session.get(f"{DOJO_URL}/settings", allow_redirects=False)
    assert response.status_code in (302, 403), f"token auth left a usable session: {response.status_code}"
    if response.status_code == 302:
        assert "/login" in response.headers.get("Location", ""), response.headers

    response = session.post(SSH_KEY_ENDPOINT, json={"ssh_key": normalized(ssh_keys["rsa"]["public"])})
    assert response.status_code == 403, response.status_code
    assert key_count(name) == 0


def test_ssh_service_token_preserves_existing_browser_session(dojo_user, second_user, ssh_keys):
    name, browser_session = dojo_user
    other_name, _ = second_user

    response = browser_session.get(
        DOJOS_ENDPOINT,
        headers=ssh_token_header([get_user_id(other_name), "ssh-tui"]),
    )
    assert response.status_code == 200 and response.json()["success"] is True

    response = add_ssh_key(browser_session, ssh_keys["ed25519"]["public"])
    assert response.status_code == 200, response.text
    assert key_count(name) == 1
    assert key_count(other_name) == 0


def test_ssh_service_token_replaces_admin_privileges_for_request_and_restores_them(
    dojo_user, random_private_dojo, admin_session
):
    name, _ = dojo_user
    response = admin_session.get(
        DOJOS_ENDPOINT,
        headers=ssh_token_header([get_user_id(name), "ssh-tui"]),
    )
    assert response.status_code == 200, response.text
    visible = [dojo["id"] for dojo in response.json()["dojos"]]
    assert random_private_dojo not in visible, \
        "the token user inherited the browser session's admin privileges"

    response = admin_session.get(DOJOS_ENDPOINT)
    assert response.status_code == 200, response.text
    visible = [dojo["id"] for dojo in response.json()["dojos"]]
    assert random_private_dojo in visible, "the admin browser session was not restored"


def test_ssh_service_token_restores_session_after_downstream_exception(dojo_user):
    name, _ = dojo_user
    user_id = get_user_id(name)
    token = mint_ssh_token([user_id, "ssh-tui"])
    code = f"""
from flask import current_app, session
from dojo.api.v1.user import authed_only_ssh

app = current_app._get_current_object()
with app.test_request_context(
    "/token-exception",
    headers={{"Authorization": {f'Bearer sk-ssh-service-{token}'!r}}},
):
    session.update({{"id": {get_user_id('admin')}, "name": "admin", "custom": "preserved"}})
    original = dict(session)

    @authed_only_ssh
    def fail():
        assert session["id"] == {user_id}
        assert "custom" not in session
        raise RuntimeError("downstream failure")

    try:
        fail()
    except RuntimeError as error:
        assert str(error) == "downstream failure"
    else:
        raise AssertionError("downstream exception was swallowed")
    assert dict(session) == original
print("TOKEN-EXCEPTION-SESSION-PASSED")
"""
    output = flask_exec(code)
    assert "TOKEN-EXCEPTION-SESSION-PASSED" in output.splitlines(), output


def test_ssh_service_token_preserves_downstream_404_and_browser_session(
    dojo_user, second_user, ssh_keys
):
    name, browser_session = dojo_user
    token_name, _ = second_user
    missing_dojo = random_name("missing-dojo-")

    response = browser_session.get(
        f"{DOJOS_ENDPOINT}/{missing_dojo}/modules",
        headers=ssh_token_header([get_user_id(token_name), "ssh-tui"]),
    )
    assert response.status_code == 404, response.text
    assert "Failed to authenticate ssh service token." not in response.text

    response = add_ssh_key(browser_session, ssh_keys["ed25519"]["public"])
    assert response.status_code == 200, response.text
    assert key_count(name) == 1
    assert key_count(token_name) == 0


def test_non_ssh_authorization_headers_fall_through_to_session_auth(dojo_user, ssh_keys):
    name, session = dojo_user

    response = session.get(DOJOS_ENDPOINT, headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert response.status_code == 200 and response.json()["success"] is True, response.text

    response = session.get(DOJOS_ENDPOINT, headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 200 and response.json()["success"] is True, response.text

    response = session.get(DOJOS_ENDPOINT)
    assert response.status_code == 200 and response.json()["success"] is True

    response = requests.post(
        DOCKER_ENDPOINT,
        headers={"Authorization": "Bearer nonsense"},
        json={"dojo": "example", "module": "hello", "challenge": "apple", "practice": False},
    )
    assert response.status_code == 403, \
        f"a non-ssh bearer token did not fall through to anonymous auth: {response.status_code}"

    response = requests.post(SSH_KEY_ENDPOINT, headers={"Authorization": "Bearer nonsense"},
                             json={"ssh_key": normalized(ssh_keys["rsa"]["public"])})
    assert response.status_code == 403, \
        f"a non-ssh bearer token produced {response.status_code} instead of the anonymous outcome"
    assert key_count(name) == 0
