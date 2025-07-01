#!/usr/bin/env python3
"""
Installation script for lifecycle-mcp extension.
This ensures the package is properly installed in the user's environment.
"""

import subprocess
import sys
import os

def install_package():
    """Install the lifecycle-mcp package in development mode."""
    try:
        # Install the package in development mode
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", "."])
        print("✓ lifecycle-mcp package installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install package: {e}")
        sys.exit(1)

if __name__ == "__main__":
    install_package()