import pytest
import requests

from utils import DOJO_HOST, TEST_DOJOS_LOCATION, create_dojo_yml


def test_module_and_challenge_visibility(visibility_test_dojo, random_user_session, admin_session):
    # Random user needs to join the dojo first
    join_response = random_user_session.get(f"http://{DOJO_HOST}/dojo/{visibility_test_dojo}/join/")
    assert join_response.status_code == 200
    
    random_response = random_user_session.get(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{visibility_test_dojo}/modules")
    assert random_response.status_code == 200
    random_modules = random_response.json()["modules"]
    
    # Module1 has future visibility, so it should NOT be returned for random users
    assert len(random_modules) == 1, f"Random user should see only 1 module, but got {len(random_modules)}"
    assert random_modules[0]["id"] == "module2", f"Random user should see module2, but got {random_modules[0]['id']}"
    
    # Module2 should have only challenge-c visible (challenge-b has future visibility)
    module2_challenges = random_modules[0]["challenges"]
    assert len(module2_challenges) == 1, f"Random user should see only 1 challenge in module2, but got {len(module2_challenges)}"
    assert module2_challenges[0]["id"] == "challenge-c", f"Random user should see challenge-c, but got {module2_challenges[0]['id']}"
    
    admin_response = admin_session.get(f"http://{DOJO_HOST}/pwncollege_api/v1/dojos/{visibility_test_dojo}/modules")
    assert admin_response.status_code == 200
    admin_modules = admin_response.json()["modules"]
    
    assert len(admin_modules) == 2, f"Admin should see 2 modules, but got {len(admin_modules)}"
    
    admin_module1 = next((m for m in admin_modules if m["id"] == "module1"), None)
    assert admin_module1 is not None, "Admin should see module1"
    assert len(admin_module1["challenges"]) == 1, f"Admin should see 1 challenge in module1, but got {len(admin_module1['challenges'])}"
    assert admin_module1["challenges"][0]["id"] == "challenge-a", f"Admin should see challenge-a in module1"
    
    admin_module2 = next((m for m in admin_modules if m["id"] == "module2"), None)
    assert admin_module2 is not None, "Admin should see module2"
    assert len(admin_module2["challenges"]) == 2, f"Admin should see 2 challenges in module2, but got {len(admin_module2['challenges'])}"
    
    challenge_ids = [c["id"] for c in admin_module2["challenges"]]
    assert "challenge-b" in challenge_ids, "Admin should see challenge-b in module2"
    assert "challenge-c" in challenge_ids, "Admin should see challenge-c in module2"


def test_module_and_challenge_visibility_rendered_page(visibility_test_dojo, random_user_session, admin_session):
    # Test the actual rendered module pages for visibility
    join_response = random_user_session.get(f"http://{DOJO_HOST}/dojo/{visibility_test_dojo}/join/")
    assert join_response.status_code == 200
    
    # Try to access module1 directly as random user - module has future visibility
    # The page should still be accessible (URL works) but might show limited content
    module1_page = random_user_session.get(f"http://{DOJO_HOST}/{visibility_test_dojo}/module1")
    assert module1_page.status_code == 200
    module1_text = module1_page.text
    
    # Module 1 page should exist and show the module name
    assert 'Module 1' in module1_text or 'module1' in module1_text.lower(), "Module 1 page should be accessible"
    
    # Challenge A should NOT be shown since module has future visibility
    assert 'Challenge A' not in module1_text, "Challenge A should not be shown to random user due to module's future visibility"
    
    # Check module2 page for challenge visibility  
    module2_page = random_user_session.get(f"http://{DOJO_HOST}/{visibility_test_dojo}/module2")
    assert module2_page.status_code == 200
    module2_text = module2_page.text
    
    # Module 2 should be fully accessible
    assert 'Module 2' in module2_text or 'module2' in module2_text.lower(), "Module 2 should be accessible"
    
    # Only Challenge C should be shown (Challenge B has future visibility)
    assert 'Challenge B' not in module2_text, "Challenge B should NOT be shown due to future visibility"
    assert 'Challenge C' in module2_text, "Challenge C should be shown in module2"
    
    # The key difference is in the API - test that trying to start challenge-b fails for random user
    # but challenge-c can be started
    start_challenge_c = random_user_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/docker", json={
        "dojo": visibility_test_dojo,
        "module": "module2",
        "challenge": "challenge-c",
        "practice": False
    })
    # Challenge C should be startable
    assert start_challenge_c.status_code == 200, "Random user should be able to start challenge-c"
    
    start_challenge_b = random_user_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/docker", json={
        "dojo": visibility_test_dojo,
        "module": "module2", 
        "challenge": "challenge-b",
        "practice": False
    })
    # Challenge B should not be startable due to future visibility
    assert start_challenge_b.status_code == 200  # API returns 200 even on failure
    response_data = start_challenge_b.json()
    assert not response_data.get("success", True), "Random user should not be able to start challenge-b"
    
    # Test admin view - everything should be fully accessible
    # Check module1 page for admin
    admin_module1_page = admin_session.get(f"http://{DOJO_HOST}/{visibility_test_dojo}/module1")
    assert admin_module1_page.status_code == 200
    assert 'Challenge A' in admin_module1_page.text, "Admin should see Challenge A in module1"
    
    # Admin should be able to start any challenge
    admin_start_challenge_a = admin_session.post(f"http://{DOJO_HOST}/pwncollege_api/v1/docker", json={
        "dojo": visibility_test_dojo,
        "module": "module1",
        "challenge": "challenge-a",
        "practice": False
    })
    assert admin_start_challenge_a.status_code == 200
    assert admin_start_challenge_a.json().get("success", False), "Admin should be able to start challenge-a"
    
    # Check module2 page for admin  
    admin_module2_page = admin_session.get(f"http://{DOJO_HOST}/{visibility_test_dojo}/module2")
    assert admin_module2_page.status_code == 200
    admin_module2_text = admin_module2_page.text
    assert 'Challenge B' in admin_module2_text, "Admin should see Challenge B in module2"
    assert 'Challenge C' in admin_module2_text, "Admin should see Challenge C in module2"
    
    # Admin should see the "hidden" indicator for Challenge B
    assert 'hidden' in admin_module2_text.lower(), "Admin should see hidden indicator for Challenge B"
    assert 'this challenge is accessible because you are this dojo\'s administrator' in admin_module2_text.lower(), \
        "Admin should see explanation that challenge is accessible due to admin privileges"
