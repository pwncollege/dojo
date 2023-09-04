import pytest
import requests

UNAUTHENTICATED_URLS = ["/", "/dojos", "/login", "/register"]

@pytest.mark.parametrize("endpoint", UNAUTHENTICATED_URLS)
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"http://localhost{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
