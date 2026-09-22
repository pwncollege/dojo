import uuid

import pytest
import requests
import yaml

from utils import DOJO_URL, create_dojo_yml, solve_challenge_offline, TEST_DOJOS_LOCATION


@pytest.fixture(scope="session")
def module_resources_dojo(admin_session, example_dojo):
    return create_dojo_yml(open(TEST_DOJOS_LOCATION / "module_resources_dojo.yml").read(), session=admin_session)


def test_module_resources(module_resources_dojo, admin_session, example_dojo):
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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


def test_lecture_slides_link_is_safe(admin_session):
    dojo_id = create_dojo_yml("""id: lecture-slides-xss
modules:
  - id: test
    resources:
      - name: Slides
        type: lecture
        slides: "x');alert('slides-xss');//"
""", session=admin_session)
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
    assert response.status_code == 200
    assert 'onclick="window.open(' not in response.text
    assert 'href="https://docs.google.com/presentation/d/x&#39;);alert(&#39;slides-xss&#39;);//"' in response.text


def test_module_resources_order(module_resources_dojo, admin_session, example_dojo):
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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


def test_optional_challenge_styling(module_resources_dojo, admin_session):
    response = admin_session.get(f"{DOJO_URL}/{module_resources_dojo}/test/")
    assert response.status_code == 200

    challenge_header = response.text.split('data-challenge-id="testb"', 1)[1].split("</h4>", 1)[0]
    assert 'class="accordion-item optional-challenge"' in response.text
    assert '<span class="optional-challenge-label">Optional</span>' in challenge_header


def test_unified_ordering(module_resources_dojo, admin_session, example_dojo):
    """Test that resources and challenges appear in YAML order"""
    dojo_id = module_resources_dojo
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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
    
    response = admin_session.get(f"{DOJO_URL}/{dojo_id}/test/")
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


def test_module_import_refreshes_lessons_without_losing_progress(admin_session, random_user):
    name, session = random_user
    source_spec = {
        "id": f"lesson-source-{uuid.uuid4().hex[:8]}",
        "type": "public",
        "image": "pwncollege/challenge-simple",
        "modules": [{"id": "lesson", "name": "Original lesson", "resources": [
            {"type": "header", "content": "Getting started"},
            {"type": "markdown", "name": "Reading", "content": "First revision", "expandable": False},
            {"type": "challenge", "id": "first", "name": "First exercise", "description": "Apply the reading"},
            {"type": "lecture", "name": "Lecture", "video": "lesson-video", "slides": "lesson-slides"},
            {"type": "challenge", "id": "second", "name": "Second exercise", "required": False},
        ]}],
    }
    source = create_dojo_yml(yaml.safe_dump(source_spec), session=admin_session)
    import_spec = {
        "id": f"lesson-import-{uuid.uuid4().hex[:8]}",
        "type": "public",
        "modules": [{"id": "renamed", "name": "Our lesson", "import": {"dojo": source, "module": "lesson"}}],
    }
    imported = create_dojo_yml(yaml.safe_dump(import_spec), session=admin_session)

    def modules(dojo):
        response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
        assert response.status_code == 200, response.text
        return response.json()["modules"]

    def items(dojo):
        return [(item["item_type"], item["name"], item.get("content"), item.get("description"),
                 item.get("video"), item.get("slides"), item.get("expandable"), item.get("required"))
                for item in modules(dojo)[0]["unified_items"]]

    original_items = items(source)
    assert items(imported) == original_items
    assert (modules(imported)[0]["id"], modules(imported)[0]["name"]) == ("renamed", "Our lesson")
    solve_challenge_offline(source, "lesson", "first", session=session, user=name)
    solves_url = f"{DOJO_URL}/pwncollege_api/v1/dojos/{imported}/solves"
    original_solves = session.get(solves_url).json()["solves"]
    assert [(solve["module_id"], solve["challenge_id"]) for solve in original_solves] == [("renamed", "first")]

    source_spec["modules"][0]["resources"][1]["content"] = "Revised reading"
    source_spec["modules"][0]["resources"].reverse()
    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{source}/update", json=source_spec)
    assert response.status_code == 200 and response.json()["success"], response.text
    assert items(imported) == original_items

    response = admin_session.post(f"{DOJO_URL}/pwncollege_api/v1/dojos/{imported}/update", json=import_spec)
    assert response.status_code == 200 and response.json()["success"], response.text
    assert items(imported) == items(source)
    assert items(imported) != original_items
    assert session.get(solves_url).json()["solves"] == original_solves


def test_modules_can_provide_reading_without_challenges(admin_session, random_user):
    _, session = random_user
    spec = {
        "id": f"reading-{uuid.uuid4().hex[:8]}",
        "type": "public",
        "modules": [{"id": "reading", "resources": [
            {"type": "header", "content": "Background material"},
            {"type": "markdown", "name": "Explanation", "content": "Reading without an exercise"},
            {"type": "lecture", "name": "Discussion", "video": "reading-video"},
        ]}],
    }
    dojo = create_dojo_yml(yaml.safe_dump(spec), session=admin_session)
    response = session.get(f"{DOJO_URL}/pwncollege_api/v1/dojos/{dojo}/modules")
    assert response.status_code == 200
    module, = response.json()["modules"]
    assert module["id"] == "reading" and module["challenges"] == []
    assert [item["type"] for item in module["unified_items"]] == ["header", "markdown", "lecture"]
    page = session.get(f"{DOJO_URL}/{dojo}/reading/")
    assert page.status_code == 200
    assert "Reading without an exercise" in page.text
    assert "reading-video" in page.text
