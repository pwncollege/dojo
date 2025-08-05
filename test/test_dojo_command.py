import subprocess
import requests
import pytest
import time

from utils import DOJO_URL, workspace_run, start_challenge, solve_challenge, get_user_id


def test_integrations_solve_endpoint(example_dojo, random_user):
    uid, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)
    
    auth_token = workspace_run("cat /run/dojo/var/auth_token", user=uid, root=True).stdout.strip()
    flag = workspace_run("cat /flag", user=uid, root=True).stdout.strip()
    
    response = requests.post(
        f"{DOJO_URL}/pwncollege_api/v1/integrations/solve",
        json={"auth_token": auth_token, "submission": flag}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "solved"
    
    response = requests.post(
        f"{DOJO_URL}/pwncollege_api/v1/integrations/solve",
        json={"auth_token": auth_token, "submission": flag}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "already_solved"


def test_dojo_command_files(example_dojo, random_user):
    uid, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)
    
    result = workspace_run("ls -la /run/dojo/bin/dojo", user=uid)
    assert result.returncode == 0, f"dojo command should exist, got {result.stderr}"


def test_dojo_command_submit(random_user, example_dojo):
    uid, session = random_user
    start_challenge(example_dojo, "hello", "apple", session=session)

    result = workspace_run("dojo submit 'pwn.college{wrong_flag}'", user=uid, check=False)
    assert "incorrect" in result.stdout, f"Expected error message, got {result.stdout}"
    assert result.returncode == 1, f"Expected failure, got return code {result.returncode}"
    
    flag = workspace_run("cat /flag", user=uid, root=True).stdout.strip()
    result = workspace_run(f"dojo submit '{flag}'", user=uid, check=False)
    assert "Congratulations! Flag accepted!" in result.stdout, f"Expected success message, got {result.stdout}"
    assert result.returncode == 0, f"Expected success, got return code {result.returncode}"
    
    flag = workspace_run("cat /flag", user=uid, root=True).stdout.strip()
    result = workspace_run(f"dojo submit '{flag}'", user=uid, check=False)
    assert "You already solved this challenge!" in result.stdout, f"Expected already solved message, got {result.stdout}"
    assert result.returncode == 0, f"Expected success, got return code {result.returncode}"
