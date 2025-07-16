#!/usr/bin/env python3
"""
Configuration management for lifecycle-mcp
Handles environment variables and configuration file settings
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class Config:
    """Configuration manager for lifecycle-mcp"""
    
    def __init__(self):
        """Initialize configuration with environment variables and config file"""
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from environment and config file"""
        # Core settings
        self._config['database_path'] = os.environ.get("LIFECYCLE_DB", "lifecycle.db")
        
        # GitHub Integration settings
        self._config['github_integration_enabled'] = self._get_bool_env(
            "GITHUB_INTEGRATION_ENABLED", False
        )
        
        # GitHub API settings
        self._config['github_token'] = os.environ.get("GITHUB_TOKEN")
        self._config['github_repo'] = os.environ.get("GITHUB_REPO")
        
        # GitHub Project Board settings
        self._config['github_project_id'] = os.environ.get("GITHUB_PROJECT_ID")
        self._config['github_project_type'] = os.environ.get("GITHUB_PROJECT_TYPE", "v2")  # v1 or v2
        
        # Load from config file if it exists
        config_file = os.environ.get("LIFECYCLE_CONFIG_FILE", "lifecycle-config.json")
        self._load_config_file(config_file)
    
    def _get_bool_env(self, env_var: str, default: bool) -> bool:
        """Get boolean environment variable with proper parsing"""
        value = os.environ.get(env_var, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        elif value in ("false", "0", "no", "off"):
            return False
        else:
            return default
    
    def _load_config_file(self, config_file: str):
        """Load configuration from JSON file if it exists"""
        try:
            config_path = Path(config_file)
            if config_path.exists():
                with open(config_path, 'r') as f:
                    file_config = json.load(f)
                
                # Merge file config with environment config (env takes precedence)
                for key, value in file_config.items():
                    if key not in self._config or self._config[key] is None:
                        self._config[key] = value
                        
        except Exception as e:
            # Don't fail if config file is invalid, just log and continue
            print(f"Warning: Could not load config file {config_file}: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        return self._config.get(key, default)
    
    def is_github_integration_enabled(self) -> bool:
        """Check if GitHub integration is enabled"""
        return self._config.get('github_integration_enabled', False)
    
    def get_github_token(self) -> Optional[str]:
        """Get GitHub token"""
        return self._config.get('github_token')
    
    def get_github_repo(self) -> Optional[str]:
        """Get GitHub repository"""
        return self._config.get('github_repo')
    
    def get_github_project_id(self) -> Optional[str]:
        """Get GitHub project ID"""
        return self._config.get('github_project_id')
    
    def get_github_project_type(self) -> str:
        """Get GitHub project type (v1 or v2)"""
        return self._config.get('github_project_type', 'v2')
    
    def validate_github_config(self) -> Tuple[bool, List[str]]:
        """Validate GitHub configuration and return (is_valid, error_messages)"""
        errors = []
        
        if not self.is_github_integration_enabled():
            return True, []  # If disabled, no validation needed
        
        # Check required GitHub settings
        if not self.get_github_token():
            errors.append("GITHUB_TOKEN is required when GitHub integration is enabled")
        
        if not self.get_github_repo():
            errors.append("GITHUB_REPO is required when GitHub integration is enabled")
        
        # Validate project type
        project_type = self.get_github_project_type()
        if project_type not in ('v1', 'v2'):
            errors.append(f"GITHUB_PROJECT_TYPE must be 'v1' or 'v2', got '{project_type}'")
        
        return len(errors) == 0, errors
    
    def get_status_mappings(self) -> Dict[str, str]:
        """Get lifecycle to GitHub status mappings"""
        default_mappings = {
            "Not Started": "Todo",
            "In Progress": "In Progress", 
            "Blocked": "Blocked",
            "Complete": "Done",
            "Abandoned": "Abandoned"
        }
        
        return self._config.get('status_mappings', default_mappings)
    
    def get_reverse_status_mappings(self) -> Dict[str, str]:
        """Get GitHub to lifecycle status mappings"""
        mappings = self.get_status_mappings()
        return {v: k for k, v in mappings.items()}
    
    def update_github_project_config(
        self, 
        project_id: Optional[str] = None,
        project_type: Optional[str] = None,
        persist: bool = True
    ) -> bool:
        """
        Update GitHub project configuration
        
        Args:
            project_id: New GitHub project ID
            project_type: New project type ('v1' or 'v2')
            persist: Whether to save to config file
            
        Returns:
            True if update successful
        """
        try:
            if project_id is not None:
                self._config['github_project_id'] = project_id
                
            if project_type is not None:
                if project_type not in ('v1', 'v2'):
                    raise ValueError(f"Invalid project type: {project_type}")
                self._config['github_project_type'] = project_type
            
            if persist:
                self._save_config_file()
                
            return True
            
        except Exception as e:
            print(f"Error updating GitHub project config: {e}")
            return False
    
    def _save_config_file(self, config_file: Optional[str] = None):
        """Save current configuration to JSON file"""
        if config_file is None:
            config_file = os.environ.get("LIFECYCLE_CONFIG_FILE", "lifecycle-config.json")
            
        try:
            # Only save non-sensitive configuration that should persist
            persist_config = {
                'github_project_id': self._config.get('github_project_id'),
                'github_project_type': self._config.get('github_project_type'),
                'status_mappings': self._config.get('status_mappings')
            }
            
            # Remove None values
            persist_config = {k: v for k, v in persist_config.items() if v is not None}
            
            config_path = Path(config_file)
            with open(config_path, 'w') as f:
                json.dump(persist_config, f, indent=2)
                
        except Exception as e:
            print(f"Warning: Could not save config file {config_file}: {e}")
    
    def validate_github_project_config(self) -> Tuple[bool, List[str]]:
        """Validate GitHub project configuration"""
        errors = []
        
        project_id = self.get_github_project_id()
        project_type = self.get_github_project_type()
        
        if project_id:
            # Basic validation of project ID format
            if project_type == "v2":
                # V2 project IDs are typically longer alphanumeric strings
                if not isinstance(project_id, str) or len(project_id) < 10:
                    errors.append("GitHub Project V2 ID appears invalid (should be long alphanumeric string)")
            elif project_type == "v1":
                # V1 project IDs are numeric
                try:
                    int(project_id)
                except ValueError:
                    errors.append("GitHub Project V1 ID must be numeric")
        
        return len(errors) == 0, errors


# Global configuration instance
config = Config()