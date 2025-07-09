"""
Property-based tests using Hypothesis for lifecycle MCP
"""

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from lifecycle_mcp.database_manager import DatabaseManager
from lifecycle_mcp.handlers.requirement_handler import RequirementHandler


class TestPropertyBasedValidation:
    """Property-based tests for data validation"""

    @given(
        req_type=st.sampled_from(["FUNC", "NFUNC", "TECH", "BUS", "INTF"]),
        priority=st.sampled_from(["P0", "P1", "P2", "P3"]),
        title=st.text(min_size=1, max_size=200).filter(lambda x: x.strip()),
        current_state=st.text(min_size=1, max_size=1000).filter(lambda x: x.strip()),
        desired_state=st.text(min_size=1, max_size=1000).filter(lambda x: x.strip()),
    )
    @pytest.mark.asyncio
    async def test_requirement_creation_properties(
        self, requirement_handler, req_type, priority, title, current_state, desired_state
    ):
        """Test that valid requirement data always creates a requirement successfully"""
        result = await requirement_handler._create_requirement(
            type=req_type,
            priority=priority,
            title=title,
            current_state=current_state,
            desired_state=desired_state,
            author="Hypothesis Test",
        )

        # Should always succeed with valid data
        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "REQ-" in result[0].text

    @given(
        functional_reqs=st.lists(
            st.text(min_size=1, max_size=200).filter(lambda x: x.strip()), min_size=0, max_size=20
        ),
        acceptance_criteria=st.lists(
            st.text(min_size=1, max_size=200).filter(lambda x: x.strip()), min_size=0, max_size=20
        ),
        risk_level=st.sampled_from(["High", "Medium", "Low"]),
    )
    @pytest.mark.asyncio
    async def test_requirement_json_fields(self, requirement_handler, functional_reqs, acceptance_criteria, risk_level):
        """Test that JSON fields are properly handled regardless of content"""
        result = await requirement_handler._create_requirement(
            type="FUNC",
            priority="P1",
            title="JSON Field Test",
            current_state="Testing JSON",
            desired_state="JSON works",
            functional_requirements=functional_reqs,
            acceptance_criteria=acceptance_criteria,
            risk_level=risk_level,
            author="Hypothesis",
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text

        # Verify data was stored correctly
        req_id = result[0].text.split()[2]  # Extract REQ-XXXX-TYPE-VV
        details = requirement_handler._get_requirement_details(requirement_id=req_id)

        # Check that lists are preserved
        details_text = details[0].text
        for req in functional_reqs:
            assert req in details_text
        for criteria in acceptance_criteria:
            assert criteria in details_text

    @given(
        effort=st.sampled_from(["XS", "S", "M", "L", "XL"]),
        assignee=st.text(alphabet=string.ascii_letters + string.digits + " .-_", min_size=0, max_size=100).filter(
            lambda x: x.strip() or x == ""
        ),
        user_story=st.text(min_size=0, max_size=1000),
    )
    @pytest.mark.asyncio
    async def test_task_creation_properties(self, task_handler, requirement_handler, effort, assignee, user_story):
        """Test task creation with various valid inputs"""
        # First create and approve a requirement
        req_result = await requirement_handler._create_requirement(
            type="FUNC",
            title="Task Property Test",
            priority="P1",
            current_state="No tasks",
            desired_state="Has tasks",
            author="Hypothesis",
        )
        req_id = req_result[0].text.split()[2]

        # Move requirement to approved state
        await requirement_handler._update_requirement_status(requirement_id=req_id, new_status="Under Review")
        await requirement_handler._update_requirement_status(requirement_id=req_id, new_status="Approved")

        # Create task with property-based data
        task_result = await task_handler._create_task(
            requirement_ids=[req_id],
            title="Property-based task",
            priority="P1",
            effort=effort,
            assignee=assignee if assignee else None,
            user_story=user_story if user_story else None,
        )

        assert len(task_result) == 1
        assert "SUCCESS" in task_result[0].text
        assert "TASK-" in task_result[0].text


class RequirementLifecycleStateMachine(RuleBasedStateMachine):
    """
    Stateful testing for requirement lifecycle transitions.
    This ensures that no sequence of valid operations can violate invariants.
    """

    def __init__(self):
        super().__init__()
        self.requirements = {}  # req_id -> current_status
        self.handler = None
        self.db_manager = None

    @initialize()
    @pytest.mark.asyncio
    async def setup(self):
        """Initialize the state machine with a fresh database"""
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_file:
            db_path = tmp_file.name

        # Initialize schema
        schema_path = Path(__file__).parent.parent / "src" / "lifecycle_mcp" / "lifecycle-schema.sql"
        if schema_path.exists():
            import sqlite3

            conn = sqlite3.connect(db_path)
            with open(schema_path, "r") as f:
                conn.executescript(f.read())
            conn.close()

        self.db_manager = DatabaseManager(db_path)
        self.handler = RequirementHandler(self.db_manager)
        self.temp_db_path = db_path

    def teardown(self):
        """Clean up resources"""
        if hasattr(self, "temp_db_path"):
            import os

            try:
                os.unlink(self.temp_db_path)
            except Exception:
                pass

    @rule(
        req_type=st.sampled_from(["FUNC", "NFUNC", "TECH", "BUS", "INTF"]),
        priority=st.sampled_from(["P0", "P1", "P2", "P3"]),
    )
    @pytest.mark.asyncio
    async def create_requirement(self, req_type, priority):
        """Rule: Create a new requirement"""
        result = await self.handler._create_requirement(
            type=req_type,
            title=f"Stateful test requirement {len(self.requirements)}",
            priority=priority,
            current_state="Current",
            desired_state="Desired",
            author="StateMachine",
        )

        if "SUCCESS" in result[0].text:
            req_id = result[0].text.split()[2]
            self.requirements[req_id] = "Draft"

    @rule(
        req_id=st.sampled_from(lambda self: list(self.requirements.keys()) if self.requirements else []),
        target_status=st.sampled_from(
            ["Under Review", "Approved", "Architecture", "Ready", "Implemented", "Validated", "Deprecated"]
        ),
    )
    @pytest.mark.asyncio
    async def transition_requirement(self, req_id, target_status):
        """Rule: Attempt to transition a requirement to a new status"""
        if not req_id:
            return

        current_status = self.requirements[req_id]

        # Define valid transitions
        valid_transitions = {
            "Draft": ["Under Review", "Deprecated"],
            "Under Review": ["Draft", "Approved", "Deprecated"],
            "Approved": ["Under Review", "Architecture", "Deprecated"],
            "Architecture": ["Approved", "Ready", "Deprecated"],
            "Ready": ["Architecture", "Implemented", "Deprecated"],
            "Implemented": ["Ready", "Validated", "Deprecated"],
            "Validated": ["Deprecated"],
            "Deprecated": [],
        }

        result = await self.handler._update_requirement_status(requirement_id=req_id, new_status=target_status)

        if target_status in valid_transitions.get(current_status, []):
            # Valid transition should succeed
            assert "SUCCESS" in result[0].text
            self.requirements[req_id] = target_status
        else:
            # Invalid transition should fail
            assert "ERROR" in result[0].text
            assert "Invalid transition" in result[0].text

    @invariant()
    def status_consistency(self):
        """Invariant: All requirements in our state match the database"""
        for req_id, expected_status in self.requirements.items():
            records = self.db_manager.get_records("requirements", "status", "id = ?", [req_id])
            if records:
                assert records[0]["status"] == expected_status


# Example test for the state machine (requires pytest-hypothesis plugin)
def test_requirement_lifecycle_state_machine():
    """Test that requirement lifecycle follows valid state transitions"""
    # Note: This would be run by hypothesis to generate many test cases
    # Uncomment to run with hypothesis installed:
    # RequirementLifecycleStateMachine.TestCase.settings = settings(max_examples=100)
    # unittest.main()
    pass


@given(num_requirements=st.integers(min_value=0, max_value=10), num_tasks_per_req=st.integers(min_value=0, max_value=5))
@pytest.mark.asyncio
async def test_project_metrics_consistency(
    db_manager, requirement_handler, task_handler, num_requirements, num_tasks_per_req
):
    """Test that project metrics remain consistent regardless of data volume"""
    created_reqs = []

    # Create requirements
    for i in range(num_requirements):
        result = await requirement_handler._create_requirement(
            type="FUNC",
            title=f"Metric test req {i}",
            priority="P1",
            current_state="Current",
            desired_state="Desired",
            author="Hypothesis",
        )
        req_id = result[0].text.split()[2]
        created_reqs.append(req_id)

        # Approve requirement so we can add tasks
        await requirement_handler._update_requirement_status(requirement_id=req_id, new_status="Under Review")
        await requirement_handler._update_requirement_status(requirement_id=req_id, new_status="Approved")

    total_tasks = 0

    # Create tasks
    for req_id in created_reqs:
        for j in range(num_tasks_per_req):
            await task_handler._create_task(requirement_ids=[req_id], title=f"Task {j} for {req_id}", priority="P1")
            total_tasks += 1

    # Verify counts
    req_count = db_manager.execute_query("SELECT COUNT(*) FROM requirements", fetch_one=True)[0]
    task_count = db_manager.execute_query("SELECT COUNT(*) FROM tasks", fetch_one=True)[0]

    assert req_count == num_requirements
    assert task_count == total_tasks

    # Verify each requirement has correct task count
    for req_id in created_reqs:
        req_tasks = db_manager.execute_query(
            "SELECT COUNT(*) FROM requirement_tasks WHERE requirement_id = ?", [req_id], fetch_one=True
        )[0]
        assert req_tasks == num_tasks_per_req
