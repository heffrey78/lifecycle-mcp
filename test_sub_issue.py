#!/usr/bin/env python3
import asyncio
import os
from src.lifecycle_mcp.github_utils import GitHubUtils

async def test_sub_issue_relationship():
    print('Testing sub-issue relationship creation...')
    
    # Test creating a sub-issue relationship (use existing issues)
    success, error_msg = await GitHubUtils.create_sub_issue_relationship('40', '41')
    
    if success:
        print('✅ Sub-issue relationship created successfully')
        
        # Test removing the relationship
        print('Testing sub-issue relationship removal...')
        success_remove, error_remove = await GitHubUtils.remove_sub_issue_relationship('40', '41')
        
        if success_remove:
            print('✅ Sub-issue relationship removed successfully')
        else:
            print(f'❌ Failed to remove sub-issue relationship: {error_remove}')
    else:
        print(f'❌ Failed to create sub-issue relationship: {error_msg}')
        
        # Check if it's a feature availability issue
        if 'sub_issues' in (error_msg or '').lower() or 'not available' in (error_msg or '').lower():
            print('ℹ️  This is expected if GitHub sub-issues feature is not available in this instance')
    
    return success

if __name__ == "__main__":
    # Set environment variables for GitHub integration
    os.environ['GITHUB_INTEGRATION_ENABLED'] = 'true'
    os.environ['GITHUB_REPO'] = 'heffrey78/lifecycle-mcp'
    
    # Try to get GitHub token
    try:
        import subprocess
        result = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True)
        if result.returncode == 0:
            os.environ['GITHUB_TOKEN'] = result.stdout.strip()
    except:
        pass
    
    result = asyncio.run(test_sub_issue_relationship())