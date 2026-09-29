def test_register_with_invalid_email_fails(client):
    """Invalid email is rejected"""
    response = client.post("/register", data={
        "name": "Test",
        "surname": "User",
        "email": "not-an-email",
        "password": "Password123",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"valid email" in response.data or b"email address" in response.data


def test_register_with_short_password_fails(client):
    """Password under 8 chars is rejected"""
    response = client.post("/register", data={
        "name": "Test",
        "surname": "User",
        "email": "test@dut.ac.za",
        "password": "abc",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"8 characters" in response.data


def test_register_with_negative_budget_fails(client):
    """Negative budget is rejected"""
    response = client.post("/register", data={
        "name": "Test",
        "surname": "User",
        "email": "test@dut.ac.za",
        "password": "Password123",
        "role": "student",
        "budget": "-500"
    }, follow_redirects=True)
    assert b"negative" in response.data.lower()


def test_login_with_wrong_password_fails(client):
    """Wrong password shows error"""
    response = client.post("/login", data={
        "email": "wrong@test.com",
        "password": "wrongpass"
    }, follow_redirects=True)
    assert b"Incorrect email" in response.data or b"password" in response.data.lower()


def test_logout_clears_session(client):
    """Logout redirects to home"""
    response = client.get("/logout")
    assert response.status_code == 302