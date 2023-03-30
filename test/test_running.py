import pytest
import requests

unauthenticated_urls = ["/", "/dojos", "/login", "/register"]

@pytest.mark.parametrize("endpoint", unauthenticated_urls)
def test_unauthenticated_return_200(endpoint):
    response = requests.get(f"http://localhost{endpoint}")
    assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
