import pytest
import subprocess
import time
import tempfile
import os
from pathlib import Path
import threading

from utils import DOJO_URL, login, dojo_run, workspace_run, start_challenge


def add_ssh_key(session, ssh_key):
    response = session.post(
        f"{DOJO_URL}/pwncollege_api/v1/ssh_key",
        json={"ssh_key": ssh_key}
    )
    return response


def delete_ssh_key(session, ssh_key):
    key_parts = ssh_key.split()
    normalized_key = f"{key_parts[0]} {key_parts[1]}"
    response = session.delete(
        f"{DOJO_URL}/pwncollege_api/v1/ssh_key",
        json={"ssh_key": normalized_key}
    )
    return response


def verify_ssh_access(private_key_file, should_work=True):
    result = ssh_command(private_key_file, "whoami")
    if should_work:
        assert result.returncode == 0
        assert "hacker" in result.stdout
    else:
        assert result.returncode != 0
    return result




@pytest.fixture
def temp_ssh_keys():
    keys = {}
    
    with tempfile.TemporaryDirectory() as tmpdir:
        rsa_key_path = os.path.join(tmpdir, 'test_rsa')
        subprocess.run([
            'ssh-keygen', '-t', 'rsa', '-b', '2048', '-f', rsa_key_path, '-N', ''
        ], check=True, capture_output=True)
        
        with open(rsa_key_path, 'r') as f:
            rsa_private = f.read()
        with open(f'{rsa_key_path}.pub', 'r') as f:
            rsa_public = f.read().strip()
        
        ed25519_key_path = os.path.join(tmpdir, 'test_ed25519')
        subprocess.run([
            'ssh-keygen', '-t', 'ed25519', '-f', ed25519_key_path, '-N', ''
        ], check=True, capture_output=True)
        
        with open(ed25519_key_path, 'r') as f:
            ed25519_private = f.read()
        with open(f'{ed25519_key_path}.pub', 'r') as f:
            ed25519_public = f.read().strip()
        
        keys['rsa'] = {'private': rsa_private, 'public': rsa_public}
        keys['ed25519'] = {'private': ed25519_private, 'public': ed25519_public}
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_rsa') as f:
            f.write(rsa_private)
            os.chmod(f.name, 0o600)
            keys['rsa']['private_file'] = f.name
            
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='_ed25519') as f:
            f.write(ed25519_private)
            os.chmod(f.name, 0o600)
            keys['ed25519']['private_file'] = f.name
    
    yield keys
    
    for key_type in keys.values():
        if 'private_file' in key_type:
            Path(key_type['private_file']).unlink(missing_ok=True)

def ssh_command(private_key_file, command="echo 'SSH test successful'"):
    ssh_host = os.getenv('DOJO_SSH_HOST', 'localhost')
    ssh_port = int(os.getenv('DOJO_SSH_PORT', '22'))
    
    ssh_cmd = [
        'ssh',
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'PasswordAuthentication=no',
        '-o', 'ConnectTimeout=10',
        '-i', private_key_file,
        '-p', str(ssh_port),
        f'hacker@{ssh_host}',
        command
    ]
    
    result = subprocess.run(
        ssh_cmd,
        capture_output=True,
        text=True,
        timeout=30
    )
    return result

def test_add_single_ssh_key(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'])

def test_add_multiple_ssh_keys(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    response = add_ssh_key(session, temp_ssh_keys['ed25519']['public'])
    assert response.status_code == 200
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'])
    verify_ssh_access(temp_ssh_keys['ed25519']['private_file'])

def test_delete_ssh_key(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'])
    
    response = delete_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    assert response.json()["success"] is True
    
    time.sleep(2)
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'], should_work=False)

def test_change_ssh_key(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'])
    
    response = delete_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    response = add_ssh_key(session, temp_ssh_keys['ed25519']['public'])
    assert response.status_code == 200
    
    time.sleep(2)
    
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'], should_work=False)
    verify_ssh_access(temp_ssh_keys['ed25519']['private_file'])

def test_add_invalid_ssh_key(random_user):
    user_id, session = random_user
    
    invalid_keys = [
        "not a valid ssh key",
        "ssh-rsa",
        "ssh-rsa AAAAB3NzaC1yc2EA",
        "ssh-dss AAAAB3NzaC1kc3MA",
        "ssh-rsa AAAAB3NzaC1yc2EA!!!",
    ]
    
    for invalid_key in invalid_keys:
        response = add_ssh_key(session, invalid_key)
        assert response.status_code == 400
        assert response.json().get("success") is False
        assert "Invalid SSH Key" in response.json().get("error", "")

def test_add_duplicate_ssh_key(random_user, temp_ssh_keys):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 400
    assert "already in use" in response.json().get("error", "")

def test_delete_nonexistent_ssh_key(random_user, temp_ssh_keys):
    user_id, session = random_user
    
    response = delete_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 400
    assert "does not exist" in response.json().get("error", "")

def test_ssh_command_execution(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    
    commands = [
        ("whoami", "hacker"),
        ("pwd", "/home/hacker"),
        ("id -un", "hacker"),
        ("ls /", "bin"),
    ]
    
    for cmd, expected in commands:
        result = ssh_command(temp_ssh_keys['rsa']['private_file'], cmd)
        if result.returncode != 0:
            print(f"Command '{cmd}' failed with code {result.returncode}")
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
        assert result.returncode == 0
        if expected not in result.stdout:
            print(f"Expected '{expected}' not found in output of '{cmd}'")
            print(f"stdout: {repr(result.stdout)}")
        assert expected in result.stdout

def test_ssh_key_with_comment(random_user, temp_ssh_keys):
    user_id, session = random_user
    
    key_with_comment = f"{temp_ssh_keys['rsa']['public']} test@example.com"
    
    response = add_ssh_key(session, key_with_comment)
    assert response.status_code == 200

def test_ssh_key_sql_injection_attempt(random_user, temp_ssh_keys):
    user_id, session = random_user
    
    malicious_keys = [
        f"{temp_ssh_keys['rsa']['public']} '; DROP TABLE users; --",
        f"{temp_ssh_keys['rsa']['public']} ' OR '1'='1",
        f"{temp_ssh_keys['rsa']['public']} \"; DROP TABLE ssh_keys; --",
    ]
    
    for key in malicious_keys:
        response = add_ssh_key(session, key)
        assert response.status_code in [200, 400]

def test_ssh_key_command_injection_attempt(random_user):
    user_id, session = random_user
    
    malicious_keys = [
        "ssh-rsa AAAAB3NzaC1yc2EA; cat /etc/passwd",
        "ssh-rsa AAAAB3NzaC1yc2EA`whoami`",
        "ssh-rsa AAAAB3NzaC1yc2EA$(reboot)",
    ]
    
    for key in malicious_keys:
        response = add_ssh_key(session, key)
        assert response.status_code == 400 or response.json().get("success") is False

def test_ssh_key_persistence(random_user, temp_ssh_keys, example_dojo):
    user_id, session = random_user
    
    response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
    assert response.status_code == 200
    
    start_challenge("example", "hello", "apple", session=session, wait=5)
    verify_ssh_access(temp_ssh_keys['rsa']['private_file'])

def test_concurrent_ssh_key_operations(random_user, temp_ssh_keys):
    user_id, session = random_user
    
    results = []
    
    def add_key():
        response = add_ssh_key(session, temp_ssh_keys['rsa']['public'])
        results.append(('add', response.status_code))
    
    def delete_key():
        response = delete_ssh_key(session, temp_ssh_keys['rsa']['public'])
        results.append(('delete', response.status_code))
    
    threads = []
    for _ in range(3):
        threads.append(threading.Thread(target=add_key))
        threads.append(threading.Thread(target=delete_key))
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join()
    
    for op, status in results:
        assert status in [200, 400]
