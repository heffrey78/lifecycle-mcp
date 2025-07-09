#!/usr/bin/env python3
"""
Build script to create a DXT (Desktop Extension) package from the main source code.
Dynamically discovers tools from handler definitions to avoid tight coupling.
"""

import os
import shutil
import zipfile
import json
import sys
import importlib.util
from pathlib import Path
from typing import List, Dict, Any

def discover_tools_from_handlers() -> List[Dict[str, str]]:
    """
    Dynamically discover tools by loading handler modules and extracting their tool definitions.
    This eliminates the need to hardcode tools in the build script.
    """
    tools = []
    
    # Handler modules to inspect (excluding base_handler)
    handler_modules = [
        'requirement_handler',
        'task_handler',
        'architecture_handler',
        'interview_handler',
        'export_handler',
        'status_handler'
    ]
    
    # Add src directory to Python path temporarily
    src_path = Path("src").absolute()
    sys.path.insert(0, str(src_path))
    
    try:
        # Import lifecycle_mcp as a package to set up proper module structure
        import lifecycle_mcp
        
        # Mock the dependencies to avoid initialization issues
        class MockDatabaseManager:
            pass
        
        # Set up the mocks in the lifecycle_mcp namespace
        sys.modules['lifecycle_mcp.database_manager'] = type(sys)('mock_db')
        sys.modules['lifecycle_mcp.database_manager'].DatabaseManager = MockDatabaseManager
        
        for handler_name in handler_modules:
            try:
                # Import handler using proper module path
                module_name = f"lifecycle_mcp.handlers.{handler_name}"
                handler_module = importlib.import_module(module_name)
                
                # Find the handler class (should be named like RequirementHandler, TaskHandler, etc.)
                handler_class_name = ''.join(word.capitalize() for word in handler_name.split('_'))
                handler_class = getattr(handler_module, handler_class_name, None)
                
                if handler_class:
                    # Create instance with mock database manager
                    # Note: Some handlers might require additional parameters
                    handler_instance = None
                    
                    try:
                        # Try with just db_manager
                        handler_instance = handler_class(MockDatabaseManager())
                    except TypeError:
                        try:
                            # Try with db_manager and None for mcp_client
                            handler_instance = handler_class(MockDatabaseManager(), None)
                        except TypeError:
                            # Special case for InterviewHandler which needs requirement_handler
                            if handler_name == 'interview_handler':
                                # Create a mock requirement handler
                                mock_req_handler = type('MockReqHandler', (), {'__init__': lambda s, *a: None})()
                                handler_instance = handler_class(MockDatabaseManager(), mock_req_handler)
                            else:
                                print(f"Warning: Could not instantiate {handler_class_name}, skipping...")
                                continue
                    
                    # Get tool definitions
                    if handler_instance and hasattr(handler_instance, 'get_tool_definitions'):
                        tool_defs = handler_instance.get_tool_definitions()
                        
                        # Extract just name and description for manifest
                        for tool_def in tool_defs:
                            tools.append({
                                "name": tool_def.get("name"),
                                "description": tool_def.get("description")
                            })
                    
            except Exception as e:
                print(f"Warning: Could not process {handler_name}: {e}")
                # Continue with other handlers
    
    finally:
        # Clean up: remove from path and modules
        sys.path.pop(0)
        # Remove mock modules
        for key in list(sys.modules.keys()):
            if key.startswith('lifecycle_mcp'):
                del sys.modules[key]
    
    return tools

def get_project_metadata() -> Dict[str, Any]:
    """Extract project metadata from pyproject.toml if available."""
    metadata = {
        "version": "1.0.0",
        "description": "Software lifecycle management MCP server for tracking requirements, tasks, and architecture decisions",
        "author": "Jeff Wikstrom",
        "license": "MIT",
        "homepage": "https://github.com/justinlevi/lifecycle-mcp",
        "repository": "https://github.com/justinlevi/lifecycle-mcp.git"
    }
    
    # Try to read from pyproject.toml if available
    try:
        import tomllib
        with open("pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)
            
        project = pyproject.get("project", {})
        metadata["version"] = project.get("version", metadata["version"])
        metadata["description"] = project.get("description", metadata["description"])
        
        # Extract author from authors list
        authors = project.get("authors", [])
        if authors and isinstance(authors[0], dict):
            metadata["author"] = authors[0].get("name", metadata["author"])
            
        # Extract URLs
        urls = project.get("urls", {})
        metadata["homepage"] = urls.get("homepage", metadata["homepage"])
        metadata["repository"] = urls.get("repository", metadata["repository"])
        
    except Exception as e:
        print(f"Note: Could not read pyproject.toml, using defaults: {e}")
    
    return metadata

def create_dxt_manifest() -> Dict[str, Any]:
    """Create the manifest.json for the DXT package with dynamically discovered tools."""
    metadata = get_project_metadata()
    
    # Discover tools dynamically
    print("Discovering tools from handler definitions...")
    tools = discover_tools_from_handlers()
    print(f"Found {len(tools)} tools")
    
    manifest = {
        "dxt_version": "0.1",
        "name": "lifecycle-mcp",
        "version": metadata["version"],
        "description": metadata["description"],
        "author": {
            "name": metadata["author"]
        },
        "server": {
            "type": "python",
            "entry_point": "server.py",
            "install_script": "setup.py",
            "mcp_config": {
                "command": "python",
                "args": [
                    "-m",
                    "lifecycle_mcp.server"
                ],
                "env": {
                    "LIFECYCLE_DB": "${__dirname}/lifecycle.db"
                }
            }
        },
        "license": metadata["license"],
        "homepage": metadata["homepage"],
        "repository": {
            "type": "git",
            "url": metadata["repository"]
        },
        "keywords": ["mcp", "lifecycle", "requirements", "tasks", "architecture", "project-management"],
        "tools": tools
    }
    
    return manifest

def build_dxt():
    """Build the DXT package"""
    print("Building DXT package for lifecycle-mcp...")
    
    # Create build directory
    build_dir = Path("build/dxt")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    
    # Copy source files
    src_dir = Path("src/lifecycle_mcp")
    dest_dir = build_dir / "lifecycle_mcp"
    print(f"Copying source from {src_dir} to {dest_dir}...")
    shutil.copytree(src_dir, dest_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    
    # Copy server.py to the root of the package
    if Path("server.py").exists():
        shutil.copy("server.py", build_dir / "server.py")
    
    # Create manifest.json
    manifest_path = build_dir / "manifest.json"
    print("Creating manifest.json...")
    try:
        manifest = create_dxt_manifest()
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        print(f"Error creating manifest: {e}")
        print("Falling back to minimal manifest...")
        # Create a minimal manifest as fallback
        minimal_manifest = {
            "dxt_version": "0.1",
            "name": "lifecycle-mcp",
            "version": "1.0.0",
            "description": "Software lifecycle management MCP server",
            "server": {
                "type": "python",
                "entry_point": "server.py",
                "install_script": "setup.py"
            },
            "tools": []  # Empty tools list as fallback
        }
        with open(manifest_path, "w") as f:
            json.dump(minimal_manifest, f, indent=2)
    
    # Create a minimal setup.py for the DXT
    setup_content = """from setuptools import setup, find_packages

setup(
    name="lifecycle-mcp",
    version="1.0.0",
    packages=find_packages(),
    install_requires=["mcp>=1.0.0"],
    python_requires=">=3.10",
    package_data={
        "lifecycle_mcp": ["*.sql"]
    }
)
"""
    with open(build_dir / "setup.py", "w") as f:
        f.write(setup_content)
    
    # Copy README
    if Path("README.md").exists():
        shutil.copy("README.md", build_dir / "README.md")
    
    # Copy pyproject.toml
    if Path("pyproject.toml").exists():
        shutil.copy("pyproject.toml", build_dir / "pyproject.toml")
    
    # Create requirements.txt
    with open(build_dir / "requirements.txt", "w") as f:
        f.write("mcp>=1.0.0\n")
    
    # Create the DXT zip file
    # Extract version from metadata for filename
    metadata = get_project_metadata()
    dxt_filename = f"lifecycle-mcp-{metadata['version']}.dxt"
    dxt_path = Path(dxt_filename)
    
    print(f"Creating {dxt_filename}...")
    with zipfile.ZipFile(dxt_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Walk through build directory and add all files
        for root, dirs, files in os.walk(build_dir):
            for file in files:
                file_path = Path(root) / file
                arcname = file_path.relative_to(build_dir)
                zf.write(file_path, arcname)
    
    # Clean up build directory
    shutil.rmtree(build_dir)
    
    print(f"✅ DXT package created: {dxt_path}")
    print(f"   Size: {dxt_path.stat().st_size / 1024:.1f} KB")
    
    # Verify the package
    print("\nVerifying package contents:")
    with zipfile.ZipFile(dxt_path, "r") as zf:
        files = zf.namelist()
        print(f"   Files in package: {len(files)}")
        for f in sorted(files)[:10]:
            print(f"   - {f}")
        if len(files) > 10:
            print(f"   ... and {len(files) - 10} more files")
        
        # Show tools discovered
        try:
            manifest_data = json.loads(zf.read("manifest.json"))
            tools = manifest_data.get("tools", [])
            print(f"\n   Tools in manifest: {len(tools)}")
            for i, tool in enumerate(tools[:5]):
                print(f"   - {tool['name']}: {tool['description']}")
            if len(tools) > 5:
                print(f"   ... and {len(tools) - 5} more tools")
        except Exception as e:
            print(f"   Could not read tools from manifest: {e}")

if __name__ == "__main__":
    try:
        build_dxt()
    except Exception as e:
        print(f"❌ Error building DXT: {e}")
        sys.exit(1)