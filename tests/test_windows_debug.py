"""Debug test for Windows issues"""
import os
import sys
import tempfile
from pathlib import Path


def test_windows_paths():
    """Test basic path operations on Windows"""
    print(f"Platform: {sys.platform}")
    print(f"OS: {os.name}")
    
    # Test temp file creation
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    print(f"Temp path: {temp_path}")
    os.close(fd)
    os.unlink(temp_path)
    
    # Test schema path
    schema_path = Path(__file__).parent.parent / "src" / "lifecycle_mcp" / "lifecycle-schema.sql"
    print(f"Schema path: {schema_path}")
    print(f"Schema exists: {schema_path.exists()}")
    print(f"Resolved path: {schema_path.resolve()}")
    
    assert True  # Always pass to see output