"""Curated schema fields round-trip through create, update, details and export (roadmap R6b, TASK-0025)."""

from .test_delete_and_history import DECISION, approve
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ, TASK, ADR = "REQ-0001-FUNC-00", "TASK-0001-00-00", "ADR-0001"

# field -> (section heading, value)
REQUIREMENT_FIELDS = {
    "nonfunctional_requirements": ("Non-Functional Requirements", "p95 search under 50 ms"),
    "technical_constraints": ("Technical Constraints", "SQLite only"),
    "business_rules": ("Business Rules", "Deleted notes are never indexed"),
    "validation_metrics": ("Validation Metrics", "Search success rate above 90%"),
    "out_of_scope": ("Out of Scope", "Mobile apps"),
}
TASK_FIELDS = {
    "implementation_plan": ("Implementation Plan", "Add an FTS5 table"),
    "test_plan": ("Test Plan", "Search 10k notes"),
    "definition_of_done": ("Definition of Done", "Benchmark recorded"),
}
DECISION_LISTS = {
    "validation_criteria": ("Validation Criteria", "p95 under 50 ms at 10k notes"),
    "risk_assessment": ("Risk Assessment", "Index size: likely, medium impact; prune trigrams"),
}


async def ok(server, name: str, arguments: dict) -> str:
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return text_of(result)


async def export(server, tmp_path, kind: str) -> str:
    await ok(server, "export_project_documentation", {"project_name": "curated", "output_directory": str(tmp_path)})
    return (tmp_path / f"curated-{kind}.md").read_text(encoding="utf-8")


def as_lists(fields: dict, suffix: str = "") -> dict:
    return {field: [value + suffix] for field, (_, value) in fields.items()}


def assert_sections(text: str, fields: dict, template: str, suffix: str = "") -> None:
    for heading, value in fields.values():
        assert template.format(heading=heading, value=value + suffix) in text, heading


async def test_requirement_fields_round_trip(mcp_server, tmp_path):  # noqa: F811
    await ok(mcp_server, "create_requirement", {**REQUIREMENT, **as_lists(REQUIREMENT_FIELDS)})

    details = await ok(mcp_server, "get_details", {"entity_id": REQ})
    assert_sections(details, REQUIREMENT_FIELDS, "### {heading}\n- {value}\n")
    assert_sections(
        await export(mcp_server, tmp_path, "requirements"), REQUIREMENT_FIELDS, "**{heading}**:\n- {value}\n"
    )

    await ok(mcp_server, "update_requirement", {"requirement_id": REQ, **as_lists(REQUIREMENT_FIELDS, " (revised)")})

    details = await ok(mcp_server, "get_details", {"entity_id": REQ})
    assert_sections(details, REQUIREMENT_FIELDS, "### {heading}\n- {value}\n", " (revised)")
    assert "- Mobile apps\n" not in details
    exported = await export(mcp_server, tmp_path, "requirements")
    assert_sections(exported, REQUIREMENT_FIELDS, "**{heading}**:\n- {value}\n", " (revised)")


async def test_task_fields_round_trip(mcp_server, tmp_path):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    await approve(mcp_server, REQ)
    task = {"requirement_ids": [REQ], "title": "Build index", "priority": "P1", **as_lists(TASK_FIELDS)}
    await ok(mcp_server, "create_task", task)

    details = await ok(mcp_server, "get_details", {"entity_id": TASK})
    assert_sections(details, TASK_FIELDS, "## {heading}\n- {value}\n")
    assert_sections(await export(mcp_server, tmp_path, "tasks"), TASK_FIELDS, "**{heading}**:\n- {value}\n")

    await ok(mcp_server, "update_task", {"task_id": TASK, **as_lists(TASK_FIELDS, " (revised)")})

    details = await ok(mcp_server, "get_details", {"entity_id": TASK})
    assert_sections(details, TASK_FIELDS, "## {heading}\n- {value}\n", " (revised)")
    assert "- Benchmark recorded\n" not in details
    assert_sections(
        await export(mcp_server, tmp_path, "tasks"), TASK_FIELDS, "**{heading}**:\n- {value}\n", " (revised)"
    )


async def test_decision_fields_round_trip(mcp_server, tmp_path):  # noqa: F811
    await ok(mcp_server, "create_requirement", REQUIREMENT)
    decision = {
        **DECISION,
        **as_lists(DECISION_LISTS),
        "deciders": ["Owner", "Search lead"],
        "implementation_notes": "Build the index in a migration",
    }
    await ok(mcp_server, "create_architecture_decision", decision)

    details = await ok(mcp_server, "get_details", {"entity_id": ADR})
    assert "- **Deciders**: Owner, Search lead" in details
    assert "## Implementation Notes\nBuild the index in a migration\n" in details
    assert_sections(details, DECISION_LISTS, "## {heading}\n- {value}\n")
    exported = await export(mcp_server, tmp_path, "architecture")
    assert "- **Deciders**: Owner, Search lead" in exported
    assert "### Implementation Notes\nBuild the index in a migration\n" in exported
    assert_sections(exported, DECISION_LISTS, "### {heading}\n- {value}\n")

    revised = {
        "architecture_id": ADR,
        **as_lists(DECISION_LISTS, " (revised)"),
        "deciders": ["Owner"],
        "implementation_notes": "Build the index lazily",
    }
    await ok(mcp_server, "update_architecture", revised)

    details = await ok(mcp_server, "get_details", {"entity_id": ADR})
    assert "- **Deciders**: Owner\n" in details and "## Implementation Notes\nBuild the index lazily\n" in details
    assert_sections(details, DECISION_LISTS, "## {heading}\n- {value}\n", " (revised)")
    exported = await export(mcp_server, tmp_path, "architecture")
    assert "### Implementation Notes\nBuild the index lazily\n" in exported
    assert_sections(exported, DECISION_LISTS, "### {heading}\n- {value}\n", " (revised)")
