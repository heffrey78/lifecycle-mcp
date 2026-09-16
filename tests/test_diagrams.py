"""Diagrams draw the real graph from relationships (roadmap R13)."""

from .test_design_links import link, new_decision
from .test_next_tasks import add_task
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def diagram(server, tmp_path, **arguments):
    """Render a diagram into tmp_path and return (response, file content)."""
    result = await call(
        server,
        "create_architectural_diagrams",
        {"diagram_type": "full_project", "output_path": str(tmp_path), **arguments},
    )
    assert not result.isError, text_of(result)
    rendered = sorted(tmp_path.glob("*.mmd")) + sorted(tmp_path.glob("*.md"))
    return result, rendered[0].read_text(encoding="utf-8") if rendered else ""


async def project(server) -> dict[str, str]:
    """A requirement with a task, two decisions where one supersedes the other, and a deprecated requirement."""
    ids = await populate(server)
    newer = await new_decision(server, ids["requirement"])
    await link(server, ids["task"], newer, "implements")
    await link(server, newer, ids["adr"], "supersedes")
    dropped = await call(server, "create_requirement", {**REQUIREMENT, "title": "Abandoned idea"})
    deprecated = dropped.structuredContent["id"]
    await call(server, "update_requirement_status", {"requirement_id": deprecated, "new_status": "Deprecated"})
    return {**ids, "newer": newer, "deprecated": deprecated}


# --- the full project graph (TASK-0060) -----------------------------------------------------------------------


async def test_the_full_project_diagram_draws_every_link_type(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)
    node = lambda record_id: record_id.replace("-", "_")  # noqa: E731

    result, content = await diagram(mcp_server, tmp_path)

    assert f"{node(ids['requirement'])} -->|implements| {node(ids['task'])}" in content
    assert f"{node(ids['requirement'])} -->|addresses| {node(ids['adr'])}" in content
    assert f"{node(ids['task'])} -->|implements| {node(ids['newer'])}" in content
    assert f"{node(ids['newer'])} -->|supersedes| {node(ids['adr'])}" in content
    assert "1 requirements, 1 tasks, 2 decisions" in text_of(result)  # the second requirement is Deprecated


async def test_deprecated_records_are_left_out_and_counted(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)

    result, content = await diagram(mcp_server, tmp_path)

    assert ids["deprecated"] not in content
    assert "left out: 1 deprecated requirements" in text_of(result)


async def test_nothing_is_capped(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    tasks = [await add_task(mcp_server, ids["requirement"], f"Task {number}", "P2") for number in range(14)]

    _, content = await diagram(mcp_server, tmp_path)

    for task_id in tasks:
        assert task_id in content
    assert content.count("-->|implements|") == len(tasks) + 1  # every task, including the one from populate


async def test_without_relationships_only_the_nodes_are_drawn(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)

    _, content = await diagram(mcp_server, tmp_path, include_relationships=False)

    assert ids["requirement"] in content and ids["task"] in content and ids["adr"] in content
    assert "-->" not in content


# --- the per-type diagrams (TASK-0061) ------------------------------------------------------------------------


def node(record_id: str) -> str:
    return record_id.replace("-", "_")


async def test_the_architecture_diagram_shows_supersession_and_the_requirements_served(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)

    result, content = await diagram(mcp_server, tmp_path, diagram_type="architecture")

    assert f"{node(ids['newer'])} -->|supersedes| {node(ids['adr'])}" in content
    assert f"{node(ids['requirement'])} -->|addresses| {node(ids['adr'])}" in content
    assert "2 decisions" in text_of(result)


async def test_the_tasks_diagram_shows_subtasks_and_dependencies(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    child = await call(
        mcp_server,
        "create_task",
        {
            "requirement_ids": [ids["requirement"]],
            "title": "Index writer",
            "priority": "P2",
            "parent_task_id": ids["task"],
        },
    )
    subtask = child.structuredContent["id"]
    other = await add_task(mcp_server, ids["requirement"], "Ranking", "P2")
    await link(mcp_server, other, ids["task"], "depends")

    _, content = await diagram(mcp_server, tmp_path, diagram_type="tasks")

    assert f"{node(subtask)} -->|subtask of| {node(ids['task'])}" in content
    assert f"{node(other)} -->|depends on| {node(ids['task'])}" in content


async def test_the_requirements_diagram_keeps_its_grouping_and_links_requirements(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    child = await call(mcp_server, "create_requirement", {**REQUIREMENT, "title": "Ranked search"})
    refinement = child.structuredContent["id"]
    await link(mcp_server, refinement, ids["requirement"], "parent")

    _, content = await diagram(mcp_server, tmp_path, diagram_type="requirements")

    assert "FUNC[FUNC Requirements]" in content
    assert f"{node(ids['requirement'])} -->|parent of| {node(refinement)}" in content


async def test_labels_survive_quotes_and_brackets(mcp_server, tmp_path):  # noqa: F811
    awkward = await call(mcp_server, "create_requirement", {**REQUIREMENT, "title": 'Search "notes" [beta]'})
    record_id = awkward.structuredContent["id"]

    _, content = await diagram(mcp_server, tmp_path, diagram_type="requirements")

    assert f'{node(record_id)}["{record_id}<br/>Search #quot;notes#quot; (beta)"]' in content
