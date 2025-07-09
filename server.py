#!/usr/bin/env python3
"""
Direct runnable MCP server for lifecycle management.
Run with: uv run server.py
"""

import sys
from pathlib import Path

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import and run the main server
from lifecycle_mcp.server import main

if __name__ == "__main__":
    main()