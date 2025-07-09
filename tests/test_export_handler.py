"""
Unit tests for ExportHandler
"""

import tempfile
from pathlib import Path

import pytest


@pytest.mark.unit
class TestExportHandler:
    """Test cases for ExportHandler"""
    
    def test_get_tool_definitions(self, export_handler):
        """Test that handler returns correct tool definitions"""
        tools = export_handler.get_tool_definitions()
        assert len(tools) == 2
        
        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "export_project_documentation",
            "create_architectural_diagrams"
        ]
        assert all(tool in tool_names for tool in expected_tools)
    
    def test_export_project_documentation_empty_project(self, export_handler):
        """Test exporting documentation for empty project"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._export_project_documentation(
                output_directory=temp_dir,
                project_name="test_project"
            )
            
            # When there's no data, it should return INFO message
            assert len(result) == 1
            assert "INFO" in result[0].text
            assert "No data found to export" in result[0].text
            
            # Check that no files were created for empty project
            export_path = Path(temp_dir)
            assert export_path.exists()
            
            # Should not create any markdown files when there's no data
            md_files = list(export_path.glob("*.md"))
            assert len(md_files) == 0
    
    @pytest.mark.asyncio
    async def test_export_project_documentation_with_data(
        self, export_handler, requirement_handler, task_handler, architecture_handler,
        sample_requirement_data, sample_task_data, sample_architecture_data
    ):
        """Test exporting documentation with actual project data"""
        # Create test data
        await requirement_handler._create_requirement(**sample_requirement_data)
        
        # Approve requirement for task creation
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        await task_handler._create_task(**sample_task_data)
        await architecture_handler._create_architecture_decision(**sample_architecture_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._export_project_documentation(
                output_directory=temp_dir,
                project_name="test_project",
                include_requirements=True,
                include_tasks=True,
                include_architecture=True
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify exported content contains our test data
            md_files = list(Path(temp_dir).glob("*.md"))
            content = ""
            for file in md_files:
                with open(file, 'r') as f:
                    content += f.read()
            
            assert "Test Requirement" in content
            assert "Test Task" in content
            assert "Test Architecture Decision" in content
    
    @pytest.mark.asyncio
    async def test_export_project_documentation_selective(
        self, export_handler, requirement_handler, sample_requirement_data
    ):
        """Test selective export of documentation"""
        # Create test data
        await requirement_handler._create_requirement(**sample_requirement_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Export only requirements
            result = export_handler._export_project_documentation(
                output_directory=temp_dir,
                project_name="test_project",
                include_requirements=True,
                include_tasks=False,
                include_architecture=False
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify content
            md_files = list(Path(temp_dir).glob("*.md"))
            content = ""
            for file in md_files:
                with open(file, 'r') as f:
                    content += f.read()
            
            assert "Test Requirement" in content
            assert "Tasks" not in content or "No tasks" in content
    
    def test_export_project_documentation_invalid_directory(self, export_handler):
        """Test export with invalid directory"""
        result = export_handler._export_project_documentation(
            output_directory="/invalid/path/that/does/not/exist",
            project_name="test_project"
        )
        
        assert len(result) == 1
        assert "ERROR" in result[0].text
    
    @pytest.mark.asyncio
    async def test_create_architectural_diagrams_requirements(
        self, export_handler, requirement_handler, sample_requirement_data
    ):
        """Test creating requirements diagram"""
        # Create test requirements
        for i in range(3):
            data = sample_requirement_data.copy()
            data['title'] = f"Requirement {i+1}"
            data['type'] = ["FUNC", "TECH", "BUS"][i % 3]
            await requirement_handler._create_requirement(**data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._create_architectural_diagrams(
                diagram_type="requirements",
                output_path=temp_dir
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            assert "diagram" in result[0].text.lower()
            
            # Check that Mermaid file was created
            mmd_files = list(Path(temp_dir).glob("*.mmd"))
            assert len(mmd_files) > 0
            
            # Verify Mermaid content
            with open(mmd_files[0], 'r') as f:
                content = f.read()
                assert "graph" in content or "flowchart" in content
                assert "REQ-0001-FUNC-00" in content
    
    @pytest.mark.asyncio
    async def test_create_architectural_diagrams_tasks(
        self, export_handler, requirement_handler, task_handler, 
        sample_requirement_data, sample_task_data
    ):
        """Test creating tasks diagram"""
        # Create requirement and tasks
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        await task_handler._create_task(**sample_task_data)
        
        # Create subtask
        subtask_data = sample_task_data.copy()
        subtask_data['title'] = "Subtask"
        subtask_data['parent_task_id'] = "TASK-0001-00-00"
        await task_handler._create_task(**subtask_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._create_architectural_diagrams(
                diagram_type="tasks",
                output_path=temp_dir
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify content includes task hierarchy
            mmd_files = list(Path(temp_dir).glob("*.mmd"))
            with open(mmd_files[0], 'r') as f:
                content = f.read()
                assert "TASK-0001-00-00" in content
                assert "TASK-0001-01-00" in content
    
    @pytest.mark.asyncio
    async def test_create_architectural_diagrams_full_project(
        self, export_handler, requirement_handler, task_handler, architecture_handler,
        sample_requirement_data, sample_task_data, sample_architecture_data
    ):
        """Test creating full project diagram"""
        # Create comprehensive test data
        await requirement_handler._create_requirement(**sample_requirement_data)
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Under Review"
        )
        await requirement_handler._update_requirement_status(
            requirement_id="REQ-0001-FUNC-00",
            new_status="Approved"
        )
        
        await task_handler._create_task(**sample_task_data)
        await architecture_handler._create_architecture_decision(**sample_architecture_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._create_architectural_diagrams(
                diagram_type="full_project",
                output_path=temp_dir,
                include_relationships=True
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify comprehensive diagram
            mmd_files = list(Path(temp_dir).glob("*.mmd"))
            with open(mmd_files[0], 'r') as f:
                content = f.read()
                assert "REQ-0001-FUNC-00" in content
                assert "TASK-0001-00-00" in content
                assert "ADR-0001" in content
                # Should show relationships
                assert "-->" in content or "---" in content
    
    @pytest.mark.asyncio
    async def test_create_architectural_diagrams_filtered(
        self, export_handler, requirement_handler, sample_requirement_data
    ):
        """Test creating diagram with requirement filter"""
        # Create multiple requirements
        await requirement_handler._create_requirement(**sample_requirement_data)
        
        req_data2 = sample_requirement_data.copy()
        req_data2['title'] = "Excluded Requirement"
        await requirement_handler._create_requirement(**req_data2)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._create_architectural_diagrams(
                diagram_type="requirements",
                output_path=temp_dir,
                requirement_ids=["REQ-0001-FUNC-00"]
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify only specified requirement is included
            mmd_files = list(Path(temp_dir).glob("*.mmd"))
            with open(mmd_files[0], 'r') as f:
                content = f.read()
                assert "REQ-0001-FUNC-00" in content
                assert "REQ-0002-FUNC-00" not in content
    
    @pytest.mark.asyncio
    async def test_create_architectural_diagrams_invalid_type(self, export_handler):
        """Test creating diagram with invalid type"""
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._create_architectural_diagrams(
                diagram_type="invalid_type",
                output_path=temp_dir
            )
            
            assert len(result) == 1
            assert "ERROR" in result[0].text
            assert "Invalid diagram type" in result[0].text
    
    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(self, export_handler):
        """Test that handle_tool_call routes correctly"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test export_project_documentation routing
            result = await export_handler.handle_tool_call(
                "export_project_documentation",
                {"output_directory": temp_dir, "project_name": "test"}
            )
            assert len(result) == 1
            # When there's no data, it returns INFO
            assert "INFO" in result[0].text or "SUCCESS" in result[0].text
            
            # Test unknown tool
            result = await export_handler.handle_tool_call("unknown_tool", {})
            assert len(result) == 1
            assert "Unknown tool: unknown_tool" in result[0].text
    
    @pytest.mark.asyncio
    async def test_export_markdown_formatting(
        self, export_handler, requirement_handler, sample_requirement_data
    ):
        """Test that exported markdown is properly formatted"""
        # Create requirement with special characters
        req_data = sample_requirement_data.copy()
        req_data['title'] = "Test & Special <Characters>"
        req_data['functional_requirements'] = ["Feature with **bold**", "Feature with _italic_"]
        await requirement_handler._create_requirement(**req_data)
        
        with tempfile.TemporaryDirectory() as temp_dir:
            result = export_handler._export_project_documentation(
                output_directory=temp_dir,
                project_name="test_project"
            )
            
            assert len(result) == 1
            assert "SUCCESS" in result[0].text
            
            # Verify markdown escaping
            md_files = list(Path(temp_dir).glob("*.md"))
            with open(md_files[0], 'r') as f:
                content = f.read()
                # Should handle special characters appropriately
                assert "Test & Special" in content
                assert "**bold**" in content or "\\*\\*bold\\*\\*" in content