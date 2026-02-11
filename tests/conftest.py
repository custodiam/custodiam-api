# tests/conftest.py
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Cliente de test para la API."""
    return TestClient(app)
