"""
Unit tests for TaskHandler
"""

import pytest


@pytest.mark.unit
class TestTaskHandler:
    """Test cases for TaskHandler"""

    def test_get_tool_definitions(self, task_handler):
        """Test that handler returns correct tool definitions"""
        tools = task_handler.get_tool_definitions()
        assert len(tools) == 6

        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "create_task",
            "update_task_status",
            "query_tasks",
            "get_task_details",
            "sync_task_from_github",
            "bulk_sync_github_tasks",
        ]
        assert all(tool in tool_names for tool in expected_tools)

    @pytest.mark.asyncio
    async def test_create_task_success(
        self, task_handler, requirement_handler, sample_requirement_data, sample_task_data
    ):
        """Test successful task creation"""
        # Create requirement and approve it first
        await requirement_handler._create_requirement(**sample_requirement_data)
        # Move through proper status transitions to Approved
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00", new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(requirement_id="REQ-0001-FUNC-00", new_status="Approved")

        # Create task
        result = await task_handler._create_task(**sample_task_data)

        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "TASK-0001-00-00" in result[0].text

        # Verify task was stored in database
        records = task_handler.db.get_records("tasks", "*", "id = ?", ["TASK-0001-00-00"])
        assert len(records) == 1
        assert records[0]["title"] == "Test Task"
        assert records[0]["priority"] == "P1"
        assert records[0]["effort"] == "M"

        # Verify task-requirement link was created
        links = task_handler.db.get_records("requirement_tasks", "*", "task_id = ?", ["TASK-0001-00-00"])
        assert len(links) == 1
        assert links[0]["requirement_id"] == "REQ-0001-FUNC-00"

    @pytest.mark.asyncio
    async def test_create_task_missing_params(self, task_handler):
        """Test task creation with missing required parameters"""
        incomplete_data = {
            "title": "Test Task"
            # Missing requirement_ids and priority
        }

        result = await task_handler._create_task(**incomplete_data)

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Missing required parameters" in result[0].text

    @pytest.mark.asyncio
    async def test_update_task_status_success(
        self, task_handler, requirement_handler, sample_requirement_data, sample_task_data
    ):
        """Test successful task status update"""
        # Create requirement and approve it first
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00", new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(requirement_id="REQ-0001-FUNC-00", new_status="Approved")
        # Now create task
        await task_handler._create_task(**sample_task_data)

        # Update task status
        result = await task_handler._update_task_status(
            task_id="TASK-0001-00-00", new_status="In Progress", comment="Starting work", assignee="New Assignee"
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "TASK-0001-00-00" in result[0].text

        # Verify status and assignee were updated
        records = task_handler.db.get_records("tasks", "status, assignee", "id = ?", ["TASK-0001-00-00"])
        assert records[0]["status"] == "In Progress"
        assert records[0]["assignee"] == "New Assignee"

    @pytest.mark.asyncio
    async def test_update_task_status_not_found(self, task_handler):
        """Test updating non-existent task"""
        result = await task_handler._update_task_status(task_id="TASK-9999-00-00", new_status="In Progress")

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Task not found" in result[0].text

    def test_query_tasks_no_results(self, task_handler):
        """Test querying tasks with no matches"""
        result = task_handler._query_tasks(status="Nonexistent")

        assert len(result) == 1
        assert "INFO" in result[0].text  # Check for above-fold format
        assert "No tasks found" in result[0].text
        assert "Try adjusting search criteria" in result[0].text

    def test_get_task_details_not_found(self, task_handler):
        """Test getting details for non-existent task"""
        result = task_handler._get_task_details(task_id="TASK-9999-00-00")

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Task not found" in result[0].text

    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(
        self, task_handler, requirement_handler, sample_requirement_data, sample_task_data
    ):
        """Test that handle_tool_call routes correctly"""
        # Create requirement and approve it
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00", new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(requirement_id="REQ-0001-FUNC-00", new_status="Approved")

        # Test create_task routing
        result = await task_handler.handle_tool_call("create_task", sample_task_data)
        assert len(result) == 1
        assert "SUCCESS" in result[0].text  # Check for above-fold format
        assert "TASK-0001-00-00" in result[0].text

        # Test unknown tool
        result = await task_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool: unknown_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_create_task_blocks_draft_requirement(
        self, task_handler, requirement_handler, sample_requirement_data, sample_task_data
    ):
        """Test that task creation is blocked for draft requirements"""
        # Create requirement in Draft status (default)
        await requirement_handler._create_requirement(**sample_requirement_data)

        # Attempt to create task for draft requirement
        result = await task_handler._create_task(**sample_task_data)

        assert len(result) == 1
        assert "ERROR" in result[0].text  # Check for above-fold format
        assert "Cannot create tasks for unapproved requirements" in result[0].text
        assert "REQ-0001-FUNC-00 (status: Draft)" in result[0].text
        assert "Approved, Architecture, Implemented, Ready, Validated" in result[0].text

        # Verify no task was created
        tasks = task_handler.db.get_records("tasks", "*", "", [])
        assert len(tasks) == 0
