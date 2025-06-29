"""
Unit tests for TaskHandler
"""

import pytest
import json

from src.lifecycle_mcp.handlers.task_handler import TaskHandler


class TestTaskHandler:
    """Test cases for TaskHandler"""
    
    def test_get_tool_definitions(self, task_handler):
        """Test that handler returns correct tool definitions"""
        tools = task_handler.get_tool_definitions()
        assert len(tools) == 4
        
        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "create_task",
            "update_task_status",
            "query_tasks", 
            "get_task_details"
        ]
        assert all(tool in tool_names for tool in expected_tools)
    
    async def test_create_task_success(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test successful task creation"""
        # Create requirement first
        await requirement_handler._create_requirement(**sample_requirement_data)
        
        # Create task
        result = await task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
        
        # Verify task was stored in database
        records = task_handler.db.get_records(
            "tasks", "*", "id = ?", ["TASK-0001-00-00"]
        )
        assert len(records) == 1
        assert records[0]['title'] == "Test Task"
        assert records[0]['priority'] == "P1"
        assert records[0]['effort'] == "M"
        
        # Verify task-requirement link was created
        links = task_handler.db.get_records(
            "requirement_tasks", "*", "task_id = ?", ["TASK-0001-00-00"]
        )
        assert len(links) == 1
        assert links[0]['requirement_id'] == "REQ-0001-FUNC-00"
    
    async def test_create_task_missing_params(self, task_handler):
        """Test task creation with missing required parameters"""
        incomplete_data = {
            "title": "Test Task"
            # Missing requirement_ids and priority
        }
        
        result = await task_handler._create_task(**incomplete_data)
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Missing required parameters" in result[0].text
    
    def test_create_subtask(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test creating a subtask"""
        # Create requirement and parent task first
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        # Create subtask
        subtask_data = sample_task_data.copy()
        subtask_data['title'] = "Test Subtask"
        subtask_data['parent_task_id'] = "TASK-0001-00-00"
        
        result = task_handler._create_task(**subtask_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-01-00: Test Subtask" in result[0].text
        
        # Verify subtask has correct parent
        records = task_handler.db.get_records(
            "tasks", "*", "id = ?", ["TASK-0001-01-00"]
        )
        assert len(records) == 1
        assert records[0]['parent_task_id'] == "TASK-0001-00-00"
        assert records[0]['task_number'] == 1
        assert records[0]['subtask_number'] == 1
    
    def test_update_task_status_success(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test successful task status update"""
        # Create requirement and task first
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        # Update task status
        result = task_handler._update_task_status(
            task_id="TASK-0001-00-00",
            new_status="In Progress",
            comment="Starting work",
            assignee="New Assignee"
        )
        
        assert len(result) == 1
        assert "Updated task TASK-0001-00-00 from Not Started to In Progress" in result[0].text
        
        # Verify status and assignee were updated
        records = task_handler.db.get_records(
            "tasks", "status, assignee", "id = ?", ["TASK-0001-00-00"]
        )
        assert records[0]['status'] == "In Progress"
        assert records[0]['assignee'] == "New Assignee"
    
    def test_update_task_status_not_found(self, task_handler):
        """Test updating non-existent task"""
        result = task_handler._update_task_status(
            task_id="TASK-9999-00-00",
            new_status="In Progress"
        )
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Task not found" in result[0].text
    
    def test_query_tasks_no_filters(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test querying tasks without filters"""
        # Create requirement and tasks
        requirement_handler._create_requirement(**sample_requirement_data)
        
        for i in range(3):
            data = sample_task_data.copy()
            data['title'] = f"Test Task {i+1}"
            task_handler._create_task(**data)
        
        result = task_handler._query_tasks()
        
        assert len(result) == 1
        assert "Found 3 tasks:" in result[0].text
        assert "TASK-0001-00-00" in result[0].text
        assert "TASK-0002-00-00" in result[0].text
        assert "TASK-0003-00-00" in result[0].text
    
    def test_query_tasks_by_status(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test querying tasks by status"""
        # Create requirement and tasks with different statuses
        requirement_handler._create_requirement(**sample_requirement_data)
        
        # Create first task and update its status
        task_handler._create_task(**sample_task_data)
        task_handler._update_task_status(task_id="TASK-0001-00-00", new_status="Complete")
        
        # Create second task (remains Not Started)
        data2 = sample_task_data.copy()
        data2['title'] = "Task 2"
        task_handler._create_task(**data2)
        
        # Query by status
        result = task_handler._query_tasks(status="Complete")
        assert len(result) == 1
        assert "Found 1 tasks:" in result[0].text
        assert "TASK-0001-00-00" in result[0].text
    
    def test_query_tasks_by_requirement_id(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test querying tasks by requirement ID"""
        # Create two requirements
        requirement_handler._create_requirement(**sample_requirement_data)
        
        req_data2 = sample_requirement_data.copy()
        req_data2['title'] = "Second Requirement"
        requirement_handler._create_requirement(**req_data2)
        
        # Create tasks linked to different requirements
        task_data1 = sample_task_data.copy()
        task_data1['requirement_ids'] = ["REQ-0001-FUNC-00"]
        task_handler._create_task(**task_data1)
        
        task_data2 = sample_task_data.copy()
        task_data2['requirement_ids'] = ["REQ-0002-FUNC-00"]
        task_data2['title'] = "Task for Req 2"
        task_handler._create_task(**task_data2)
        
        # Query by requirement ID
        result = task_handler._query_tasks(requirement_id="REQ-0001-FUNC-00")
        assert len(result) == 1
        assert "Found 1 tasks:" in result[0].text
        assert "TASK-0001-00-00" in result[0].text
    
    def test_query_tasks_no_results(self, task_handler):
        """Test querying tasks with no matches"""
        result = task_handler._query_tasks(status="Nonexistent")
        
        assert len(result) == 1
        assert "No tasks found matching criteria" in result[0].text
    
    def test_get_task_details_success(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test getting task details"""
        # Create requirement and task
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        result = task_handler._get_task_details(task_id="TASK-0001-00-00")
        
        assert len(result) == 1
        details = result[0].text
        assert "# Task Details: TASK-0001-00-00" in details
        assert "Test Task" in details
        assert "P1" in details
        assert "M" in details  # effort
        assert "Test Assignee" in details
        assert "As a user, I want to test this functionality" in details  # user story
    
    def test_get_task_details_with_subtasks(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test getting task details that include subtasks"""
        # Create requirement, parent task, and subtask
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        subtask_data = sample_task_data.copy()
        subtask_data['title'] = "Test Subtask"
        subtask_data['parent_task_id'] = "TASK-0001-00-00"
        task_handler._create_task(**subtask_data)
        
        # Get parent task details
        result = task_handler._get_task_details(task_id="TASK-0001-00-00")
        
        assert len(result) == 1
        details = result[0].text
        assert "## Subtasks (1)" in details
        assert "TASK-0001-01-00: Test Subtask" in details
    
    def test_get_task_details_with_parent(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test getting subtask details that include parent task"""
        # Create requirement, parent task, and subtask
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        subtask_data = sample_task_data.copy()
        subtask_data['title'] = "Test Subtask"
        subtask_data['parent_task_id'] = "TASK-0001-00-00"
        task_handler._create_task(**subtask_data)
        
        # Get subtask details
        result = task_handler._get_task_details(task_id="TASK-0001-01-00")
        
        assert len(result) == 1
        details = result[0].text
        assert "## Parent Task" in details
        assert "TASK-0001-00-00: Test Task" in details
    
    def test_get_task_details_not_found(self, task_handler):
        """Test getting details for non-existent task"""
        result = task_handler._get_task_details(task_id="TASK-9999-00-00")
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Task not found" in result[0].text
    
    def test_handle_tool_call_routing(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that handle_tool_call routes correctly"""
        # Create requirement first
        requirement_handler._create_requirement(**sample_requirement_data)
        
        # Test create_task routing
        result = task_handler.handle_tool_call("create_task", sample_task_data)
        assert len(result) == 1
        assert "Created task" in result[0].text
        
        # Test unknown tool
        result = task_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool: unknown_tool" in result[0].text
    
    def test_acceptance_criteria_json_handling(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that acceptance criteria are properly serialized and deserialized"""
        # Create requirement and task
        requirement_handler._create_requirement(**sample_requirement_data)
        task_handler._create_task(**sample_task_data)
        
        # Get details and verify acceptance criteria appear
        result = task_handler._get_task_details(task_id="TASK-0001-00-00")
        details = result[0].text
        
        assert "Task acceptance criteria 1" in details
        assert "Task acceptance criteria 2" in details
    
    def test_task_numbering_sequential(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task numbering is sequential"""
        # Create requirement
        requirement_handler._create_requirement(**sample_requirement_data)
        
        # Create multiple tasks
        for i in range(3):
            data = sample_task_data.copy()
            data['title'] = f"Task {i+1}"
            result = task_handler._create_task(**data)
            assert f"TASK-000{i+1}-00-00" in result[0].text
    
    @pytest.mark.asyncio
    async def test_create_task_blocks_draft_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation is blocked for draft requirements"""
        # Create requirement in Draft status (default)
        await requirement_handler._create_requirement(**sample_requirement_data)
        
        # Attempt to create task for draft requirement
        result = await task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Cannot create tasks for unapproved requirements" in result[0].text
        assert "REQ-0001-FUNC-00 (status: Draft)" in result[0].text
        assert "Approved, Architecture, Implemented, Ready, Validated" in result[0].text
        
        # Verify no task was created
        tasks = task_handler.db.get_records("tasks", "*", "", [])
        assert len(tasks) == 0
    
    async def test_create_task_blocks_under_review_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation is blocked for under review requirements"""
        # Create requirement and move to Under Review
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        
        # Attempt to create task
        result = await task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Cannot create tasks for unapproved requirements" in result[0].text
        assert "REQ-0001-FUNC-00 (status: Under Review)" in result[0].text
    
    async def test_create_task_allows_approved_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation succeeds for approved requirements"""
        # Create requirement and approve it
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        # Create task should succeed
        result = await task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
        
        # Verify task was created
        tasks = task_handler.db.get_records("tasks", "*", "id = ?", ["TASK-0001-00-00"])
        assert len(tasks) == 1
    
    async def test_create_task_allows_architecture_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation succeeds for requirements in Architecture status"""
        # Create requirement and move to Architecture
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Architecture"
        )
        
        # Create task should succeed
        result = await task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
    
    def test_create_task_allows_ready_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation succeeds for requirements in Ready status"""
        # Create requirement and move to Ready
        requirement_handler._create_requirement(**sample_requirement_data)
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Architecture"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Ready"
        )
        
        # Create task should succeed
        result = task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
    
    def test_create_task_allows_implemented_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation succeeds for requirements in Implemented status"""
        # Create requirement and move to Implemented
        requirement_handler._create_requirement(**sample_requirement_data)
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Architecture"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Ready"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Implemented"
        )
        
        # Create task should succeed
        result = task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
    
    def test_create_task_allows_validated_requirement(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test that task creation succeeds for requirements in Validated status"""
        # Create requirement and move to Validated
        requirement_handler._create_requirement(**sample_requirement_data)
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Architecture"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Ready"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Implemented"
        )
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Validated"
        )
        
        # Create task should succeed
        result = task_handler._create_task(**sample_task_data)
        
        assert len(result) == 1
        assert "Created task TASK-0001-00-00: Test Task" in result[0].text
    
    def test_create_task_mixed_requirement_statuses(self, task_handler, requirement_handler, sample_requirement_data, sample_task_data):
        """Test task creation with mixed requirement statuses"""
        # Create first requirement (approved)
        requirement_handler._create_requirement(**sample_requirement_data)
        requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        # Create second requirement (draft)
        req_data2 = sample_requirement_data.copy()
        req_data2['title'] = "Second Requirement"
        requirement_handler._create_requirement(**req_data2)
        
        # Attempt to create task linked to both requirements
        task_data = sample_task_data.copy()
        task_data['requirement_ids'] = ["REQ-0001-FUNC-00", "REQ-0002-FUNC-00"]
        
        result = task_handler._create_task(**task_data)
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Cannot create tasks for unapproved requirements" in result[0].text
        assert "REQ-0002-FUNC-00 (status: Draft)" in result[0].text
    
    async def test_create_task_nonexistent_requirement(self, task_handler, sample_task_data):
        """Test task creation with nonexistent requirement"""
        # Attempt to create task for nonexistent requirement
        task_data = sample_task_data.copy()
        task_data['requirement_ids'] = ["REQ-9999-FUNC-00"]
        
        result = await task_handler._create_task(**task_data)
        
        assert len(result) == 1
        assert "Error" in result[0].text
        assert "Requirement REQ-9999-FUNC-00 not found" in result[0].text