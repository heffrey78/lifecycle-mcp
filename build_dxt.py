#!/usr/bin/env python3
"""
Build script to create a DXT (Desktop Extension) package from the main source code.
This eliminates the need for duplicate code in lifecycle-mcp-extension directory.
"""

import os
import shutil
import zipfile
import json
import subprocess
import sys
from pathlib import Path

def create_dxt_manifest():
    """Create the manifest.json for the DXT package"""
    manifest = {
        "dxt_version": "0.1",
        "name": "lifecycle-mcp",
        "version": "1.0.0",
        "description": "Software lifecycle management MCP server for tracking requirements, tasks, and architecture decisions",
        "author": {
            "name": "Jeff Wikstrom"
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
        "license": "MIT",
        "homepage": "https://github.com/justinlevi/lifecycle-mcp",
        "repository": {
            "type": "git",
            "url": "https://github.com/justinlevi/lifecycle-mcp.git"
        },
        "keywords": ["mcp", "lifecycle", "requirements", "tasks", "architecture", "project-management"],
        "tools": [
            "create_requirement",
            "update_requirement_status",
            "query_requirements",
            "get_requirement_details",
            "trace_requirement",
            "create_task",
            "update_task_status",
            "query_tasks",
            "get_task_details",
            "sync_task_from_github",
            "bulk_sync_github_tasks",
            "create_architecture_decision",
            "update_architecture_status",
            "query_architecture_decisions",
            "get_architecture_details",
            "add_architecture_review",
            "get_project_status",
            "start_requirement_interview",
            "continue_requirement_interview",
            "start_architectural_conversation",
            "continue_architectural_conversation",
            "export_project_documentation",
            "create_architectural_diagrams"
        ]
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
    
    # Create manifest.json
    manifest_path = build_dir / "manifest.json"
    print("Creating manifest.json...")
    with open(manifest_path, "w") as f:
        json.dump(create_dxt_manifest(), f, indent=2)
    
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
    dxt_filename = "lifecycle-mcp-1.0.0.dxt"
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

if __name__ == "__main__":
    try:
        build_dxt()
    except Exception as e:
        print(f"❌ Error building DXT: {e}")
        sys.exit(1)