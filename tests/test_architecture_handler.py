"""
Unit tests for ArchitectureHandler
"""

import pytest


@pytest.mark.unit
class TestArchitectureHandler:
    """Test cases for ArchitectureHandler"""

    def test_get_tool_definitions(self, architecture_handler):
        """Test that handler returns correct tool definitions"""
        tools = architecture_handler.get_tool_definitions()
        assert len(tools) == 5

        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "create_architecture_decision",
            "update_architecture_status",
            "query_architecture_decisions",
            "get_architecture_details",
            "add_architecture_review",
        ]
        assert all(tool in tool_names for tool in expected_tools)

    @pytest.mark.asyncio
    async def test_create_architecture_decision_success(
        self, architecture_handler, requirement_handler, sample_requirement_data, sample_architecture_data
    ):
        """Test successful architecture decision creation"""
        # Create requirement first
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Create architecture decision
        result = await architecture_handler._create_architecture_decision(**sample_architecture_data)

        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "ADR-0001" in result[0].text

        # Verify ADR was stored in database
        records = architecture_handler.db.get_records("architecture", "*", "id = ?", ["ADR-0001"])
        assert len(records) == 1
        assert records[0]["title"] == "Test Architecture Decision"
        assert records[0]["context"] == "This is the context for the test decision"
        assert records[0]["decision_outcome"] == "This is the test decision"

    @pytest.mark.asyncio
    async def test_create_architecture_decision_missing_params(self, architecture_handler):
        """Test architecture decision creation with missing required parameters"""
        incomplete_data = {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Test Decision",
            # Missing context and decision
        }

        result = await architecture_handler._create_architecture_decision(**incomplete_data)

        assert len(result) == 1
        assert "ERROR" in result[0].text
        assert "Missing required parameters" in result[0].text

    @pytest.mark.asyncio
    async def test_create_architecture_decision_without_requirements(
        self, architecture_handler, sample_architecture_data
    ):
        """Test creating ADR without requirements - should succeed but not link"""
        result = await architecture_handler._create_architecture_decision(**sample_architecture_data)

        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "ADR-0001" in result[0].text

        # Note: In the current implementation, ADRs can be created without validating
        # requirement existence. Links are created but may be dangling.

    def test_query_architecture_decisions_no_results(self, architecture_handler):
        """Test querying architecture decisions with no matches"""
        result = architecture_handler._query_architecture_decisions(status="Nonexistent")

        assert len(result) == 1
        assert "INFO" in result[0].text
        assert "No architecture decisions found" in result[0].text

    def test_get_architecture_details_not_found(self, architecture_handler):
        """Test getting details for non-existent ADR"""
        result = architecture_handler._get_architecture_details(architecture_id="ADR-9999")

        assert len(result) == 1
        assert "ERROR" in result[0].text
        assert "Architecture decision not found" in result[0].text

    def test_add_architecture_review_not_found(self, architecture_handler):
        """Test adding review to non-existent ADR"""
        result = architecture_handler._add_architecture_review(architecture_id="ADR-9999", comment="Test review")

        assert len(result) == 1
        assert "ERROR" in result[0].text
        assert "Architecture decision not found" in result[0].text

    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(
        self, architecture_handler, requirement_handler, sample_requirement_data, sample_architecture_data
    ):
        """Test that handle_tool_call routes correctly"""
        # Create requirement first
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Test create_architecture_decision routing
        result = await architecture_handler.handle_tool_call("create_architecture_decision", sample_architecture_data)
        assert len(result) == 1
        assert "SUCCESS" in result[0].text

        # Test unknown tool
        result = await architecture_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool: unknown_tool" in result[0].text
