"""
Unit tests for StatusHandler
"""

import pytest

from lifecycle_mcp.handlers.status_handler import StatusHandler


@pytest.mark.unit
class TestStatusHandler:
    """Test cases for StatusHandler"""
    
    def test_get_tool_definitions(self, status_handler):
        """Test that handler returns correct tool definitions"""
        tools = status_handler.get_tool_definitions()
        assert len(tools) == 1
        
        tool_names = [tool["name"] for tool in tools]
        assert "get_project_status" in tool_names
    
    def test_get_project_status_empty_project(self, status_handler):
        """Test getting status for empty project"""
        result = status_handler._get_project_status()
        
        assert len(result) == 1
        assert "INFO" in result[0].text
        assert "Project" in result[0].text and "status" in result[0].text
        
        # Should show zero counts
        text = result[0].text
        assert "0 requirements" in text or "No requirements" in text
        assert "0 tasks" in text or "No tasks" in text
        # Architecture decisions are not always shown in empty status
    
    @pytest.mark.asyncio
    async def test_get_project_status_with_requirements(
        self, status_handler, requirement_handler, sample_requirement_data
    ):
        """Test project status with requirements in various states"""
        # Create requirements in different states
        statuses = ["Draft", "Under Review", "Approved"]
        
        for i, status in enumerate(statuses):
            data = sample_requirement_data.copy()
            data['title'] = f"Requirement {i+1}"
            await requirement_handler._create_requirement(**data)
            
            if status != "Draft":
                if status == "Under Review":
                    await requirement_handler._update_requirement_status(
                        requirement_id=f"REQ-000{i+1}-FUNC-00",
                        new_status="Under Review"
                    )
                elif status == "Approved":
                    await requirement_handler._update_requirement_status(
                        requirement_id=f"REQ-000{i+1}-FUNC-00",
                        new_status="Under Review"
                    )
                    await requirement_handler._update_requirement_status(
                        requirement_id=f"REQ-000{i+1}-FUNC-00",
                        new_status="Approved"
                    )
        
        result = status_handler._get_project_status()
        
        assert len(result) == 1
        text = result[0].text
        
        # Should show requirement counts by status
        assert "3 requirements" in text
        assert "Draft" in text
        assert "Under Review" in text
        assert "Approved" in text
        
        # Should show counts for each status
        assert "**Draft**: 1" in text
        assert "**Under Review**: 1" in text
        assert "**Approved**: 1" in text
    
    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(self, status_handler):
        """Test that handle_tool_call routes correctly"""
        # Test get_project_status routing
        result = await status_handler.handle_tool_call("get_project_status", {})
        assert len(result) == 1
        assert "INFO" in result[0].text
        
        # Test with parameters
        result = await status_handler.handle_tool_call(
            "get_project_status", 
            {"include_blocked": True}
        )
        assert len(result) == 1
        assert "INFO" in result[0].text
        
        # Test unknown tool
        result = await status_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool: unknown_tool" in result[0].text
    
    def test_empty_project_messaging(self, status_handler):
        """Test helpful messaging for empty projects"""
        result = status_handler._get_project_status()
        
        text = result[0].text
        
        # Should provide guidance for empty project
        assert "No requirements" in text or "0 requirements" in text
        
        # Should still show structure
        assert "Requirements" in text or "requirements" in text
        assert "Tasks" in text or "tasks" in text
        # Architecture might not be shown in empty project
