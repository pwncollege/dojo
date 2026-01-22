from utils import DOJO_URL

def test_github_edit_links_welcome_dojo(admin_session, welcome_dojo):
    """Test that GitHub edit links appear correctly for the welcome dojo"""

    response = admin_session.get(f"{DOJO_URL}/{welcome_dojo}")
    assert response.status_code == 200, f"Failed to load welcome dojo page: {response.status_code}"
    
    assert "github.com/pwncollege/welcome-dojo/edit/main/" in response.text, \
        "Dojo page should have edit link"
    assert "fa-edit" in response.text, "Edit links should include Font Awesome edit icon"
    assert "github-edit-link" in response.text, "Edit links should have the github-edit-link CSS class"

    response = admin_session.get(f"{DOJO_URL}/{welcome_dojo}/welcome")
    assert response.status_code == 200, f"Failed to load welcome module page: {response.status_code}"
    
    assert "github.com/pwncollege/welcome-dojo/edit/main/" in response.text, \
        "Module page should have edit link"
