def test_csrf_token_in_login_page(client):
    """Login page contains CSRF token"""
    response = client.get("/login")
    assert b"_csrf_token" in response.data


def test_csrf_token_in_register_page(client):
    """Register page contains CSRF token"""
    response = client.get("/register")
    assert b"_csrf_token" in response.data


def test_security_headers_present(client):
    """Response includes security headers"""
    response = client.get("/")
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in response.headers


def test_rate_limiting_after_multiple_failures(client):
    """Rate limiting kicks in after 5 failures"""
    for i in range(6):
        response = client.post("/login", data={
            "email": "test@test.com",
            "password": "wrong"
        }, follow_redirects=True)

    assert b"Too many" in response.data or b"wait" in response.data.lower()