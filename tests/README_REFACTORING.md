# Test Refactoring Guide

## Refactoring test_task_handler.py

The original `test_task_handler.py` has 665 lines with significant duplication. Here's how to refactor it:

### 1. Use Parametrization for Similar Tests

**Before (multiple similar test methods):**
```python
async def test_create_task_blocks_draft_requirement(self, ...):
    # 20 lines of setup and assertions for Draft status

async def test_create_task_blocks_under_review_requirement(self, ...):
    # 20 lines of setup and assertions for Under Review status

async def test_create_task_allows_approved_requirement(self, ...):
    # 20 lines of setup and assertions for Approved status

# ... 5 more similar methods
```

**After (single parametrized test):**
```python
@pytest.mark.parametrize("req_status,should_succeed", [
    ("Draft", False),
    ("Under Review", False),
    ("Approved", True),
    # ... other statuses
])
async def test_create_task_requirement_status_validation(
    self, task_handler, req_status, should_succeed
):
    # Single implementation handles all cases
```

### 2. Extract Common Fixtures

**Before (repeated in many tests):**
```python
# This pattern repeated 20+ times:
await requirement_handler._create_requirement(**sample_requirement_data)
await requirement_handler._update_requirement_status(
    requirement_id="REQ-0001-FUNC-00",
    new_status="Under Review"
)
await requirement_handler._update_requirement_status(
    requirement_id="REQ-0001-FUNC-00",
    new_status="Approved"
)
```

**After (fixture):**
```python
@pytest.fixture
async def approved_requirement(self, requirement_handler, sample_requirement_data):
    """Create and approve a requirement for task creation"""
    await requirement_handler._create_requirement(**sample_requirement_data)
    # ... status transitions
    return "REQ-0001-FUNC-00"
```

### 3. Combine Related Test Cases

**Before:**
- `test_query_tasks_by_status` (30 lines)
- `test_query_tasks_by_priority` (30 lines)
- `test_query_tasks_by_assignee` (30 lines)
- `test_query_tasks_by_requirement_id` (30 lines)

**After:**
```python
@pytest.mark.parametrize("filter_type,filter_value,expected_count", [
    ("status", "Complete", 1),
    ("priority", "P1", 2),
    ("assignee", "Alice", 2),
    ("requirement_id", "REQ-0001-FUNC-00", 3),
])
async def test_query_tasks_with_filters(self, filter_type, filter_value, expected_count):
    # Single implementation for all query types
```

## Benefits of Refactoring

1. **Reduced Lines:** 665 → ~300 lines (55% reduction)
2. **Better Maintainability:** Changes to test logic only need to be made once
3. **Clearer Test Intent:** Parametrization makes test cases more explicit
4. **Faster Test Development:** New test cases can be added as parameters
5. **DRY Principle:** No duplicated setup code

## Applying to Other Test Files

Similar patterns can be applied to:

### test_requirement_handler.py
- Status transition tests (7 methods → 1 parametrized)
- Query tests with different filters
- Validation tests for different requirement types

### test_database_manager.py
- Insert/update operations with different data types
- Query operations with various filters
- Transaction success/failure scenarios

## Next Steps

1. Run both test files to ensure coverage is maintained:
   ```bash
   pytest tests/test_task_handler.py -v
   pytest tests/test_task_handler_refactored.py -v
   ```

2. Compare coverage:
   ```bash
   pytest tests/test_task_handler.py --cov=lifecycle_mcp.handlers.task_handler
   pytest tests/test_task_handler_refactored.py --cov=lifecycle_mcp.handlers.task_handler
   ```

3. Once validated, replace the original with the refactored version

4. Apply similar refactoring to other test files with duplication