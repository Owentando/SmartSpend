def test_name_too_short_rejected(client):
    """Single-char name is rejected"""
    response = client.post("/register", data={
        "name": "A",
        "surname": "User",
        "email": "valid@dut.ac.za",
        "password": "Password123",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"2 and 50" in response.data


def test_name_with_numbers_rejected(client):
    """Name with digits is rejected"""
    response = client.post("/register", data={
        "name": "John123",
        "surname": "User",
        "email": "valid@dut.ac.za",
        "password": "Password123",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"letters" in response.data


def test_password_without_number_rejected(client):
    """Password with no digits is rejected"""
    response = client.post("/register", data={
        "name": "John",
        "surname": "User",
        "email": "valid@dut.ac.za",
        "password": "onlyletters",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"number" in response.data


def test_password_without_letter_rejected(client):
    """Password with only digits is rejected"""
    response = client.post("/register", data={
        "name": "John",
        "surname": "User",
        "email": "valid@dut.ac.za",
        "password": "12345678",
        "role": "student",
        "budget": "1000"
    }, follow_redirects=True)
    assert b"letter" in response.data