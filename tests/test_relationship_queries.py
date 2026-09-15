"""query_relationships answers every link question (roadmap R16, TASK-0035).

It replaces get_entity_relationships (one record's links) and query_all_relationships (every link for a graph).
"""

import json
import re

from .test_delete_and_history import DECISION, approve
from .test_tool_results import REQUIREMENT, call, mcp_server, text_of  # noqa: F401 (mcp_server is a fixture)

REQ_1, REQ_2 = "REQ-0001-FUNC-00", "REQ-0002-FUNC-00"
TASK_1, TASK_2 = "TASK-0001-00-00", "TASK-0002-00-00"
ADR = "ADR-0001"


async def ok(server, name: str, arguments: dict) -> str:
    result = await call(server, name, arguments)
    assert not result.isError, text_of(result)
    return text_of(result)


async def linked_project(server) -> None:
    """REQ_1 implements TASK_1 and TASK_2 and addresses ADR; TASK_2 depends on TASK_1; REQ_2 refines REQ_1."""
    await ok(server, "create_requirement", REQUIREMENT)
    await ok(server, "create_requirement", {**REQUIREMENT, "title": "Tagging"})
    await approve(server, REQ_1)
    await ok(server, "create_task", {"requirement_ids": [REQ_1], "title": "Build index", "priority": "P1"})
    await ok(server, "create_task", {"requirement_ids": [REQ_1], "title": "Rank results", "priority": "P1"})
    await ok(server, "create_relationship", {"source_id": TASK_2, "target_id": TASK_1, "relationship_type": "depends"})
    await ok(server, "create_relationship", {"source_id": REQ_2, "target_id": REQ_1, "relationship_type": "refines"})
    await ok(server, "create_architecture_decision", DECISION)


def graph(text: str) -> set[tuple[str, str, str]]:
    links = json.loads(re.search(r"```json\n(.*)\n```", text, re.S).group(1))
    return {(link["source"], link["target"], link["type"]) for link in links}


async def test_one_records_links_in_both_directions(mcp_server):  # noqa: F811
    await linked_project(mcp_server)

    text = await ok(mcp_server, "query_relationships", {"entity_id": TASK_1})

    assert f"Entity {TASK_1} has 2 relationship(s)" in text
    assert f"- ← **Searchable notes** ({REQ_1})" in text
    assert f"- ← **Rank results** ({TASK_2})" in text


async def test_direction_and_type_narrow_one_records_links(mcp_server):  # noqa: F811
    await linked_project(mcp_server)

    outgoing = await ok(mcp_server, "query_relationships", {"entity_id": TASK_2, "direction": "outgoing"})
    assert f"Entity {TASK_2} has 1 relationship(s)" in outgoing and f"- → **Build index** ({TASK_1})" in outgoing

    incoming = await ok(mcp_server, "query_relationships", {"entity_id": TASK_2, "direction": "incoming"})
    assert f"Entity {TASK_2} has 1 relationship(s)" in incoming and f"- ← **Searchable notes** ({REQ_1})" in incoming

    assert f"Entity {REQ_1} has 4 relationship(s)" in await ok(mcp_server, "query_relationships", {"entity_id": REQ_1})
    implements = await ok(mcp_server, "query_relationships", {"entity_id": REQ_1, "relationship_type": "implements"})
    assert f"Entity {REQ_1} has 2 relationship(s)" in implements
    refined_by = await ok(mcp_server, "query_relationships", {"entity_id": REQ_1, "direction": "incoming"})
    assert f"Entity {REQ_1} has 1 relationship(s)" in refined_by and f"- ← **Tagging** ({REQ_2})" in refined_by


async def test_without_entity_id_every_link_is_returned_as_json_and_can_be_limited_by_type(mcp_server):  # noqa: F811
    await linked_project(mcp_server)

    everything = graph(await ok(mcp_server, "query_relationships", {}))
    assert everything == {
        (REQ_1, TASK_1, "implements"),
        (REQ_1, TASK_2, "implements"),
        (TASK_2, TASK_1, "depends"),
        (REQ_2, REQ_1, "refines"),
        (REQ_1, ADR, "addresses"),
    }

    tasks_only = graph(await ok(mcp_server, "query_relationships", {"entity_types": ["task"]}))
    assert tasks_only == {(TASK_2, TASK_1, "depends")}

    design = await ok(mcp_server, "query_relationships", {"entity_types": ["requirement", "architecture"]})
    assert graph(design) == {(REQ_2, REQ_1, "refines"), (REQ_1, ADR, "addresses")}


async def test_direction_without_entity_id_and_malformed_ids_are_refused(mcp_server):  # noqa: F811
    await linked_project(mcp_server)

    no_entity = await call(mcp_server, "query_relationships", {"direction": "incoming"})
    assert no_entity.isError and "direction needs entity_id" in text_of(no_entity)

    malformed = await call(mcp_server, "query_relationships", {"entity_id": "NOTE-1"})
    assert malformed.isError and "Invalid entity ID: NOTE-1" in text_of(malformed)


async def test_the_replaced_tools_are_gone(mcp_server):  # noqa: F811
    for name in ("get_entity_relationships", "query_all_relationships"):
        result = await call(mcp_server, name, {})
        assert result.isError and "Unknown tool" in text_of(result), name
