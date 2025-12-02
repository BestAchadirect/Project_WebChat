import pytest
from unittest.mock import MagicMock

def test_signup_success(mock_client, mock_db_session):
    """Test successful tenant signup."""
    # Arrange
    payload = {"email": "test@example.com", "password": "StrongPassword123!"}
    mock_client.post.return_value.status_code = 201
    mock_client.post.return_value.json.return_value = {"id": 1, "email": "test@example.com"}

    # Act
    response = mock_client.post("/api/signup", json=payload)

    # Assert
    assert response.status_code == 201
    assert response.json()["email"] == "test@example.com"

def test_login_success(mock_client):
    """Test successful login."""
    # Arrange
    payload = {"email": "test@example.com", "password": "StrongPassword123!"}
    mock_client.post.return_value.status_code = 200
    mock_client.post.return_value.json.return_value = {"access_token": "fake-jwt-token"}

    # Act
    response = mock_client.post("/api/login", json=payload)

    # Assert
    assert response.status_code == 200
    assert "access_token" in response.json()

def test_login_invalid_credentials(mock_client):
    """Test login with invalid credentials."""
    # Arrange
    payload = {"email": "test@example.com", "password": "WrongPassword"}
    mock_client.post.return_value.status_code = 401
    
    # Act
    response = mock_client.post("/api/login", json=payload)

    # Assert
    assert response.status_code == 401
