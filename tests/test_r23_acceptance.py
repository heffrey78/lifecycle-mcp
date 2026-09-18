"""R23 acceptance: each acceptance criterion of REQ-0004-INTF-00 (get_details shows what the record actually has).

Three fields did not survive the rendering. An ADR's authors printed the stored JSON while deciders, one line above,
printed a readable list (F-41). Consequences interpolated each value, so a value holding a list came out as a Python
repr in details and in export alike. And requirement details listed only implementing tasks: R9 gave architecture and
task details their link sections and left the requirement end out, so a requirement with a decision against it and no
tasks read as though nothing linked to it - the silent failure of the three, because nothing in the output told the
reader which case they were looking at.
"""

import os

from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)

AUTHORS = ["Ada Lovelace", "Alan Turing"]
CONSEQUENCES = {"positive": ["Search is fast", "Index stays small"], "negative": ["One more file to ship"]}


async def details(server, entity_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": entity_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def decision(server, requirement_id: str, **extra) -> str:
    result = await call(
        server,
        "create_architecture_decision",
        {
            "requirement_ids": [requirement_id],
            "title": "Use trigrams",
            "context": "Prefix search misses infixes",
            "decision": "Index trigrams",
            **extra,
        },
    )
    assert not result.isError, text_of(result)
    return result.structuredContent["id"]


async def exported_architecture(server, tmp_path) -> str:
    result = await call(
        server, "export_project_documentation", {"project_name": "R23", "output_directory": str(tmp_path)}
    )
    assert not result.isError, text_of(result)
    name = next(f for f in os.listdir(tmp_path) if "architecture" in f.lower())
    with open(os.path.join(tmp_path, name), encoding="utf-8") as handle:
        return handle.read()


async def test_1_authors_read_as_a_list_not_as_stored_json(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    adr = await decision(mcp_server, ids["requirement"], authors=AUTHORS)

    report = await details(mcp_server, adr)

    assert "- **Authors**: Ada Lovelace, Alan Turing\n" in report
    assert '["Ada Lovelace"' not in report and "['Ada Lovelace'" not in report


async def test_1b_an_adr_without_authors_says_so(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    report = await details(mcp_server, ids["adr"])

    # create_architecture_decision defaults the author, so the field is never blank in practice; the guard is that
    # whatever is stored renders as text.
    assert "- **Authors**: " in report
    assert "[" not in report.split("- **Authors**: ")[1].split("\n")[0]


async def test_2_list_valued_consequences_render_as_lines_in_details_and_export(mcp_server, tmp_path):  # noqa: F811
    ids = await populate(mcp_server)
    adr = await decision(mcp_server, ids["requirement"], consequences=CONSEQUENCES)

    report = await details(mcp_server, adr)
    exported = await exported_architecture(mcp_server, tmp_path)

    for text in (report, exported):
        assert "**Positive**:\n- Search is fast\n- Index stays small\n" in text
        assert "**Negative**:\n- One more file to ship\n" in text
        assert "['Search is fast'" not in text and '["Search is fast"' not in text


async def test_2b_string_valued_consequences_are_unchanged(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    adr = await decision(mcp_server, ids["requirement"], consequences={"positive": "Search is fast"})

    assert "**Positive**: Search is fast\n" in await details(mcp_server, adr)


async def test_3_a_requirement_names_the_decisions_it_addresses(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)

    report = await details(mcp_server, ids["requirement"])

    assert f"## Addresses Decisions (1)\n- {ids['adr']}: Use FTS5 [Proposed]\n" in report


async def test_3b_a_requirement_names_its_requirement_links_and_their_type(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    other = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "FUNC",
            "title": "Rank results",
            "priority": "P2",
            "current_state": "Results come back unordered.",
            "desired_state": "Results come back ranked.",
        },
    )
    assert not other.isError, text_of(other)
    sibling = other.structuredContent["id"]
    linked = await call(
        mcp_server,
        "create_relationship",
        {"source_id": ids["requirement"], "target_id": sibling, "relationship_type": "relates"},
    )
    assert not linked.isError, text_of(linked)

    outgoing = await details(mcp_server, ids["requirement"])
    incoming = await details(mcp_server, sibling)

    assert f"## Linked Requirements (1)\n- relates → {sibling}: Rank results [Draft]\n" in outgoing
    assert f"- relates ← {ids['requirement']}: " in incoming


async def test_4_a_requirement_with_no_links_of_a_kind_has_no_empty_section(mcp_server):  # noqa: F811
    bare = await call(
        mcp_server,
        "create_requirement",
        {
            "type": "TECH",
            "title": "Nothing links here",
            "priority": "P3",
            "current_state": "Nothing points at this requirement.",
            "desired_state": "Nothing still points at it.",
        },
    )
    assert not bare.isError, text_of(bare)

    report = await details(mcp_server, bare.structuredContent["id"])

    assert "Addresses Decisions" not in report
    assert "Linked Requirements" not in report
    assert "Linked Tasks" not in report
