#!/usr/bin/env python3
"""
Base Handler class for MCP Lifecycle Management Server
Provides common functionality for all domain handlers
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from mcp.types import TextContent

from ..database_manager import DatabaseManager

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    """Abstract base class for all MCP tool handlers"""
    
    def __init__(self, db_manager: DatabaseManager):
        """Initialize handler with database manager"""
        self.db = db_manager
        self.logger = logger.getChild(self.__class__.__name__)
    
    def _create_response(self, text: str) -> List[TextContent]:
        """Create standardized response format"""
        return [TextContent(type="text", text=text)]
    
    def _create_above_fold_response(self, status: str, key_info: str, action_info: str = "", details: str = "") -> List[TextContent]:
        """Create above-the-fold optimized response format
        
        Args:
            status: Status indicator (SUCCESS/ERROR/INFO etc)
            key_info: Most important information (ID, count, etc)
            action_info: Actionable information or next steps (optional)
            details: Detailed information for expansion (optional)
        """
        # Line 1: Status + Key Info
        line1 = f"[{status}] {key_info}"
        
        # Line 2: Action info if provided
        line2 = action_info if action_info else ""
        
        # Line 3: Summary or continuation indicator
        if details:
            line3 = "📄 Details available below (expand to view)"
        else:
            line3 = ""
        
        # Build response
        response_lines = [line1]
        if line2:
            response_lines.append(line2)
        if line3:
            response_lines.append(line3)
        
        # Add details section if provided
        if details:
            response_lines.append("")  # Blank line separator
            response_lines.append(details)
        
        return [TextContent(type="text", text="\n".join(response_lines))]
    
    def _format_status_summary(self, entity_type: str, entity_id: str, status: str, extra_info: str = "") -> str:
        """Format a concise status summary for above-the-fold display"""
        base = f"{entity_type} {entity_id} [{status}]"
        if extra_info:
            return f"{base} - {extra_info}"
        return base
    
    def _format_count_summary(self, entity_type: str, count: int, filter_desc: str = "") -> str:
        """Format a count summary for above-the-fold display"""
        if filter_desc:
            return f"Found {count} {entity_type}(s) matching: {filter_desc}"
        return f"Found {count} {entity_type}(s)"
    
    def _create_error_response(self, error_msg: str, exception: Optional[Exception] = None) -> List[TextContent]:
        """Create standardized error response"""
        if exception:
            self.logger.error(f"{error_msg}: {str(exception)}")
            full_error = f"{error_msg}: {str(exception)}"
        else:
            self.logger.error(error_msg)
            full_error = error_msg
        
        # Use above-the-fold format for errors
        return self._create_above_fold_response("ERROR", error_msg)
    
    def _validate_required_params(self, params: Dict[str, Any], required_fields: List[str]) -> Optional[str]:
        """Validate that required parameters are present"""
        missing = [field for field in required_fields if field not in params or params[field] is None]
        if missing:
            return f"Missing required parameters: {', '.join(missing)}"
        return None
    
    def _safe_json_loads(self, json_str: Optional[str], default: Any = None) -> Any:
        """Safely load JSON string with fallback"""
        if not json_str:
            return default or []
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"Failed to parse JSON: {json_str}")
            return default or []
    
    def _safe_json_dumps(self, data: Any) -> str:
        """Safely dump data to JSON string"""
        try:
            return json.dumps(data) if data is not None else "[]"
        except (TypeError, ValueError) as e:
            self.logger.warning(f"Failed to serialize to JSON: {str(e)}")
            return "[]"
    
    def _log_operation(self, entity_type: str, entity_id: str, event_type: str, actor: str = "MCP User"):
        """Log lifecycle events"""
        try:
            self.db.insert_record("lifecycle_events", {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "event_type": event_type,
                "actor": actor
            })
        except Exception as e:
            self.logger.warning(f"Failed to log event: {str(e)}")
    
    def _add_review_comment(self, entity_type: str, entity_id: str, comment: str, reviewer: str = "MCP User"):
        """Add review comment to an entity"""
        try:
            self.db.insert_record("reviews", {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "reviewer": reviewer,
                "comment": comment
            })
        except Exception as e:
            self.logger.warning(f"Failed to add review comment: {str(e)}")
    
    @abstractmethod
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return list of tool definitions this handler provides"""
        pass
    
    @abstractmethod
    async def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> List[TextContent]:
        """Handle a tool call for this handler's domain"""
        pass