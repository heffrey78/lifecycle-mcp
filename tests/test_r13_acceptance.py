"""R13 acceptance: each acceptance criterion of REQ-0008-FUNC-00 (diagrams that show structure) through the MCP
server layer, one test per criterion in the requirement's order (TASK-0063).
"""

from .test_diagrams import diagram, node, project
from .test_next_tasks import add_task
from .test_tool_results import REQUIREMENT, call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)


async def test_1_the_full_project_diagram_links_every_non_deprecated_record(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)

    result, content = await diagram(mcp_server, tmp_path)

    assert f"{node(ids['requirement'])} -->|implements| {node(ids['task'])}" in content
    assert f"{node(ids['requirement'])} -->|addresses| {node(ids['adr'])}" in content
    assert ids["deprecated"] not in content
    assert "left out: 1 deprecated requirements" in text_of(result)


async def test_2_a_task_implementing_a_decision_and_a_superseded_decision_are_drawn(mcp_server, tmp_path):  # noqa: F811
    ids = await project(mcp_server)

    _, content = await diagram(mcp_server, tmp_path)

    assert f"{node(ids['task'])} -->|implements| {node(ids['newer'])}" in content
    assert f"{node(ids['newer'])} -->|supersedes| {node(ids['adr'])}" in content


async def test_3_a_limit_says_how_much_it_drew_and_how_much_it_left_out(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    for number in range(3):
        await add_task(mcp_server, ids["requirement"], f"Task {number}", "P2")

    limited, _ = await diagram(mcp_server, tmp_path, limit=1)
    complete, _ = await diagram(mcp_server, tmp_path)

    assert "1 tasks" in text_of(limited) and "3 tasks over the limit" in text_of(limited)
    assert "4 tasks" in text_of(complete) and "over the limit" not in text_of(complete)


async def test_4_two_renders_of_a_type_leave_one_file(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)

    await diagram(mcp_server, tmp_path)
    await diagram(mcp_server, tmp_path, diagram_type="tasks")
    await diagram(mcp_server, tmp_path, diagram_type="tasks")

    assert [path.name for path in sorted(tmp_path.iterdir())] == ["full_project-diagram.mmd", "tasks-diagram.mmd"]


async def test_5_directory_structure_is_refused_and_the_real_types_are_named(mcp_server, tmp_path):  # noqa: F811
    result = await call(
        mcp_server,
        "create_architectural_diagrams",
        {"diagram_type": "directory_structure", "output_path": str(tmp_path)},
    )

    assert result.isError is True
    message = text_of(result)
    assert "full_project" in message and "dependencies" in message


async def test_6_a_title_with_quotes_and_brackets_still_renders(mcp_server, tmp_path):  # noqa: F811
    awkward = await call(mcp_server, "create_requirement", {**REQUIREMENT, "title": 'Search "notes" [beta]'})
    record_id = awkward.structuredContent["id"]

    _, content = await diagram(mcp_server, tmp_path, diagram_type="requirements")

    assert f'{node(record_id)}["{record_id}<br/>Search #quot;notes#quot; (beta)"]' in content
    assert '"]' in content and content.count('"') % 2 == 0  # every label quote is closed
