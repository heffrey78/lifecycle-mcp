"""
Test configuration and fixtures for MCP Lifecycle Management Server
"""

import pytest
import tempfile
import os
import asyncio
from pathlib import Path
from unittest.mock import Mock
import logging

from lifecycle_mcp.database_manager import DatabaseManager
from lifecycle_mcp.handlers import (
    RequirementHandler,
    TaskHandler,
    ArchitectureHandler,
    InterviewHandler,
    ExportHandler,
    StatusHandler
)

# Configure pytest-asyncio to avoid deprecation warnings
pytest_plugins = ('pytest_asyncio',)

# Configure logging for tests
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def pytest_configure(config):
    """Configure pytest with asyncio settings"""
    # This addresses the deprecation warning about asyncio_default_fixture_loop_scope
    config.option.asyncio_default_fixture_loop_scope = "function"


@pytest.fixture(scope="function")
def event_loop():
    """Create an instance of the default event loop for each test function."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
        db_path = tmp_file.name
    
    # Create schema
    schema_path = Path(__file__).parent.parent / "src" / "lifecycle_mcp" / "lifecycle-schema.sql"
    if schema_path.exists():
        import sqlite3
        conn = sqlite3.connect(db_path)
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        conn.close()
    
    yield db_path
    
    # Clean up
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def db_manager(temp_db):
    """Create a DatabaseManager instance with temporary database"""
    return DatabaseManager(temp_db)


@pytest.fixture
def requirement_handler(db_manager):
    """Create a RequirementHandler instance"""
    return RequirementHandler(db_manager)


@pytest.fixture
def task_handler(db_manager):
    """Create a TaskHandler instance"""
    return TaskHandler(db_manager)


@pytest.fixture
def architecture_handler(db_manager):
    """Create an ArchitectureHandler instance"""
    return ArchitectureHandler(db_manager)


@pytest.fixture
def interview_handler(db_manager, requirement_handler):
    """Create an InterviewHandler instance"""
    return InterviewHandler(db_manager, requirement_handler)


@pytest.fixture
def export_handler(db_manager):
    """Create an ExportHandler instance"""
    return ExportHandler(db_manager)


@pytest.fixture
def status_handler(db_manager):
    """Create a StatusHandler instance"""
    return StatusHandler(db_manager)


@pytest.fixture
def sample_requirement_data():
    """Sample requirement data for testing"""
    return {
        "type": "FUNC",
        "title": "Test Requirement",
        "priority": "P1",
        "current_state": "Current test state",
        "desired_state": "Desired test state",
        "functional_requirements": ["Functional requirement 1", "Functional requirement 2"],
        "acceptance_criteria": ["Acceptance criteria 1", "Acceptance criteria 2"],
        "business_value": "Test business value",
        "risk_level": "Medium",
        "author": "Test Author"
    }


@pytest.fixture
def sample_task_data():
    """Sample task data for testing"""
    return {
        "requirement_ids": ["REQ-0001-FUNC-00"],
        "title": "Test Task",
        "priority": "P1",
        "effort": "M",
        "user_story": "As a user, I want to test this functionality",
        "acceptance_criteria": ["Task acceptance criteria 1", "Task acceptance criteria 2"],
        "assignee": "Test Assignee"
    }


@pytest.fixture
def sample_architecture_data():
    """Sample architecture decision data for testing"""
    return {
        "requirement_ids": ["REQ-0001-FUNC-00"],
        "title": "Test Architecture Decision",
        "context": "This is the context for the test decision",
        "decision": "This is the test decision",
        "decision_drivers": ["Driver 1", "Driver 2"],
        "considered_options": ["Option 1", "Option 2"],
        "consequences": {"positive": "Good outcome", "negative": "Some trade-offs"},
        "authors": ["Test Architect"]
    }


@pytest.fixture
def mock_text_content():
    """Mock TextContent for testing"""
    def _create_mock(text):
        mock = Mock()
        mock.type = "text"
        mock.text = text
        return mock
    return _create_mock