def test_home_page_loads(client):
    """Home page returns 200"""
    response = client.get("/")
    assert response.status_code == 200


def test_login_page_loads(client):
    """Login page loads"""
    response = client.get("/login")
    assert response.status_code == 200


def test_register_page_loads(client):
    """Register page loads"""
    response = client.get("/register")
    assert response.status_code == 200


def test_dashboard_redirects_when_not_logged_in(client):
    """Dashboard requires login"""
    response = client.get("/dashboard")
    assert response.status_code == 302


def test_budget_list_redirects_when_not_logged_in(client):
    """Budget List requires login"""
    response = client.get("/budget-list")
    assert response.status_code == 302


def test_404_page(client):
    """Unknown URL returns 404"""
    response = client.get("/this-does-not-exist")
    assert response.status_code == 404


def test_admin_dashboard_blocked_for_non_admins(client):
    """Non-admins can't access admin dashboard"""
    response = client.get("/admin/dashboard")
    assert response.status_code == 302