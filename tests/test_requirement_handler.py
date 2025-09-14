"""
Unit tests for RequirementHandler
"""

import pytest


@pytest.mark.unit
class TestRequirementHandler:
    """Test cases for RequirementHandler"""

    def test_get_tool_definitions(self, requirement_handler):
        """Test that handler returns correct tool definitions"""
        tools = requirement_handler.get_tool_definitions()
        assert len(tools) == 6

        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "create_requirement",
            "update_requirement_status",
            "query_requirements",
            "query_requirements_json",
            "get_requirement_details",
            "trace_requirement",
        ]
        assert all(tool in tool_names for tool in expected_tools)

    @pytest.mark.asyncio
    async def test_create_requirement_success(self, requirement_handler, sample_requirement_data):
        """Test successful requirement creation"""
        result = await requirement_handler._create_requirement(**sample_requirement_data)

        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format

        # Verify requirement was stored in database
        records = requirement_handler.db.get_records("requirements", "*", "id = ?", ["REQ-0001-FUNC-00"])
        assert len(records) == 1
        assert records[0]["title"] == "Test Requirement"
        assert records[0]["type"] == "FUNC"
        assert records[0]["priority"] == "P1"

    @pytest.mark.asyncio
    async def test_create_requirement_missing_params(self, requirement_handler):
        """Test requirement creation with missing required parameters"""
        incomplete_data = {
            "type": "FUNC",
            "title": "Test Requirement",
            # Missing priority, current_state, desired_state
        }

        result = await requirement_handler._create_requirement(**incomplete_data)

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Missing required parameters" in result[0].text

    @pytest.mark.asyncio
    async def test_update_requirement_status_valid_transition(self, requirement_handler, sample_requirement_data):
        """Test valid status transition"""
        # Create requirement first
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Update status from Draft to Under Review (valid transition)
        result = await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00", new_status="Under Review", comment="Moving to review"
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format

        # Verify status was updated
        records = requirement_handler.db.get_records("requirements", "status", "id = ?", ["REQ-0001-FUNC-00"])
        assert records[0]["status"] == "Under Review"

    @pytest.mark.asyncio
    async def test_update_requirement_status_invalid_transition(self, requirement_handler, sample_requirement_data):
        """Test invalid status transition"""
        # Create requirement first
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Try invalid transition from Draft to Validated
        result = await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00", new_status="Validated"
        )

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Invalid transition from Draft to Validated" in result[0].text

    @pytest.mark.asyncio
    async def test_update_requirement_status_not_found(self, requirement_handler):
        """Test updating non-existent requirement"""
        result = await requirement_handler._update_requirement_status(
            requirement_id="REQ-9999-FUNC-00", new_status="Under Review"
        )

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Requirement not found" in result[0].text

    @pytest.mark.asyncio
    async def test_query_requirements_no_filters(self, requirement_handler, sample_requirement_data):
        """Test querying requirements without filters"""
        # Create test requirements
        for i in range(3):
            data = sample_requirement_data.copy()
            data["title"] = f"Test Requirement {i + 1}"
            await requirement_handler._create_requirement(**data)

        result = requirement_handler._query_requirements()

        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "3 requirement" in result[0].text
        assert "REQ-0001-FUNC-00" in result[0].text
        assert "REQ-0002-FUNC-00" in result[0].text
        assert "REQ-0003-FUNC-00" in result[0].text

    @pytest.mark.asyncio
    async def test_query_requirements_with_filters(self, requirement_handler, sample_requirement_data):
        """Test querying requirements with filters"""
        # Create requirements with different statuses and priorities
        data1 = sample_requirement_data.copy()
        data1["title"] = "High Priority Requirement"
        data1["priority"] = "P0"
        await requirement_handler._create_requirement(**data1)

        data2 = sample_requirement_data.copy()
        data2["title"] = "Low Priority Requirement"
        data2["priority"] = "P3"
        await requirement_handler._create_requirement(**data2)

        # Query by priority
        result = requirement_handler._query_requirements(priority="P0")
        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "1 requirement" in result[0].text
        assert "High Priority Requirement" in result[0].text

        # Query by status
        result = requirement_handler._query_requirements(status="Draft")
        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "2 requirement" in result[0].text

    @pytest.mark.asyncio
    async def test_query_requirements_with_search_text(self, requirement_handler, sample_requirement_data):
        """Test querying requirements with search text"""
        # Create requirements with different titles
        data1 = sample_requirement_data.copy()
        data1["title"] = "User Authentication System"
        await requirement_handler._create_requirement(**data1)

        data2 = sample_requirement_data.copy()
        data2["title"] = "Payment Processing Module"
        await requirement_handler._create_requirement(**data2)

        # Search by title
        result = requirement_handler._query_requirements(search_text="Authentication")
        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "1 requirement" in result[0].text
        assert "User Authentication System" in result[0].text

    def test_query_requirements_no_results(self, requirement_handler):
        """Test querying requirements with no matches"""
        result = requirement_handler._query_requirements(status="Nonexistent")

        assert len(result) == 1
        assert "INFO" in result[0].text  # Check for above-fold format
        assert "No requirements found" in result[0].text

    @pytest.mark.asyncio
    async def test_get_requirement_details_success(self, requirement_handler, sample_requirement_data):
        """Test getting requirement details"""
        # Create requirement
        await requirement_handler._create_requirement(**sample_requirement_data)

        result = requirement_handler._get_requirement_details(requirement_id="REQ-0001-FUNC-00")

        assert len(result) == 1
        assert "INFO" in result[0].text  # Check for above-fold format
        details = result[0].text
        assert "REQ-0001-FUNC-00" in details
        assert "Test Requirement" in details
        assert "FUNC" in details
        assert "P1" in details
        assert "Current test state" in details
        assert "Desired test state" in details
        assert "Test business value" in details

    def test_get_requirement_details_not_found(self, requirement_handler):
        """Test getting details for non-existent requirement"""
        result = requirement_handler._get_requirement_details(requirement_id="REQ-9999-FUNC-00")

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Requirement not found" in result[0].text

    @pytest.mark.asyncio
    async def test_trace_requirement_success(self, requirement_handler, sample_requirement_data):
        """Test requirement tracing"""
        # Create requirement
        await requirement_handler._create_requirement(**sample_requirement_data)

        result = requirement_handler._trace_requirement(requirement_id="REQ-0001-FUNC-00")

        assert len(result) == 1
        assert "INFO" in result[0].text  # Check for above-fold format
        trace = result[0].text
        assert "REQ-0001-FUNC-00" in trace
        assert "Test Requirement" in trace
        assert "Implementation Tasks (0)" in trace  # No tasks linked yet

    def test_trace_requirement_not_found(self, requirement_handler):
        """Test tracing non-existent requirement"""
        result = requirement_handler._trace_requirement(requirement_id="REQ-9999-FUNC-00")

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Requirement not found" in result[0].text

    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(self, requirement_handler, sample_requirement_data):
        """Test that handle_tool_call routes correctly"""
        # Test create_requirement routing
        result = await requirement_handler.handle_tool_call("create_requirement", sample_requirement_data)
        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format

        # Test unknown tool
        result = await requirement_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Unknown tool: unknown_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_functional_requirements_json_handling(self, requirement_handler, sample_requirement_data):
        """Test that functional requirements are properly serialized and deserialized"""
        # Create requirement with functional requirements
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Get details and verify functional requirements appear
        result = requirement_handler._get_requirement_details(requirement_id="REQ-0001-FUNC-00")
        details = result[0].text

        assert "Functional Requirements" in details
        assert "Functional requirement 1" in details
        assert "Functional requirement 2" in details

    @pytest.mark.asyncio
    async def test_acceptance_criteria_json_handling(self, requirement_handler, sample_requirement_data):
        """Test that acceptance criteria are properly serialized and deserialized"""
        # Create requirement with acceptance criteria
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Get details and verify acceptance criteria appear
        result = requirement_handler._get_requirement_details(requirement_id="REQ-0001-FUNC-00")
        details = result[0].text

        assert "Acceptance Criteria" in details
        assert "Acceptance criteria 1" in details
        assert "Acceptance criteria 2" in details

    @pytest.mark.asyncio
    async def test_requirement_numbering_by_type(self, requirement_handler):
        """Test that requirement numbering is correctly handled by type"""
        # Create FUNC requirement
        func_data = {
            "type": "FUNC",
            "title": "Functional Requirement",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired",
            "author": "Test Author",
        }
        result1 = await requirement_handler._create_requirement(**func_data)
        assert "REQ-0001-FUNC-00" in result1[0].text

        # Create TECH requirement
        tech_data = {
            "type": "TECH",
            "title": "Technical Requirement",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired",
            "author": "Test Author",
        }
        result2 = await requirement_handler._create_requirement(**tech_data)
        assert "REQ-0001-TECH-00" in result2[0].text

        # Create another FUNC requirement
        func_data2 = {
            "type": "FUNC",
            "title": "Another Functional Requirement",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired",
            "author": "Test Author",
        }
        result3 = await requirement_handler._create_requirement(**func_data2)
        assert "REQ-0002-FUNC-00" in result3[0].text
