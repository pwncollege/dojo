import time
from utils import DOJO_URL, journalctl


def slow_query_logs():
    return [line for line in journalctl("dojo-ctfd", "--since", "-10m").stdout.splitlines()
            if "Slow query" in line]


def test_slow_query_logging(random_user_session):
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"] == 1
    
    logs = "\n".join(slow_query_logs()[-5:])
    
    assert "Slow query:" in logs
    assert "dojo_plugin/api/v1/test_error.py" in logs
    

def test_fast_query_not_logged(random_user_session):
    before_count = len(slow_query_logs())
    
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos")
    assert response.status_code == 200
    
    after_count = len(slow_query_logs())
    
    assert after_count == before_count, "Fast queries should not be logged"

    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"] == 1

    final_count = len(slow_query_logs())
    assert final_count > after_count, "Second slow query should be logged"

def test_capped_query(random_user_session):
    for _ in range(2):
        start = time.time()
        response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/capped_query")
        end = time.time()
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["result"] == "TIMEOUT"
        assert 0.4 < end-start < 0.80

    # other slow queries still work
    response = random_user_session.get(f"{DOJO_URL}/pwncollege_api/v1/test_error/slow_query")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result"] == 1
