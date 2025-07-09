"""
Unit tests for above-the-fold display optimization
"""


import pytest

from lifecycle_mcp.handlers.base_handler import BaseHandler


@pytest.mark.unit
class TestAboveFoldFormatting:
    """Test cases for above-the-fold display formatting"""
    
    class ConcreteHandler(BaseHandler):
        """Concrete implementation for testing BaseHandler"""
        
        def get_tool_definitions(self):
            return []
        
        async def handle_tool_call(self, tool_name, arguments):
            return []
    
    @pytest.fixture
    def handler(self, db_manager):
        """Create a concrete handler instance for testing"""
        return self.ConcreteHandler(db_manager)
    
    def test_create_above_fold_response_basic(self, handler):
        """Test basic above-the-fold response creation"""
        result = handler._create_above_fold_response("SUCCESS", "Test message")
        
        assert len(result) == 1
        assert result[0].type == "text"
        assert "[SUCCESS] Test message" in result[0].text
    
    def test_create_above_fold_response_with_action(self, handler):
        """Test above-the-fold response with action info"""
        result = handler._create_above_fold_response(
            "SUCCESS", 
            "Task TASK-001 created", 
            "📋 Test Task | P1 | Medium"
        )
        
        text = result[0].text
        lines = text.split('\n')
        
        assert lines[0] == "[SUCCESS] Task TASK-001 created"
        assert lines[1] == "📋 Test Task | P1 | Medium"
    
    def test_create_above_fold_response_with_details(self, handler):
        """Test above-the-fold response with expandable details"""
        result = handler._create_above_fold_response(
            "INFO",
            "Requirement REQ-001 details",
            "📄 Test Requirement | FUNC | P1",
            "Detailed information here\nMore details\nEven more details"
        )
        
        text = result[0].text
        lines = text.split('\n')
        
        assert lines[0] == "[INFO] Requirement REQ-001 details"
        assert lines[1] == "📄 Test Requirement | FUNC | P1"
        assert lines[2] == "📄 Details available below (expand to view)"
        assert lines[3] == ""  # Blank separator line
        assert "Detailed information here" in text
        assert "More details" in text
    
    def test_create_above_fold_response_no_action_with_details(self, handler):
        """Test above-the-fold response without action info but with details"""
        result = handler._create_above_fold_response(
            "ERROR",
            "Operation failed",
            "",
            "Error details here"
        )
        
        text = result[0].text
        lines = text.split('\n')
        
        assert lines[0] == "[ERROR] Operation failed"
        assert lines[1] == "📄 Details available below (expand to view)"
        assert "Error details here" in text
    
    def test_format_status_summary(self, handler):
        """Test status summary formatting"""
        result = handler._format_status_summary("Task", "TASK-001", "Complete")
        assert result == "Task TASK-001 [Complete]"
        
        result_with_extra = handler._format_status_summary(
            "Requirement", "REQ-001", "Draft", "needs review"
        )
        assert result_with_extra == "Requirement REQ-001 [Draft] - needs review"
    
    def test_format_count_summary(self, handler):
        """Test count summary formatting"""
        result = handler._format_count_summary("task", 5)
        assert result == "Found 5 task(s)"
        
        result_with_filter = handler._format_count_summary(
            "requirement", 3, "status: Draft | priority: P1"
        )
        assert result_with_filter == "Found 3 requirement(s) matching: status: Draft | priority: P1"
    
    def test_error_response_uses_above_fold(self, handler):
        """Test that error responses use above-the-fold formatting"""
        result = handler._create_error_response("Test error message")
        
        text = result[0].text
        assert text.startswith("[ERROR] Test error message")
    
    def test_above_fold_response_handles_empty_strings(self, handler):
        """Test that above-the-fold response handles empty strings gracefully"""
        result = handler._create_above_fold_response("INFO", "Key info", "", "")
        
        text = result[0].text
        lines = text.split('\n')
        
        assert lines[0] == "[INFO] Key info"
        assert len(lines) == 1  # No empty lines added
    
    def test_above_fold_response_consistent_format(self, handler):
        """Test that response format is consistent"""
        # Test various combinations
        test_cases = [
            ("SUCCESS", "Operation complete", "", ""),
            ("ERROR", "Operation failed", "Try again", ""),
            ("INFO", "Status update", "Action needed", "Details here"),
            ("WARNING", "Potential issue", "", "Warning details")
        ]
        
        for status, key_info, action_info, details in test_cases:
            result = handler._create_above_fold_response(status, key_info, action_info, details)
            text = result[0].text
            
            # Always starts with [STATUS] format
            assert text.startswith(f"[{status}]")
            
            # Contains key info
            assert key_info in text
            
            # If action_info provided, it's on line 2
            if action_info:
                lines = text.split('\n')
                assert len(lines) >= 2
                assert action_info in lines[1]
            
            # If details provided, has expansion indicator
            if details:
                assert "📄 Details available below" in text
                assert details in text
    
    def test_above_fold_limits_visible_content(self, handler):
        """Test that above-the-fold format properly limits visible content"""
        result = handler._create_above_fold_response(
            "SUCCESS",
            "Short key info",
            "Brief action info", 
            "Very long details that would normally clutter the display but are now hidden below the fold"
        )
        
        text = result[0].text
        lines = text.split('\n')
        
        # First 3 lines should be concise
        assert len(lines[:3]) == 3
        assert lines[0].startswith("[SUCCESS]")
        assert "Short key info" in lines[0]
        assert "Brief action info" in lines[1]
        assert "📄 Details available below" in lines[2]
        
        # Details should be after blank line
        assert lines[3] == ""
        assert "Very long details" in lines[4]