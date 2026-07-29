import base64
import json
import os
import random
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
    get_outer_container_for,
    get_user_id,
    login,
    remove_workspace_container,
    start_challenge,
    workspace_run,
)

SSH_KEY_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/ssh_key"
DOJOS_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/dojos"
DOCKER_ENDPOINT = f"{DOJO_URL}/pwncollege_api/v1/docker"

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


def forced_command_line(user_id, public_key):
    return f'command="{ENTER_COMMAND} user_{user_id}" {normalized(public_key)}'


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


def mint_ssh_token(payload, *, secret="", backdate=0):
    result = dojo_run("docker", "exec", "sshd", "python3", "-c", _MINT_TOKEN_SCRIPT,
                      json.dumps(payload), secret, str(backdate))
    return result.stdout.strip()


def ssh_token_header(payload, **kwargs):
    return {"Authorization": f"Bearer sk-ssh-service-{mint_ssh_token(payload, **kwargs)}"}


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


def test_authorized_keys_command_binds_each_key_to_its_owner(dojo_user, ssh_keys):
    name, session = dojo_user
    user_id = get_user_id(name)
    ed25519 = ssh_keys["ed25519"]["public"]
    injected_marker = f"pwned-{name}"

    response = add_ssh_key(session, f'command="touch /tmp/{injected_marker}",no-pty {ed25519}')
    assert response.status_code == 200, response.text

    lines = authorized_keys_lines()
    expected = forced_command_line(user_id, ed25519)
    owned = [line for line in lines if line.endswith(normalized(ed25519))]
    assert owned == [expected], f"expected exactly one forced-command line for the key, got {owned}"
    assert owned[0].count("command=") == 1, f"a second forced command was injected: {owned[0]!r}"
    assert injected_marker not in "\n".join(lines), "user-supplied option leaked into the sshd key stream"

    listing = dojo_run("docker", "exec", "sshd", "ls", "/tmp").stdout
    assert injected_marker not in listing, "user-supplied forced command executed in the sshd container"

    assert delete_ssh_key(session, ed25519).status_code == 200
    assert expected not in authorized_keys_lines(), "auth.py served a deleted key"


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
    assert result.returncode == 255, f"the smuggled key authenticated: rc={result.returncode}"
    assert "Permission denied" in result.stderr, result.stderr


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


def test_duplicate_key_rejected_and_db_session_recovers(dojo_user, ssh_keys):
    name, session = dojo_user
    rsa = ssh_keys["rsa"]["public"]

    assert add_ssh_key(session, rsa).status_code == 200
    response = add_ssh_key(session, rsa)
    assert response.status_code == 400, response.status_code
    assert response.json() == {"success": False, "error": "SSH Key already in use"}, response.json()
    assert key_count(name) == 1

    response = add_ssh_key(session, ssh_keys["ed25519"]["public"])
    assert response.status_code == 200, f"session was left unusable by the rollback: {response.text}"
    assert key_count(name) == 2


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


def test_settings_page_scopes_keys_to_owner(dojo_user, second_user, ssh_keys):
    _, session = dojo_user
    _, other_session = second_user
    mine = normalized(ssh_keys["rsa"]["public"])
    theirs = normalized(ssh_keys["ed25519"]["public"])

    assert add_ssh_key(session, mine).status_code == 200
    assert add_ssh_key(other_session, theirs).status_code == 200

    page = session.get(f"{DOJO_URL}/settings")
    assert page.status_code == 200
    assert mine in page.text, "the user's own key is missing from their settings page"
    assert theirs not in page.text, "another user's key leaked into the settings page"

    page = other_session.get(f"{DOJO_URL}/settings")
    assert page.status_code == 200
    assert theirs in page.text
    assert mine not in page.text


def test_user_deletion_cascades_keys(dojo_user, second_user, ssh_keys):
    name, session = dojo_user
    other_name, other_session = second_user
    user_id = get_user_id(name)
    rsa = ssh_keys["rsa"]["public"]

    assert add_ssh_key(session, rsa).status_code == 200
    assert key_count(name) == 1
    assert forced_command_line(user_id, rsa) in authorized_keys_lines()

    db_sql(f"DELETE FROM users WHERE id = {user_id}")

    assert int(db_sql(f"SELECT count(*) FROM ssh_keys WHERE user_id = {user_id}")) == 0, \
        "deleting a user left their ssh keys behind"
    assert forced_command_line(user_id, rsa) not in authorized_keys_lines(), \
        "a deleted user's key is still served to sshd"

    assert add_ssh_key(other_session, rsa).status_code == 200, \
        "the deleted user's key value never became available again"
    assert key_count(other_name) == 1


def test_malformed_key_row_does_not_break_auth(workspace_ssh_user, dojo_user):
    other_name, _ = dojo_user
    owner_id = get_user_id(workspace_ssh_user.name)
    owner_line = forced_command_line(owner_id, workspace_ssh_user.keys["rsa"]["public"])

    db_sql(f"INSERT INTO ssh_keys (user_id, value) VALUES ({get_user_id(other_name)}, '')")
    try:
        assert owner_line in authorized_keys_lines(), \
            "a blank ssh_keys row suppressed a healthy user's key"
        result = ssh_run(workspace_ssh_user.keys["rsa"]["private_file"], "whoami")
        assert result.returncode == 0, result.stderr
        assert "hacker" in result.stdout
    finally:
        db_sql("DELETE FROM ssh_keys WHERE value = ''")


def test_every_registered_key_reaches_the_owners_workspace(workspace_ssh_user):
    assert key_count(workspace_ssh_user.name) == 3

    for key_type in ("rsa", "ed25519", "ecdsa"):
        result = ssh_run(workspace_ssh_user.keys[key_type]["private_file"], "whoami; hostname")
        assert result.returncode == 0, f"{key_type} key failed to authenticate: {result.stderr}"
        assert "hacker" in result.stdout, f"{key_type}: {result.stdout!r}"
        assert "hello~apple" in result.stdout, f"{key_type}: {result.stdout!r}"

    user_id = get_user_id(workspace_ssh_user.name)
    node = get_outer_container_for(f"user_{user_id}")
    running = dojo_run("docker", "inspect", "-f", "{{.State.Running}}", f"user_{user_id}",
                       container=node).stdout.strip()
    assert running == "true", f"ssh reached a container that is not running on {node}"


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


def test_sftp_session_fails_promptly(workspace_ssh_user, tmp_path):
    source = tmp_path / "sftp_payload.txt"
    source.write_text("sftp-payload\n")
    batch = tmp_path / "batch"
    batch.write_text(f"put {source} /home/hacker/sftp_up.txt\n")

    started = time.time()
    result = subprocess.run(
        ["sftp", *SSH_BASE_OPTIONS, "-P", str(SSH_PORT),
         "-i", workspace_ssh_user.keys["ed25519"]["private_file"],
         "-b", str(batch), f"hacker@{DOJO_SSH_HOST}"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
    )
    elapsed = time.time() - started
    assert elapsed < 30, f"the sftp session hung for {elapsed:.1f}s"
    assert result.returncode != 0, "sftp unexpectedly succeeded without an sftp server in the workspace"


@pytest.mark.xfail(reason="the workspace image ships no scp binary, so legacy scp transfers fail", strict=False)
def test_scp_legacy_transfer_round_trips(workspace_ssh_user, tmp_path):
    private_key = workspace_ssh_user.keys["ed25519"]["private_file"]
    payload = "scp-payload-round-trip"
    source = tmp_path / "scp_up.txt"
    source.write_text(payload + "\n")

    upload = subprocess.run(
        ["scp", "-O", *SSH_BASE_OPTIONS, "-P", str(SSH_PORT), "-i", private_key,
         str(source), f"hacker@{DOJO_SSH_HOST}:/home/hacker/scp_up.txt"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert upload.returncode == 0, upload.stderr
    assert workspace_run("cat /home/hacker/scp_up.txt",
                         user=workspace_ssh_user.name).stdout.strip() == payload

    destination = tmp_path / "scp_down.txt"
    download = subprocess.run(
        ["scp", "-O", *SSH_BASE_OPTIONS, "-P", str(SSH_PORT), "-i", private_key,
         f"hacker@{DOJO_SSH_HOST}:/home/hacker/scp_up.txt", str(destination)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
    )
    assert download.returncode == 0, download.stderr
    assert destination.read_text().strip() == payload


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
        assert result.returncode == 255, "an unregistered key authenticated"
        assert "Permission denied" in result.stderr, result.stderr

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
        assert result.returncode == 255, \
            f"the deleted key still authenticated (rc={result.returncode}, expected an auth failure)"
        assert "Permission denied" in result.stderr, result.stderr

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


def test_banned_user_cannot_ssh(dojo_user, ssh_keys):
    name, session = dojo_user
    user_id = get_user_id(name)
    assert add_ssh_key(session, ssh_keys["ed25519"]["public"]).status_code == 200

    db_sql(f"UPDATE users SET banned = true WHERE id = {user_id}")
    try:
        assert forced_command_line(user_id, ssh_keys["ed25519"]["public"]) not in authorized_keys_lines(), \
            "a banned user's key is still served to sshd"
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


def test_non_ssh_authorization_headers_fall_through_to_session_auth(dojo_user, ssh_keys):
    name, session = dojo_user

    response = session.get(DOJOS_ENDPOINT, headers={"Authorization": "Basic Zm9vOmJhcg=="})
    assert response.status_code == 200 and response.json()["success"] is True, response.text

    response = session.get(DOJOS_ENDPOINT)
    assert response.status_code == 200 and response.json()["success"] is True

    response = requests.post(SSH_KEY_ENDPOINT, headers={"Authorization": "Bearer nonsense"},
                             json={"ssh_key": normalized(ssh_keys["rsa"]["public"])})
    assert response.status_code == 403, \
        f"a non-ssh bearer token produced {response.status_code} instead of the anonymous outcome"
    assert key_count(name) == 0
