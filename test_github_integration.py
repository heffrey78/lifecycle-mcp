#!/usr/bin/env python3
"""
Simple test script for GitHub integration
"""

import asyncio
import json
import sys
import os

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from lifecycle_mcp.handlers.task_handler import TaskHandler
from lifecycle_mcp.database_manager import DatabaseManager


async def test_github_integration():
    """Test the GitHub integration functionality"""
    
    # Initialize test database
    test_db_path = "test_lifecycle.db"
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    # Create database manager and task handler
    db_manager = DatabaseManager(test_db_path)
    task_handler = TaskHandler(db_manager)
    
    # First create a requirement to link to
    db_manager.insert_record("requirements", {
        "id": "REQ-0001-FUNC-01",
        "requirement_number": 1,
        "version": 1,
        "type": "FUNC",
        "title": "Test Requirement",
        "priority": "P1",
        "current_state": "No GitHub integration",
        "desired_state": "GitHub integration working",
        "author": "test@example.com"
    })
    
    print("Testing GitHub integration...")
    print("1. Creating a task with GitHub integration")
    
    # Test creating a task
    result = await task_handler._create_task(
        requirement_ids=["REQ-0001-FUNC-01"],
        title="Test GitHub Integration",
        priority="P1",
        effort="S",
        user_story="As a developer, I want GitHub issues to be created automatically when tasks are created",
        acceptance_criteria=["GitHub issue is created", "Issue contains proper metadata", "Issue URL is stored"]
    )
    
    print(f"Create task result: {result[0].text}")
    
    # Get the created task to test updates
    tasks = db_manager.get_records(
        "tasks", 
        "id, github_issue_number, github_issue_url", 
        "title = ?", 
        ["Test GitHub Integration"]
    )
    
    if tasks:
        task = tasks[0]
        print(f"Task created: {task['id']}")
        if task['github_issue_number']:
            print(f"GitHub issue created: #{task['github_issue_number']}")
            print(f"GitHub issue URL: {task['github_issue_url']}")
            
            print("\n2. Testing task status update")
            update_result = await task_handler._update_task_status(
                task_id=task['id'],
                new_status="In Progress",
                comment="Starting work on GitHub integration"
            )
            print(f"Update task result: {update_result[0].text}")
            
            print("\n3. Testing task completion")
            complete_result = await task_handler._update_task_status(
                task_id=task['id'],
                new_status="Complete",
                comment="GitHub integration is working!"
            )
            print(f"Complete task result: {complete_result[0].text}")
        else:
            print("No GitHub issue was created (gh CLI might not be available or not in a GitHub repo)")
    
    # Clean up test database
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
    
    print("\nGitHub integration test completed!")


if __name__ == "__main__":
    asyncio.run(test_github_integration())