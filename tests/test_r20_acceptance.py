"""R20 acceptance: each acceptance criterion of REQ-0011-FUNC-00 (amending an accepted decision) through the MCP
server layer, one test per criterion in the requirement's order.

An accepted decision that says 16 while the code says 32 is the failure mode decision records exist to prevent.
The remedies before this were a comment, which renders away from the decision, or a whole superseding ADR, which
buries a one-number correction under a second document. An amendment sits between them without relaxing R6a: the
decision's own text is never rewritten.
"""

from .test_tool_results import call, mcp_server, populate, text_of  # noqa: F401 (mcp_server is a fixture)

CORRECTION = "The pool defaults to 32, not 16: the benchmark this decision called for measured 32."


async def accept(server, architecture_id: str = "ADR-0001") -> None:
    result = await call(
        server, "update_architecture_status", {"architecture_id": architecture_id, "new_status": "Accepted"}
    )
    assert not result.isError, text_of(result)


async def amend(server, amendment: str, architecture_id: str = "ADR-0001", **extra):
    return await call(
        server, "update_architecture", {"architecture_id": architecture_id, "amendment": amendment, **extra}
    )


async def details(server, entity_id: str) -> str:
    result = await call(server, "get_details", {"entity_id": entity_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def history(server, entity_id: str) -> str:
    result = await call(server, "get_entity_history", {"entity_id": entity_id})
    assert not result.isError, text_of(result)
    return text_of(result)


async def test_1_an_amendment_leaves_the_decision_as_written_and_shows_with_it(mcp_server):  # noqa: F811
    ids = await populate(mcp_server)
    await accept(mcp_server)

    amended = await amend(mcp_server, CORRECTION, reason="The benchmark contradicted the decision")
    assert not amended.isError, text_of(amended)
    assert amended.structuredContent["amendments"] == 1

    shown = await details(mcp_server, ids["adr"])
    assert "## Decision\nSQLite FTS5" in shown  # the original text, byte for byte
    assert "## Amendments (1)" in shown and CORRECTION in shown
    assert shown.index("## Decision") < shown.index("## Amendments")  # the correction sits with what it corrects
    assert "**Revision**: 0" in shown  # nothing was edited


async def test_2_the_exported_documentation_carries_the_amendment(mcp_server, tmp_path):  # noqa: F811
    await populate(mcp_server)
    await accept(mcp_server)
    await amend(mcp_server, CORRECTION, reason="The benchmark contradicted the decision")
    commented = await call(mcp_server, "add_comment", {"entity_id": "ADR-0001", "comment": "Raised in review"})
    assert not commented.isError, text_of(commented)

    export = {"project_name": "r20", "output_directory": str(tmp_path), "include_tasks": False}
    exported = await call(mcp_server, "export_project_documentation", export)
    assert not exported.isError, text_of(exported)

    document = (tmp_path / "r20-architecture.md").read_text(encoding="utf-8")
    assert "### Amendments (1)" in document and CORRECTION in document
    # Read in order, without following a link or scrolling to the comments.
    assert document.index("### Decision") < document.index("### Amendments") < document.index("**Comments**")


async def test_3_amending_a_proposed_decision_says_to_edit_it_instead(mcp_server):  # noqa: F811
    await populate(mcp_server)  # leaves ADR-0001 Proposed

    refused = await amend(mcp_server, CORRECTION)

    assert refused.isError
    assert "is Proposed; edit it instead" in text_of(refused)
    assert "Amendments" not in await details(mcp_server, "ADR-0001")


async def test_4_editing_an_accepted_decision_names_amendment_and_supersession(mcp_server):  # noqa: F811
    await populate(mcp_server)
    await accept(mcp_server)

    refused = await call(mcp_server, "update_architecture", {"architecture_id": "ADR-0001", "decision": "Use Tantivy"})

    assert refused.isError
    explanation = text_of(refused)
    assert "only Proposed decisions can be edited" in explanation  # R6a's rule is unchanged
    assert "amendment" in explanation and "supersedes" in explanation  # both ways out are named
    assert "SQLite FTS5" in await details(mcp_server, "ADR-0001")


async def test_5_an_amendment_is_its_own_event_in_the_history(mcp_server):  # noqa: F811
    await populate(mcp_server)
    await accept(mcp_server)
    await amend(mcp_server, CORRECTION, reason="The benchmark measured 32")

    shown = await history(mcp_server, "ADR-0001")

    assert "amended decision_outcome by MCP User" in shown
    assert "(reason: The benchmark measured 32)" in shown
    assert "edited decision_outcome" not in shown  # not a field edit
    assert "comment by" not in shown  # and not a comment


async def test_6_an_amendment_cannot_be_smuggled_in_beside_an_edit(mcp_server):  # noqa: F811
    await populate(mcp_server)
    await accept(mcp_server)

    refused = await amend(mcp_server, CORRECTION, decision="Use Tantivy")

    assert refused.isError and "Pass amendment on its own" in text_of(refused)
    assert "SQLite FTS5" in await details(mcp_server, "ADR-0001")
