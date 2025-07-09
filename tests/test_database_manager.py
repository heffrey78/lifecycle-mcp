"""
Unit tests for DatabaseManager
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from lifecycle_mcp.database_manager import DatabaseManager


@pytest.mark.unit
class TestDatabaseManager:
    """Test cases for DatabaseManager"""

    def test_init_creates_database(self):
        """Test that DatabaseManager creates database if it doesn't exist"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=True) as tmp_file:
            db_path = tmp_file.name

        # Database file should not exist after deletion
        assert not Path(db_path).exists()

        # Creating DatabaseManager should create the database
        DatabaseManager(db_path)  # Creating DatabaseManager should create the database
        assert Path(db_path).exists()

        # Clean up
        os.unlink(db_path)

    def test_get_connection_context_manager(self, db_manager):
        """Test that get_connection works as context manager"""
        with db_manager.get_connection() as conn:
            assert isinstance(conn, sqlite3.Connection)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1

    def test_get_connection_with_row_factory(self, db_manager):
        """Test get_connection with row factory enabled"""
        with db_manager.get_connection(row_factory=True) as conn:
            assert conn.row_factory == sqlite3.Row

    def test_execute_query_insert(self, db_manager):
        """Test execute_query for INSERT operations"""
        # Insert a test record with all required fields
        result = db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )
        assert result is not None  # Should return row ID

    def test_execute_query_select(self, db_manager):
        """Test execute_query for SELECT operations"""
        # First insert a record with all required fields
        db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )

        # Then select it
        result = db_manager.execute_query(
            "SELECT id, title FROM requirements WHERE id = ?", ["REQ-0001-FUNC-00"], fetch_one=True
        )
        assert result is not None
        assert result[0] == "REQ-0001-FUNC-00"
        assert result[1] == "Test Requirement"

    def test_execute_query_select_all(self, db_manager):
        """Test execute_query with fetch_all"""
        # Insert multiple records with all required fields
        for i in range(3):
            db_manager.execute_query(
                "INSERT INTO requirements (id, requirement_number, type, title, priority, "
                "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    f"REQ-000{i + 1}-FUNC-00",
                    i + 1,
                    "FUNC",
                    f"Test Requirement {i + 1}",
                    "P1",
                    "Current",
                    "Desired",
                    "Test Author",
                ],
            )

        # Select all
        results = db_manager.execute_query("SELECT id FROM requirements WHERE type = ?", ["FUNC"], fetch_all=True)
        assert len(results) == 3

    def test_execute_many(self, db_manager):
        """Test execute_many for batch operations"""
        params_list = [
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement 1", "P1", "Current", "Desired", "Test Author"],
            ["REQ-0002-FUNC-00", 2, "FUNC", "Test Requirement 2", "P2", "Current", "Desired", "Test Author"],
            ["REQ-0003-FUNC-00", 3, "FUNC", "Test Requirement 3", "P3", "Current", "Desired", "Test Author"],
        ]

        db_manager.execute_many(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            params_list,
        )

        # Verify all records were inserted
        count = db_manager.execute_query("SELECT COUNT(*) FROM requirements", fetch_one=True)
        assert count[0] == 3

    def test_transaction_success(self, db_manager):
        """Test successful transaction"""
        with db_manager.transaction() as cursor:
            cursor.execute(
                "INSERT INTO requirements (id, requirement_number, type, title, priority, "
                "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
            )

        # Verify record was committed
        result = db_manager.execute_query(
            "SELECT id FROM requirements WHERE id = ?", ["REQ-0001-FUNC-00"], fetch_one=True
        )
        assert result is not None

    def test_transaction_rollback(self, db_manager):
        """Test transaction rollback on exception"""
        try:
            with db_manager.transaction() as cursor:
                cursor.execute(
                    "INSERT INTO requirements (id, requirement_number, type, title, priority, "
                    "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
                )
                # Force an error
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify record was not committed
        result = db_manager.execute_query(
            "SELECT id FROM requirements WHERE id = ?", ["REQ-0001-FUNC-00"], fetch_one=True
        )
        assert result is None

    def test_get_next_id(self, db_manager):
        """Test get_next_id functionality"""
        # First ID should be 1
        next_id = db_manager.get_next_id("requirements", "requirement_number")
        assert next_id == 1

        # Insert a record with all required fields
        db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )

        # Next ID should be 2
        next_id = db_manager.get_next_id("requirements", "requirement_number")
        assert next_id == 2

    def test_get_next_id_with_filter(self, db_manager):
        """Test get_next_id with WHERE clause"""
        # Insert records of different types with all required fields
        db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )
        db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-TECH-00", 1, "TECH", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )

        # Next FUNC ID should be 2
        next_id = db_manager.get_next_id("requirements", "requirement_number", "type = ?", ["FUNC"])
        assert next_id == 2

        # Next TECH ID should be 2
        next_id = db_manager.get_next_id("requirements", "requirement_number", "type = ?", ["TECH"])
        assert next_id == 2

    def test_check_exists(self, db_manager):
        """Test check_exists functionality"""
        # Should not exist initially
        exists = db_manager.check_exists("requirements", "id = ?", ["REQ-0001-FUNC-00"])
        assert not exists

        # Insert record with all required fields
        db_manager.execute_query(
            "INSERT INTO requirements (id, requirement_number, type, title, priority, "
            "current_state, desired_state, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ["REQ-0001-FUNC-00", 1, "FUNC", "Test Requirement", "P1", "Current", "Desired", "Test Author"],
        )

        # Should exist now
        exists = db_manager.check_exists("requirements", "id = ?", ["REQ-0001-FUNC-00"])
        assert exists

    def test_insert_record(self, db_manager):
        """Test insert_record helper method"""
        data = {
            "id": "REQ-0001-FUNC-00",
            "requirement_number": 1,
            "type": "FUNC",
            "title": "Test Requirement",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired",
            "author": "Test Author",
        }

        row_id = db_manager.insert_record("requirements", data)
        assert row_id is not None

        # Verify record was inserted
        result = db_manager.execute_query(
            "SELECT title FROM requirements WHERE id = ?", ["REQ-0001-FUNC-00"], fetch_one=True
        )
        assert result[0] == "Test Requirement"

    def test_update_record(self, db_manager):
        """Test update_record helper method"""
        # Insert initial record with all required fields
        db_manager.insert_record(
            "requirements",
            {
                "id": "REQ-0001-FUNC-00",
                "requirement_number": 1,
                "type": "FUNC",
                "title": "Test Requirement",
                "priority": "P1",
                "current_state": "Current",
                "desired_state": "Desired",
                "author": "Test Author",
            },
        )

        # Update record
        db_manager.update_record(
            "requirements", {"title": "Updated Title", "priority": "P2"}, "id = ?", ["REQ-0001-FUNC-00"]
        )

        # Verify update
        result = db_manager.execute_query(
            "SELECT title, priority FROM requirements WHERE id = ?", ["REQ-0001-FUNC-00"], fetch_one=True
        )
        assert result[0] == "Updated Title"
        assert result[1] == "P2"

    def test_get_records(self, db_manager):
        """Test get_records helper method"""
        # Insert test data with all required fields
        for i in range(3):
            db_manager.insert_record(
                "requirements",
                {
                    "id": f"REQ-000{i + 1}-FUNC-00",
                    "requirement_number": i + 1,
                    "type": "FUNC",
                    "title": f"Test Requirement {i + 1}",
                    "priority": f"P{i + 1}",
                    "current_state": "Current",
                    "desired_state": "Desired",
                    "author": "Test Author",
                },
            )

        # Get all records
        records = db_manager.get_records("requirements", "*", "type = ?", ["FUNC"], "priority")
        assert len(records) == 3
        assert records[0]["title"] == "Test Requirement 1"  # Should be sorted by priority

        # Get limited records
        records = db_manager.get_records("requirements", "id, title", "type = ?", ["FUNC"], "priority", limit=2)
        assert len(records) == 2
