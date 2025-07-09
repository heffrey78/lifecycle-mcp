"""
Refactored unit tests for TaskHandler using parametrization
This demonstrates how to reduce the 665 lines to ~300 with better organization
"""


import pytest


@pytest.mark.unit
class TestTaskHandlerRefactored:
    """Refactored test cases for TaskHandler using parametrization"""
    
    @pytest.fixture
    async def approved_requirement(self, requirement_handler, sample_requirement_data):
        """Create and approve a requirement for task creation"""
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        return "REQ-0001-FUNC-00"
    
    @pytest.fixture
    async def multiple_approved_requirements(self, requirement_handler, sample_requirement_data):
        """Create multiple approved requirements"""
        req_ids = []
        for i in range(3):
            data = sample_requirement_data.copy()
            data['title'] = f"Requirement {i+1}"
            await requirement_handler._create_requirement(**data)
            
            req_id = f"REQ-000{i+1}-FUNC-00"
            await requirement_handler._update_requirement_status(
                requirement_id=req_id,
                new_status="Under Review"
            )
            await requirement_handler._update_requirement_status(
                requirement_id=req_id,
                new_status="Approved"
            )
            req_ids.append(req_id)
        return req_ids
    
    def test_get_tool_definitions(self, task_handler):
        """Test that handler returns correct tool definitions"""
        tools = task_handler.get_tool_definitions()
        assert len(tools) == 6
        
        expected_tools = [
            "create_task", "update_task_status", "query_tasks",
            "get_task_details", "sync_task_from_github", "bulk_sync_github_tasks"
        ]
        tool_names = [tool["name"] for tool in tools]
        assert all(tool in tool_names for tool in expected_tools)
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("missing_field", ["requirement_ids", "title", "priority"])
    async def test_create_task_missing_required_fields(self, task_handler, sample_task_data, missing_field):
        """Test task creation with missing required fields"""
        incomplete_data = sample_task_data.copy()
        del incomplete_data[missing_field]
        
        result = await task_handler._create_task(**incomplete_data)
        
        assert len(result) == 1
        assert "ERROR" in result[0].text
        assert "Missing required parameters" in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("req_status,should_succeed", [
        ("Draft", False),
        ("Under Review", False),
        ("Approved", True),
        ("Architecture", True),
        ("Ready", True),
        ("Implemented", True),
        ("Validated", True),
        ("Deprecated", False),
    ])
    async def test_create_task_requirement_status_validation(
        self, task_handler, requirement_handler, sample_requirement_data, 
        sample_task_data, req_status, should_succeed
    ):
        """Test task creation with requirements in different statuses"""
        # Create requirement
        await requirement_handler._create_requirement(**sample_requirement_data)
        req_id = "REQ-0001-FUNC-00"
        
        # Move to target status through valid transitions
        if req_status != "Draft":
            transitions = {
                "Under Review": ["Under Review"],
                "Approved": ["Under Review", "Approved"],
                "Architecture": ["Under Review", "Approved", "Architecture"],
                "Ready": ["Under Review", "Approved", "Architecture", "Ready"],
                "Implemented": ["Under Review", "Approved", "Architecture", "Ready", "Implemented"],
                "Validated": ["Under Review", "Approved", "Architecture", "Ready", "Implemented", "Validated"],
                "Deprecated": ["Deprecated"],
            }
            
            for status in transitions.get(req_status, []):
                await requirement_handler._update_requirement_status(
                    requirement_id=req_id,
                    new_status=status
                )
        
        # Attempt task creation
        result = await task_handler._create_task(**sample_task_data)
        
        if should_succeed:
            assert "SUCCESS" in result[0].text
            assert "TASK-0001-00-00" in result[0].text
        else:
            assert "ERROR" in result[0].text
            assert "Cannot create tasks for unapproved requirements" in result[0].text or \
                   "deprecated" in result[0].text.lower()
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("task_count", [1, 3, 5])
    async def test_task_numbering_sequential(
        self, task_handler, approved_requirement, sample_task_data, task_count
    ):
        """Test that task numbering is sequential"""
        for i in range(task_count):
            data = sample_task_data.copy()
            data['title'] = f"Task {i+1}"
            result = await task_handler._create_task(**data)
            
            expected_id = f"TASK-{str(i+1).zfill(4)}-00-00"
            assert expected_id in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("parent_exists,subtask_level,expected_id", [
        (True, 1, "TASK-0001-01-00"),
        (True, 2, "TASK-0001-02-00"),  # Second subtask of same parent
        (False, 1, None),  # Should fail
    ])
    async def test_subtask_creation(
        self, task_handler, approved_requirement, sample_task_data,
        parent_exists, subtask_level, expected_id
    ):
        """Test subtask creation at different levels"""
        # Create parent task
        await task_handler._create_task(**sample_task_data)
        parent_id = "TASK-0001-00-00"
        
        if subtask_level == 2:
            # Create first-level subtask
            subtask_data = sample_task_data.copy()
            subtask_data['title'] = "Subtask Level 1"
            subtask_data['parent_task_id'] = parent_id
            await task_handler._create_task(**subtask_data)
            # For second subtask, keep the same parent (TASK-0001-00-00)
            # The test expects TASK-0001-02-00, not a sub-subtask
        
        # Create the target subtask
        subtask_data = sample_task_data.copy()
        subtask_data['title'] = f"Subtask Level {subtask_level}"
        subtask_data['parent_task_id'] = parent_id if parent_exists else "TASK-9999-00-00"
        
        result = await task_handler._create_task(**subtask_data)
        
        if expected_id:
            assert "SUCCESS" in result[0].text
            assert expected_id in result[0].text
        else:
            assert "ERROR" in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("current_status,new_status,should_succeed", [
        ("Not Started", "In Progress", True),
        ("Not Started", "Complete", True),
        ("Not Started", "Blocked", True),
        ("In Progress", "Complete", True),
        ("In Progress", "Blocked", True),
        ("Complete", "In Progress", True),  # Can reopen
        ("Blocked", "In Progress", True),
        ("Not Started", "Invalid Status", False),
    ])
    async def test_update_task_status_transitions(
        self, task_handler, approved_requirement, sample_task_data,
        current_status, new_status, should_succeed
    ):
        """Test various task status transitions"""
        # Create task
        await task_handler._create_task(**sample_task_data)
        task_id = "TASK-0001-00-00"
        
        # Set initial status if not "Not Started"
        if current_status != "Not Started":
            await task_handler._update_task_status(
                task_id=task_id,
                new_status=current_status
            )
        
        # Attempt transition
        result = await task_handler._update_task_status(
            task_id=task_id,
            new_status=new_status
        )
        
        if should_succeed:
            assert "SUCCESS" in result[0].text
            assert new_status in result[0].text
        else:
            assert "ERROR" in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("filter_type,filter_value,expected_count", [
        ("status", "Not Started", 3),
        ("status", "Complete", 1),
        ("priority", "P1", 2),
        ("priority", "P2", 2),
        ("assignee", "Alice", 2),
        ("assignee", "Bob", 1),
    ])
    async def test_query_tasks_with_filters(
        self, task_handler, approved_requirement, sample_task_data,
        filter_type, filter_value, expected_count
    ):
        """Test querying tasks with various filters"""
        # Create test tasks with different attributes
        tasks_config = [
            {"title": "Task 1", "priority": "P1", "assignee": "Alice", "status": "Not Started"},
            {"title": "Task 2", "priority": "P1", "assignee": "Bob", "status": "Not Started"},
            {"title": "Task 3", "priority": "P2", "assignee": "Alice", "status": "Complete"},
            {"title": "Task 4", "priority": "P2", "assignee": None, "status": "Not Started"},
        ]
        
        # Create tasks
        for i, config in enumerate(tasks_config):
            data = sample_task_data.copy()
            data.update(config)
            await task_handler._create_task(**data)
            
            # Update status if needed
            if config["status"] != "Not Started":
                await task_handler._update_task_status(
                    task_id=f"TASK-{str(i+1).zfill(4)}-00-00",
                    new_status=config["status"]
                )
        
        # Query with filter
        query_params = {filter_type: filter_value}
        result = task_handler._query_tasks(**query_params)
        
        assert len(result) == 1
        assert f"{expected_count} task" in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("include_subtasks,include_parent,include_requirements", [
        (True, False, False),   # Test subtask relationship
        (True, True, False),    # Test parent relationship (requires subtask)
        (False, False, True),   # Test requirement relationship
        (True, True, True),     # Test all relationships
    ])
    async def test_get_task_details_relationships(
        self, task_handler, approved_requirement, sample_task_data,
        include_subtasks, include_parent, include_requirements
    ):
        """Test task details with various relationship configurations"""
        # Create parent task
        await task_handler._create_task(**sample_task_data)
        
        if include_subtasks:
            # Create subtask
            subtask_data = sample_task_data.copy()
            subtask_data['title'] = "Subtask"
            subtask_data['parent_task_id'] = "TASK-0001-00-00"
            await task_handler._create_task(**subtask_data)
            
            # Get parent details
            result = task_handler._get_task_details(task_id="TASK-0001-00-00")
            assert "Subtasks" in result[0].text
            assert "TASK-0001-01-00" in result[0].text
        
        if include_parent:
            # Only test parent relationship if subtask was created
            if include_subtasks:
                # Get subtask details
                result = task_handler._get_task_details(task_id="TASK-0001-01-00")
                assert "Parent Task" in result[0].text
                assert "TASK-0001-00-00" in result[0].text
        
        if include_requirements:
            # Get task details with requirements
            result = task_handler._get_task_details(task_id="TASK-0001-00-00")
            assert "REQ-0001-FUNC-00" in result[0].text
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("effort", ["XS", "S", "M", "L", "XL"])
    async def test_task_effort_values(
        self, task_handler, approved_requirement, sample_task_data, effort
    ):
        """Test task creation with different effort values"""
        data = sample_task_data.copy()
        data['effort'] = effort
        
        result = await task_handler._create_task(**data)
        
        assert "SUCCESS" in result[0].text
        
        # Verify effort was stored
        task_id = "TASK-0001-00-00"
        details = task_handler._get_task_details(task_id=task_id)
        assert effort in details[0].text
    
    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(
        self, task_handler, approved_requirement, sample_task_data
    ):
        """Test that handle_tool_call routes correctly"""
        # Test each tool
        tools_and_params = [
            ("create_task", sample_task_data),
            ("update_task_status", {"task_id": "TASK-0001-00-00", "new_status": "In Progress"}),
            ("query_tasks", {}),
            ("get_task_details", {"task_id": "TASK-0001-00-00"}),
            ("unknown_tool", {}),
        ]
        
        # Create a task first for some operations
        await task_handler._create_task(**sample_task_data)
        
        for tool_name, params in tools_and_params:
            result = await task_handler.handle_tool_call(tool_name, params)
            assert len(result) == 1
            
            if tool_name == "unknown_tool":
                assert "Unknown tool: unknown_tool" in result[0].text
            else:
                assert "ERROR" not in result[0].text or tool_name == "get_task_details"