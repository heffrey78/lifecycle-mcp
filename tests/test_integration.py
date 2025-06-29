"""
Integration tests for MCP Lifecycle Management Server
Tests end-to-end functionality of the modular architecture
"""

import pytest
import tempfile
import os
from pathlib import Path

from src.lifecycle_mcp.server import LifecycleMCPServer


class TestMCPServerIntegration:
    """Integration tests for the complete MCP server"""
    
    @pytest.fixture
    def server_instance(self):
        """Create a server instance with temporary database"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp_file:
            db_path = tmp_file.name
        
        # Set environment variable for database path
        os.environ['LIFECYCLE_DB'] = db_path
        
        try:
            server = LifecycleMCPServer()
            yield server
        finally:
            # Clean up
            try:
                os.unlink(db_path)
            except OSError:
                pass
            if 'LIFECYCLE_DB' in os.environ:
                del os.environ['LIFECYCLE_DB']
    
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
        expected_tool_count = 21  # Total number of MCP tools
        assert len(server_instance.handlers) == expected_tool_count
    
    def test_end_to_end_requirement_workflow(self, server_instance):
        """Test complete requirement workflow from creation to validation"""
        server = server_instance
        
        # 1. Create requirement
        req_result = server.requirement_handler.handle_tool_call("create_requirement", {
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
        
        assert "Created requirement REQ-0001-FUNC-00" in req_result[0].text
        
        # 2. Create task for requirement
        task_result = server.task_handler.handle_tool_call("create_task", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Implement Integration Test Feature",
            "priority": "P1",
            "effort": "L",
            "user_story": "As a user, I want this feature to work",
            "acceptance_criteria": ["Implementation complete", "Tests pass"],
            "assignee": "Developer"
        })
        
        assert "Created task TASK-0001-00-00" in task_result[0].text
        
        # 3. Create architecture decision
        arch_result = server.architecture_handler.handle_tool_call("create_architecture_decision", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Integration Test Architecture",
            "context": "Need to decide on architecture approach",
            "decision": "Use modular architecture pattern",
            "decision_drivers": ["Maintainability", "Testability"],
            "considered_options": ["Monolithic", "Modular", "Microservices"],
            "consequences": {"positive": "Better maintainability", "negative": "Slight complexity increase"}
        })
        
        assert "Created architecture decision ADR-0001" in arch_result[0].text
        
        # 4. Update task status to complete
        task_update_result = server.task_handler.handle_tool_call("update_task_status", {
            "task_id": "TASK-0001-00-00",
            "new_status": "Complete",
            "comment": "Feature implemented successfully"
        })
        
        assert "Updated task TASK-0001-00-00 from Not Started to Complete" in task_update_result[0].text
        
        # 5. Move requirement through lifecycle
        status_updates = [
            ("Under Review", "Moving to review"),
            ("Approved", "Approved for implementation"),
            ("Ready", "Ready for development"),
            ("Implemented", "Implementation complete"),
            ("Validated", "Validation successful")
        ]
        
        for new_status, comment in status_updates:
            req_update_result = server.requirement_handler.handle_tool_call("update_requirement_status", {
                "requirement_id": "REQ-0001-FUNC-00",
                "new_status": new_status,
                "comment": comment
            })
            assert f"Updated REQ-0001-FUNC-00" in req_update_result[0].text
        
        # 6. Verify final state with trace
        trace_result = server.requirement_handler.handle_tool_call("trace_requirement", {
            "requirement_id": "REQ-0001-FUNC-00"
        })
        
        trace_text = trace_result[0].text
        assert "# Requirement Trace: REQ-0001-FUNC-00" in trace_text
        assert "Status**: Validated" in trace_text
        assert "TASK-0001-00-00" in trace_text
        assert "ADR-0001" in trace_text
    
    def test_project_status_with_data(self, server_instance):
        """Test project status reporting with actual data"""
        server = server_instance
        
        # Create some test data
        # Multiple requirements in different states
        for i in range(3):
            server.requirement_handler.handle_tool_call("create_requirement", {
                "type": "FUNC",
                "title": f"Test Requirement {i+1}",
                "priority": "P1",
                "current_state": "Current",
                "desired_state": "Desired"
            })
        
        # Update one requirement to Validated
        server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Under Review"
        })
        server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Approved"
        })
        server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Ready"
        })
        server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Implemented"
        })
        server.requirement_handler.handle_tool_call("update_requirement_status", {
            "requirement_id": "REQ-0001-FUNC-00",
            "new_status": "Validated"
        })
        
        # Create tasks
        for i in range(2):
            server.task_handler.handle_tool_call("create_task", {
                "requirement_ids": [f"REQ-000{i+1}-FUNC-00"],
                "title": f"Test Task {i+1}",
                "priority": "P1"
            })
        
        # Complete one task
        server.task_handler.handle_tool_call("update_task_status", {
            "task_id": "TASK-0001-00-00",
            "new_status": "Complete"
        })
        
        # Get project status
        status_result = server.status_handler.handle_tool_call("get_project_status", {
            "include_blocked": True
        })
        
        status_text = status_result[0].text
        assert "# Project Status Dashboard" in status_text
        assert "Requirements Overview" in status_text
        assert "Tasks Overview" in status_text
        assert "Draft" in status_text  # Should show requirements in Draft
        assert "Validated" in status_text  # Should show validated requirement
        assert "Complete" in status_text  # Should show completed task
    
    def test_export_functionality(self, server_instance):
        """Test export functionality with real data"""
        server = server_instance
        
        # Create test data
        server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Export Test Requirement",
            "priority": "P1",
            "current_state": "No export functionality",
            "desired_state": "Export functionality available",
            "business_value": "Users can export their data"
        })
        
        server.task_handler.handle_tool_call("create_task", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Implement Export Feature",
            "priority": "P1",
            "effort": "M"
        })
        
        # Test export with temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            export_result = server.export_handler.handle_tool_call("export_project_documentation", {
                "project_name": "integration-test",
                "output_directory": temp_dir,
                "include_requirements": True,
                "include_tasks": True,
                "include_architecture": False
            })
            
            assert "Successfully exported" in export_result[0].text
            assert "integration-test-requirements.md" in export_result[0].text
            assert "integration-test-tasks.md" in export_result[0].text
            
            # Verify files were created
            req_file = Path(temp_dir) / "integration-test-requirements.md"
            task_file = Path(temp_dir) / "integration-test-tasks.md"
            assert req_file.exists()
            assert task_file.exists()
            
            # Verify content
            req_content = req_file.read_text()
            assert "Export Test Requirement" in req_content
            
            task_content = task_file.read_text()
            assert "Implement Export Feature" in task_content
    
    def test_architectural_diagrams(self, server_instance):
        """Test architectural diagram generation"""
        server = server_instance
        
        # Create test data
        server.requirement_handler.handle_tool_call("create_requirement", {
            "type": "FUNC",
            "title": "Diagram Test Requirement",
            "priority": "P1",
            "current_state": "Current",
            "desired_state": "Desired"
        })
        
        server.architecture_handler.handle_tool_call("create_architecture_decision", {
            "requirement_ids": ["REQ-0001-FUNC-00"],
            "title": "Test Architecture Decision",
            "context": "Architecture context",
            "decision": "Use this approach"
        })
        
        # Test different diagram types
        diagram_types = ["requirements", "architecture", "full_project"]
        
        for diagram_type in diagram_types:
            result = server.export_handler.handle_tool_call("create_architectural_diagrams", {
                "diagram_type": diagram_type,
                "output_format": "markdown_with_mermaid"
            })
            
            assert len(result) == 1
            content = result[0].text
            assert "```mermaid" in content
            assert "flowchart TD" in content
    
    def test_interview_workflow(self, server_instance):
        """Test interview workflow integration"""
        server = server_instance
        
        # Start requirement interview
        start_result = server.interview_handler.handle_tool_call("start_requirement_interview", {
            "project_context": "Integration Test Project",
            "stakeholder_role": "Product Owner"
        })
        
        assert "# Requirement Interview Started" in start_result[0].text
        assert "Session ID" in start_result[0].text
        
        # Extract session ID (simplified for test)
        session_id = "test-session"
        server.interview_handler.interview_sessions[session_id] = {
            "project_context": "Integration Test Project",
            "stakeholder_role": "Product Owner",
            "gathered_data": {},
            "current_stage": "problem_identification",
            "questions_asked": []
        }
        
        # Continue interview through stages
        continue_result = server.interview_handler.handle_tool_call("continue_requirement_interview", {
            "session_id": session_id,
            "answers": {
                "current_problem": "No integration testing",
                "impact": "Quality issues"
            }
        })
        
        assert "Interview Progress" in continue_result[0].text
    
    def test_tool_routing_accuracy(self, server_instance):
        """Test that tool routing works correctly for all tools"""
        server = server_instance
        
        # Test that each tool routes to the correct handler
        tool_handler_mapping = {
            "create_requirement": server.requirement_handler,
            "create_task": server.task_handler,
            "create_architecture_decision": server.architecture_handler,
            "start_requirement_interview": server.interview_handler,
            "export_project_documentation": server.export_handler,
            "get_project_status": server.status_handler
        }
        
        for tool_name, expected_handler in tool_handler_mapping.items():
            actual_handler = server.handlers.get(tool_name)
            assert actual_handler == expected_handler, f"Tool {tool_name} not routed to correct handler"
    
    def test_error_handling_integration(self, server_instance):
        """Test error handling across the integrated system"""
        server = server_instance
        
        # Test handling of invalid tool calls
        try:
            # This should be handled gracefully by the server
            result = server.requirement_handler.handle_tool_call("nonexistent_tool", {})
            assert "Unknown tool" in result[0].text
        except Exception as e:
            pytest.fail(f"Error handling failed: {str(e)}")
        
        # Test handling of invalid parameters
        result = server.requirement_handler.handle_tool_call("create_requirement", {
            "title": "Missing required fields"
            # Missing type, priority, current_state, desired_state
        })
        assert "Error" in result[0].text
        assert "Missing required parameters" in result[0].text