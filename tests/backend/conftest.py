import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_db_session():
    """Fixture to mock database session."""
    session = MagicMock()
    return session

@pytest.fixture
def mock_client():
    """Fixture to mock API client."""
    client = MagicMock()
    # Setup default behaviors if needed
    return client
