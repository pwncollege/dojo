import pytest
import requests

from utils import DOJO_HOST, create_dojo_yml, TEST_DOJOS_LOCATION


@pytest.fixture(scope="session")
def module_resources_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "module_resources_dojo.yml").read(), session=admin_session)


def test_module_resources(module_resources_dojo, admin_session, example_dojo):
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    assert "Resource A" in page_content
    assert "Resource B" in page_content
    assert "Resource C" in page_content
    assert "Resource D" in page_content
    assert "Resource E" in page_content
    
    assert "hh4XAU6XYP0" in page_content
    assert "14ZJRIyf0HnoYO1N8GI5ygE-ZVgdhjJrvzkETFLz7NIo" in page_content
    assert "TESTB123" in page_content
    assert "hIK1Dfjxq4E" in page_content
    assert "1NjoOj03eQsjnZWhm-A3IsxTVqeWUqFvR4wgfXnhsnu4" in page_content
    assert "PLHhKcdBlprMfIBVorNvOfY5UiHJmOk9nh" in page_content
    assert "TESTD456" in page_content
    assert "1H1V1HkVt3k" in page_content
    assert "1_xdrCm136NzcDl9bqSgAEQuigUHkNjkKmamhaej296Q" in page_content


def test_module_resources_order(module_resources_dojo, admin_session, example_dojo):
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    pos_a = page_content.find("Resource A")
    pos_b = page_content.find("Resource B")
    pos_c = page_content.find("Resource C")
    pos_d = page_content.find("Resource D")
    pos_e = page_content.find("Resource E")
    
    assert pos_a != -1 and pos_b != -1 and pos_c != -1 and pos_d != -1 and pos_e != -1
    assert pos_a < pos_b < pos_c < pos_d < pos_e


def test_module_resources_with_challenges(module_resources_dojo, admin_session, example_dojo):
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    assert "Challenge A" in page_content
    assert "Challenge B" in page_content
    
    pos_resource_c = page_content.find("Resource C")
    pos_challenge_a = page_content.find("Challenge A")
    pos_resource_d = page_content.find("Resource D")
    pos_challenge_b = page_content.find("Challenge B")
    
    assert pos_resource_c != -1 and pos_challenge_a != -1 and pos_resource_d != -1 and pos_challenge_b != -1
    
    assert pos_resource_c < pos_challenge_a < pos_resource_d, f"Challenge A should be between Resource C ({pos_resource_c}) and Resource D ({pos_resource_d}), but found at {pos_challenge_a}"
    
    pos_resource_e = page_content.find("Resource E")
    assert pos_resource_e < pos_challenge_b, f"Challenge B ({pos_challenge_b}) should come after Resource E ({pos_resource_e})"


def test_unified_ordering(module_resources_dojo, admin_session, example_dojo):
    """Test that resources and challenges appear in YAML order"""
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    items = [
        "DESC789",  # First description
        "Resource A",
        "Resource B",
        "DESC_MIDDLE",  # Second description
        "Advanced Section",
        "Resource C",
        "Challenge A",
        "Resource D",
        "DESC_BOTTOM",  # Third description
        "Resource E",
        "Challenge B"
    ]
    
    positions = [page_content.find(item) for item in items]
    
    for i, pos in enumerate(positions):
        assert pos != -1, f"{items[i]} not found in page"
    
    for i in range(len(positions) - 1):
        assert positions[i] < positions[i+1], f"{items[i]} (at {positions[i]}) should appear before {items[i+1]} (at {positions[i+1]})"


def test_header_resources(module_resources_dojo, admin_session, example_dojo):
    """Test that header resources render correctly"""
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    assert "<br>" in page_content
    assert "<h2>Advanced Section</h2>" in page_content
    
    pos_b = page_content.find("Resource B")
    pos_header = page_content.find("<h2>Advanced Section</h2>")
    pos_c = page_content.find("Resource C")
    
    assert pos_b < pos_header < pos_c, f"Header should be between Resource B and C"


def test_non_expandable_markdown_resources(module_resources_dojo, admin_session, example_dojo):
    """Test that markdown resources with expandable=false render inline at their specified positions"""
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    # Check all non-expandable markdown resources exist
    assert "DESC789" in page_content
    assert "First description resource at the top" in page_content
    assert "DESC_MIDDLE" in page_content
    assert "Second description resource in the middle" in page_content
    assert "DESC_BOTTOM" in page_content
    assert "Third description resource after challenges" in page_content
    
    # Check ordering - non-expandable markdown resources should appear in their specified positions
    pos_first_desc = page_content.find("DESC789")
    pos_resource_a = page_content.find("Resource A")
    pos_resource_b = page_content.find("Resource B")
    pos_middle_desc = page_content.find("DESC_MIDDLE")
    pos_advanced = page_content.find("Advanced Section")
    pos_resource_d = page_content.find("Resource D")
    pos_bottom_desc = page_content.find("DESC_BOTTOM")
    pos_resource_e = page_content.find("Resource E")
    
    # First description should be before Resource A
    assert pos_first_desc < pos_resource_a, "First description should appear before Resource A"
    
    # Middle description should be between Resource B and Advanced Section
    assert pos_resource_b < pos_middle_desc < pos_advanced, "Middle description should be between Resource B and Advanced Section"
    
    # Bottom description should be between Resource D and Resource E
    assert pos_resource_d < pos_bottom_desc < pos_resource_e, "Bottom description should be between Resource D and Resource E"


def test_markdown_file_loading(module_resources_dojo, admin_session, example_dojo):
    """Test that markdown resources can load content from files"""
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"http://{DOJO_HOST}/{dojo_id}/test/")
    assert response.status_code == 200
    page_content = response.text
    
    # Check that file-loaded content appears
    assert "FILE_CONTENT_123" in page_content
    assert "Test Content from File" in page_content
    assert "Feature 1" in page_content
    assert "Feature 2" in page_content
    assert "Feature 3" in page_content
    
    # Check that it appears after Resource E (it's expandable by default)
    assert "Resource from File" in page_content
    pos_resource_e = page_content.find("Resource E")
    pos_file_resource = page_content.find("Resource from File")
    assert pos_resource_e < pos_file_resource, "File-loaded resource should appear after Resource E"
