import pytest
import requests
from utils import login, DOJO_URL, dojo_run


def test_slow_query_logging(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"] == 1
    
    result = dojo_run("sh", "-c", "docker logs ctfd 2>&1 | grep 'Slow query' | tail -5")
    logs = result.stdout
    
    assert "Slow query:" in logs
    assert "time=" in logs
    
    assert float(logs.split("time=")[1].split("s")[0]) >= 1.0
    
    assert "user_id=" in logs
    
    assert "traceback=" in logs
    assert "dojo_plugin/api/v1/test_error.py" in logs
    

def test_fast_query_not_logged(random_user_session):
    dojo_run("sh", "-c", "docker logs ctfd 2>&1 | grep 'Slow query' | wc -l > /tmp/before_count")
    before_count = int(dojo_run("cat", "/tmp/before_count").stdout.strip())
    
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200
    
    dojo_run("sh", "-c", "docker logs ctfd 2>&1 | grep 'Slow query' | wc -l > /tmp/after_count")
    after_count = int(dojo_run("cat", "/tmp/after_count").stdout.strip())
    
    assert after_count == before_count, "Fast queries should not be logged"

    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"] == 1

    dojo_run("sh", "-c", "docker logs ctfd 2>&1 | grep 'Slow query' | wc -l > /tmp/after_count")
    final_count = int(dojo_run("cat", "/tmp/after_count").stdout.strip())
    assert final_count > after_count, "Second slow query should not be logged"
