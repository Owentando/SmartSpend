import os
import sys
import pytest

# Make sure Python can find "app.py" from the tests folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app as flask_app


@pytest.fixture
def app():
    """Provide the Flask app configured for testing."""
    flask_app.config.update({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "CSRF_DISABLED": True,          # ⭐ Skip CSRF in tests
        "SECRET_KEY": "test-secret-key",
    })
    yield flask_app


@pytest.fixture
def client(app):
    """Provide a test client for making requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Provide a CLI runner for testing."""
    return app.test_cli_runner()