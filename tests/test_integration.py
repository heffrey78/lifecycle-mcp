"""
Integration tests for MCP Lifecycle Management Server
Tests end-to-end functionality of the modular architecture
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

import pytest

from lifecycle_mcp.server import LifecycleMCPServer

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.mark.integration
class TestMCPServerIntegration:
    """Integration tests for the complete MCP server"""
    
    @pytest.fixture
    def server_instance(self):
        """
        Create a server instance with properly initialized temporary database.
        
        This fixture implements best practices:
        1. Ensures database is properly initialized with schema
        2. Provides complete isolation between tests
        3. Handles async initialization correctly
        4. Cleans up resources reliably
        """
        # Create a truly temporary directory for our test
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, 'test_lifecycle.db')
            
            # Set environment variable for database path
            original_env = os.environ.get('LIFECYCLE_DB')
            os.environ['LIFECYCLE_DB'] = db_path
            
            try:
                # Create server instance
                server = LifecycleMCPServer()
                
                # Verify database was properly initialized
                with server.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [row[0] for row in cursor.fetchall()]
                    
                    required_tables = ['requirements', 'tasks', 'architecture', 'requirement_tasks']
                    for table in required_tables:
                        if table not in tables:
                            raise RuntimeError(f"Database initialization failed: missing table '{table}'")
                    
                    logger.info(f"Database initialized successfully with tables: {tables}")
                
                yield server
                
            finally:
                # Restore original environment
                if original_env is None:
                    os.environ.pop('LIFECYCLE_DB', None)
                else:
                    os.environ['LIFECYCLE_DB'] = original_env
                
                # Close database connections properly
                if hasattr(server, 'db_manager'):
                    server.db_manager.close()
    
    def test_server_initialization(self, server_instance):
        """Test that server initializes correctly with all handlers"""
        assert server_instance.db_manager is not None
        assert server_instance.requirement_handler is not None
        assert server_instance.task_handler is not None
        assert server_instance.architecture_handler is not None
        assert server_instance.interview_handler is not None
        assert server_instance.export_handler is not None
        assert server_instance.status_handler is not None
        
        # Verify all tools are registered
        # Total number of MCP tools (including sync_task_from_github and bulk_sync_github_tasks)
        expected_tool_count = 23
        assert len(server_instance.handlers) == expected_tool_count
    
    @pytest.mark.asyncio
    async def test_end_to_end_requirement_workflow(self, server_instance):
        """Test complete requirement workflow from creation to validation"""
        server = server_instance
        
        # 1. Create requirement
        req_result = await server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Integration Test Requirement",
            "priority": "P1",
            "current_state": "No functionality exists",
            "desired_state": "Functionality implemented and tested",
            "functional_requirements": ["Feature A", "Feature B"],
            "acceptance_criteria": ["AC1", "AC2"],
            "business_value": "Improved user experience",
            "author": "Integration Test"
        })
        
        assert len(req_result) == 1
        assert "SUCCESS" in req_result[0].text  # Check for above-fold format
        assert "REQ-0001-FUNC-00" in req_result[0].text
        
        # 2. Move requirement through proper status transitions to allow task creation
        transitions = [
            ("Under Review", "Moving to review phase"),
            ("Approved", "Requirement approved for implementation")
        ]
        
        for new_status, comment in transitions:
            status_result = await server.requirement_handler.handle_tool_call("update_requirement_status", {
                "requirement_id": "REQ-0001-FUNC-00",
                "new_status": new_status,
                "comment": comment
            })
            assert "SUCCESS" in status_result[0].text
        
        # 3. Create task for approved requirement
        task_result = await server.task_handler.handle_tool_call("create_task", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Implement Integration Test Feature",
            "priority": "P1",
            "effort": "L",
            "user_story": "As a user, I want this feature to work",
            "acceptance_criteria": ["Implementation complete", "Tests pass"],
            "assignee": "TestDev"  # Use simple assignee name without spaces
        })
        
        assert len(task_result) == 1
        assert "SUCCESS" in task_result[0].text  # Check for above-fold format
        assert "TASK-0001-00-00" in task_result[0].text
        
        # 4. Create architecture decision
        arch_result = await server.architecture_handler.handle_tool_call("create_architecture_decision", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Integration Test Architecture",
            "context": "Need to decide on architecture approach",
            "decision": "Use modular architecture pattern",
            "decision_drivers": ["Maintainability", "Testability"],
            "considered_options": ["Monolithic", "Modular", "Microservices"],
            "consequences": {"positive": "Better maintainability", "negative": "Slight complexity increase"}
        })
        
        assert len(arch_result) == 1
        assert "SUCCESS" in arch_result[0].text  # Check for above-fold format
        assert "ADR-0001" in arch_result[0].text
        
        # 5. Update task status to complete
        task_update_result = await server.task_handler.handle_tool_call("update_task_status", {
            "task_id": "TASK-0001-00-00",
            "new_status": "Complete",
            "comment": "Feature implemented successfully"
        })
        
        assert len(task_update_result) == 1
        assert "SUCCESS" in task_update_result[0].text
        
        # 6. Move requirement through remaining lifecycle states
        final_transitions = [
            ("Architecture", "Architecture defined"),
            ("Ready", "Ready for development"),
            ("Implemented", "Implementation complete"),
            ("Validated", "Validation successful")
        ]
        
        for new_status, comment in final_transitions:
            req_update_result = await server.requirement_handler.handle_tool_call("update_requirement_status", {
                "requirement_id": "REQ-0001-FUNC-00",
                "new_status": new_status,
                "comment": comment
            })
            assert "SUCCESS" in req_update_result[0].text
        
        # 7. Verify final state with trace
        trace_result = server.requirement_handler.handle_tool_call("trace_requirement", {
            "requirement_id": "REQ-0001-FUNC-00"
        })
        
        # Handle sync trace_requirement call
        if asyncio.iscoroutine(trace_result):
            trace_result = await trace_result
        
        assert len(trace_result) == 1
        trace_text = trace_result[0].text
        assert "INFO" in trace_text  # Check for above-fold format
        assert "REQ-0001-FUNC-00" in trace_text
        assert "Validated" in trace_text
        assert "TASK-0001-00-00" in trace_text
        assert "ADR-0001" in trace_text
    
    @pytest.mark.asyncio
    async def test_project_status_with_data(self, server_instance):
        """Test project status reporting with actual data"""
        server = server_instance
        
        # Create multiple requirements in different states
        requirements = [
            ("Test Requirement 1", "P0", "Draft"),
            ("Test Requirement 2", "P1", "Approved"),
            ("Test Requirement 3", "P2", "Validated")
        ]
        
        for i, (title, priority, target_status) in enumerate(requirements):
            # Create requirement
            req_result = await server.requirement_handler.handle_tool_call("create_requirement", {
                "type": "FUNC",
                "title": title,
                "priority": priority,
                "current_state": "Current state",
                "desired_state": "Desired state",
                "author": "Test Suite"
            })
            assert "SUCCESS" in req_result[0].text
            
            # Move to target status if not Draft
            if target_status == "Approved":
                await server.requirement_handler.handle_tool_call("update_requirement_status", {
                    "requirement_id": f"REQ-000{i+1}-FUNC-00",
                    "new_status": "Under Review"
                })
                await server.requirement_handler.handle_tool_call("update_requirement_status", {
                    "requirement_id": f"REQ-000{i+1}-FUNC-00",
                    "new_status": "Approved"
                })
            elif target_status == "Validated":
                # Move through full lifecycle
                for status in ["Under Review", "Approved", "Architecture", "Ready", "Implemented", "Validated"]:
                    await server.requirement_handler.handle_tool_call("update_requirement_status", {
                        "requirement_id": f"REQ-000{i+1}-FUNC-00",
                        "new_status": status
                    })
        
        # Create tasks for approved requirement
        task_result = await server.task_handler.handle_tool_call("create_task", {
            "requirement_ids": ["REQ-0002-FUNC-00"],
            "title": "Test Task",
            "priority": "P1"
        })
        assert "SUCCESS" in task_result[0].text
        
        # Get project status
        status_result = await server.status_handler.handle_tool_call("get_project_status", {})
        
        assert len(status_result) == 1
        status_text = status_result[0].text
        
        # Verify status contains expected information
        assert "INFO" in status_text  # Above-fold format
        assert "Project" in status_text
        assert "3 requirements" in status_text  # Summary shows 3 requirements
        assert "**Draft**: 1" in status_text
        assert "**Approved**: 1" in status_text
        assert "**Validated**: 1" in status_text
        assert "Total Requirements**: 3" in status_text
    
    @pytest.mark.asyncio
    async def test_export_functionality(self, server_instance):
        """Test documentation export functionality"""
        server = server_instance
        
        # Create some test data
        req_result = await server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Export Test Requirement",
            "priority": "P1",
            "current_state": "No export",
            "desired_state": "Can export docs",
            "author": "Test"
        })
        assert "SUCCESS" in req_result[0].text
        
        # Test export with temporary directory
        with tempfile.TemporaryDirectory() as export_dir:
            export_result = await server.export_handler.handle_tool_call("export_project_documentation", {
                "output_directory": export_dir,
                "project_name": "test_project"
            })
            
            assert len(export_result) == 1
            assert "SUCCESS" in export_result[0].text
            
            # Verify files were created - check what files are actually created
            created_files = list(Path(export_dir).glob("*.md"))
            assert len(created_files) > 0, "No markdown files were created"
            
            # At least one file should contain project documentation
            file_contents = []
            for filepath in created_files:
                with open(filepath, 'r') as f:
                    file_contents.append(f.read())
            
            all_content = '\n'.join(file_contents)
            assert "Export Test Requirement" in all_content, "Exported files should contain the test requirement"
    
    @pytest.mark.asyncio  
    async def test_architectural_diagrams(self, server_instance):
        """Test architecture diagram generation"""
        server = server_instance
        
        # Create test data
        req_result = await server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Diagram Test Requirement",
            "priority": "P1",
            "current_state": "No diagrams",
            "desired_state": "Has diagrams",
            "author": "Test"
        })
        assert "SUCCESS" in req_result[0].text
        
        # Generate diagram
        with tempfile.TemporaryDirectory() as diagram_dir:
            diagram_result = await server.export_handler.handle_tool_call("create_architectural_diagrams", {
                "diagram_type": "requirements",
                "output_path": diagram_dir
            })
            
            assert len(diagram_result) == 1
            assert "SUCCESS" in diagram_result[0].text
            
            # Check that diagram file was created
            diagram_files = list(Path(diagram_dir).glob("*.mmd"))
            assert len(diagram_files) > 0, "No Mermaid diagram files were created"
    
    @pytest.mark.asyncio
    async def test_interview_workflow(self, server_instance):
        """Test interactive interview workflow"""
        server = server_instance
        
        # Start requirement interview
        interview_result = await server.interview_handler.handle_tool_call("start_requirement_interview", {
            "project_context": "Test project for integration testing",
            "stakeholder_role": "Product Owner"
        })
        
        assert len(interview_result) == 1
        assert "SUCCESS" in interview_result[0].text
        
        # Extract session ID from response
        response_text = interview_result[0].text
        # Session ID should be in the response - check for actual response format
        assert "Interview session" in response_text or "session" in response_text.lower()
    
    def test_tool_routing_accuracy(self, server_instance):
        """Test that tools are correctly routed to handlers"""
        server = server_instance
        
        # Test tool routing
        tool_handler_mapping = {
            "create_requirement": server.requirement_handler,
            "create_task": server.task_handler,
            "create_architecture_decision": server.architecture_handler,
            "start_requirement_interview": server.interview_handler,
            "export_project_documentation": server.export_handler,
            "get_project_status": server.status_handler
        }
        
        for tool_name, expected_handler in tool_handler_mapping.items():
            assert tool_name in server.handlers
            assert server.handlers[tool_name] == expected_handler
    
    @pytest.mark.asyncio
    async def test_error_handling_integration(self, server_instance):
        """Test error handling across the integrated system"""
        server = server_instance
        
        # Test invalid requirement creation
        error_result = await server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "INVALID_TYPE",  # Invalid type
            "title": "Error Test"
            # Missing required fields
        })
        
        assert len(error_result) == 1
        assert "ERROR" in error_result[0].text
        
        # Test invalid task creation (requirement doesn't exist)
        task_error = await server.task_handler.handle_tool_call("create_task", {
            "requirement_ids": ["REQ-9999-FUNC-00"],  # Non-existent
            "title": "Error Task",
            "priority": "P1"
        })
        
        assert len(task_error) == 1
        assert "ERROR" in task_error[0].text
        assert "not found" in task_error[0].text
        
        # Test invalid status transition
        # First create a valid requirement
        req_result = await server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Transition Test",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired",
            "author": "Test"
        })
        assert "SUCCESS" in req_result[0].text
        
        # Try invalid transition from Draft to Validated
        transition_error = await server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Validated"  # Invalid transition from Draft
        })
        
        assert len(transition_error) == 1
        assert "ERROR" in transition_error[0].text
        assert "Invalid transition" in transition_error[0].text