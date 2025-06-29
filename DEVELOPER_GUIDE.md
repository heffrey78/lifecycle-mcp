# Developer Guide: Adding New Handlers

## Overview
This guide explains how to add new domain-specific handlers to the Lifecycle MCP Server using the modular handler architecture.

## Handler Architecture

The server uses a modular handler architecture where each handler is responsible for a specific domain (requirements, tasks, architecture, etc.). All handlers inherit from `BaseHandler` and follow consistent patterns.

## Creating a New Handler

### Step 1: Create Handler Class

Create a new file in `src/lifecycle_mcp/handlers/` (e.g., `my_new_handler.py`):

```python
#!/usr/bin/env python3
"""
MyNewHandler for MCP Lifecycle Management Server
Handles [description of domain] operations
"""

from typing import List, Dict, Any
from mcp.types import TextContent, Tool

from .base_handler import BaseHandler


class MyNewHandler(BaseHandler):
    """Handler for [domain] operations"""
    
    def get_tools(self) -> List[Tool]:
        """Return list of tools provided by this handler"""
        return [
            Tool(
                name="my_tool_name",
                description="Description of what this tool does",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "param1": {
                            "type": "string",
                            "description": "Description of parameter"
                        },
                        "param2": {
                            "type": "boolean", 
                            "description": "Optional boolean parameter",
                            "default": False
                        }
                    },
                    "required": ["param1"]
                }
            )
            # Add more tools as needed
        ]
    
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "my_tool_name":
                return await self._my_tool_name(arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            self.logger.error(f"Error in {tool_name}: {str(e)}")
            return self._create_error_response(f"Error executing {tool_name}", e)
    
    async def _my_tool_name(self, args: Dict[str, Any]) -> List[TextContent]:
        """Implementation of my_tool_name"""
        param1 = args.get("param1")
        param2 = args.get("param2", False)
        
        # Validate inputs
        if not param1:
            return self._create_error_response("param1 is required")
        
        try:
            # Database operations using self.db
            result = await self.db.fetch_one(
                "SELECT * FROM my_table WHERE column1 = ?",
                (param1,)
            )
            
            if result:
                response = f"Found: {result}"
            else:
                response = "No results found"
            
            return self._create_response(response)
            
        except Exception as e:
            self.logger.error(f"Database error in _my_tool_name: {str(e)}")
            return self._create_error_response("Database operation failed", e)
```

### Step 2: Update Handler Imports

Add your handler to `src/lifecycle_mcp/handlers/__init__.py`:

```python
from .base_handler import BaseHandler
from .requirement_handler import RequirementHandler
from .task_handler import TaskHandler
from .architecture_handler import ArchitectureHandler
from .interview_handler import InterviewHandler
from .export_handler import ExportHandler
from .status_handler import StatusHandler
from .my_new_handler import MyNewHandler  # Add this line

__all__ = [
    "BaseHandler",
    "RequirementHandler", 
    "TaskHandler",
    "ArchitectureHandler",
    "InterviewHandler",
    "ExportHandler",
    "StatusHandler",
    "MyNewHandler"  # Add this line
]
```

### Step 3: Register Handler in Server

Update `src/lifecycle_mcp/server.py` to include your handler:

```python
# Add import
from .handlers import (
    RequirementHandler,
    TaskHandler, 
    ArchitectureHandler,
    InterviewHandler,
    ExportHandler,
    StatusHandler,
    MyNewHandler  # Add this line
)

class LifecycleMCPServer:
    def __init__(self):
        # Initialize database manager
        self.db_manager = DatabaseManager()
        
        # Initialize handlers
        self.requirement_handler = RequirementHandler(self.db_manager)
        self.task_handler = TaskHandler(self.db_manager)
        self.architecture_handler = ArchitectureHandler(self.db_manager)
        self.interview_handler = InterviewHandler(self.db_manager, self.requirement_handler)
        self.export_handler = ExportHandler(self.db_manager)
        self.status_handler = StatusHandler(self.db_manager)
        self.my_new_handler = MyNewHandler(self.db_manager)  # Add this line
        
        # Create handler registry for tool routing
        self.handlers = {
            # Existing handlers...
            
            # Add your tools here
            "my_tool_name": self.my_new_handler,
        }
```

## Handler Development Guidelines

### 1. **Use BaseHandler Features**
- Inherit from `BaseHandler` for common functionality
- Use `self._create_response()` for success responses
- Use `self._create_error_response()` for error responses
- Access database via `self.db`
- Use `self.logger` for logging

### 2. **Follow Async Patterns**
- All handler methods must be `async`
- Use `await` for database operations
- Handle exceptions properly with try/catch

### 3. **Database Operations**
- Use `self.db.execute_query()` for INSERT/UPDATE/DELETE
- Use `self.db.fetch_one()` for single row SELECT
- Use `self.db.fetch_all()` for multiple row SELECT
- Always use parameterized queries to prevent SQL injection

### 4. **Tool Schema Design**
- Define clear input schemas with proper types
- Mark required parameters in the `required` array
- Provide helpful descriptions for all parameters
- Use appropriate JSON Schema types (string, number, boolean, array, object)

### 5. **Error Handling**
- Validate all inputs before processing
- Provide meaningful error messages
- Log errors with appropriate severity levels
- Don't expose internal implementation details to users

### 6. **Testing**
- Create unit tests for each handler method
- Mock the database manager for isolated testing
- Test both success and error cases
- Verify tool schema compliance

## Example: Complete Handler Implementation

See `src/lifecycle_mcp/handlers/requirement_handler.py` for a complete example of a well-structured handler that demonstrates:
- Multiple tools in one handler
- Complex input validation
- Database transactions
- State management
- Comprehensive error handling

## Database Schema Updates

If your handler requires new database tables or modifications:

1. Update `src/lifecycle_mcp/lifecycle-schema.sql`
2. Consider migration strategy for existing databases
3. Update the `DatabaseManager.initialize_database()` method if needed
4. Document schema changes in CLAUDE.md

## Integration Testing

After implementing your handler:

1. Test with Claude Code: `claude mcp add lifecycle-mcp`
2. Verify all tools appear in the tool list
3. Test each tool with valid and invalid inputs
4. Check error handling and logging
5. Verify database operations work correctly

## Common Patterns

### State Validation
```python
VALID_STATES = ["state1", "state2", "state3"]
if new_state not in VALID_STATES:
    return self._create_error_response(f"Invalid state: {new_state}")
```

### ID Generation
```python
async def _generate_id(self, prefix: str) -> str:
    result = await self.db.fetch_one(
        "SELECT COUNT(*) as count FROM my_table"
    )
    count = result['count'] if result else 0
    return f"{prefix}-{count + 1:04d}"
```

### JSON Field Handling
```python
import json

# Storing JSON
json_data = json.dumps(data)
await self.db.execute_query(
    "INSERT INTO table (json_field) VALUES (?)",
    (json_data,)
)

# Reading JSON
result = await self.db.fetch_one("SELECT json_field FROM table WHERE id = ?", (id,))
data = json.loads(result['json_field']) if result else {}
```

This guide provides the foundation for extending the Lifecycle MCP Server with new domain-specific functionality while maintaining consistency and code quality.