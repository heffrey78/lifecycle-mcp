"""The links the handlers create and the links create_relationship permits cannot drift apart (REQ-0007-INTF-00).

create_relationship refused a task's parent link as "Invalid relationship: task -> task (parent)" while create_task
and update_task both created exactly that link through BaseHandler._link, which never consults the permitted table.
Two lists with no connection to each other, so nothing noticed. This reads the _link calls out of the source, so
adding one in a handler is enough to trip the test, and a pair that a dedicated tool owns has to say so out loud -
the shape test_schema_coverage.py already uses for a column no tool exposes.
"""

import ast
from pathlib import Path

from lifecycle_mcp.handlers.relationship_handler import LINKS_OWNED_BY_A_TOOL, RelationshipHandler

HANDLERS = Path(__file__).resolve().parent.parent / "src" / "lifecycle_mcp" / "handlers"


def linked_pairs() -> dict[tuple[str, str, str], list[str]]:
    """Every (source_type, target_type, relationship_type) the handlers pass to _link, by file.

    Read from the source rather than listed by hand: a list would be the third copy of the same fact.
    """
    found: dict[tuple[str, str, str], list[str]] = {}
    for path in sorted(HANDLERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "_link" or len(node.args) < 5:
                continue
            literals = [arg.value if isinstance(arg, ast.Constant) else None for arg in node.args[:5]]
            source_type, _, target_type, _, rel_type = literals
            if source_type and target_type and rel_type:
                found.setdefault((source_type, target_type, rel_type), []).append(path.name)
    return found


def test_the_handlers_do_create_links_we_can_see():
    """A guard on the guard: if the AST walk stops finding anything, every assertion below passes vacuously."""
    pairs = linked_pairs()

    # Four distinct pairs across six call sites today: implements and parent are each written from two places.
    assert len(pairs) >= 4, pairs
    assert sum(len(files) for files in pairs.values()) >= 6, pairs
    assert ("requirement", "task", "implements") in pairs
    assert ("task", "task", "parent") in pairs


def test_every_link_the_handlers_create_is_permitted_or_owned_by_a_named_tool():
    handler = RelationshipHandler.__new__(RelationshipHandler)

    unaccounted = {
        pair: files
        for pair, files in linked_pairs().items()
        if not handler._validate_relationship(*pair) and pair not in LINKS_OWNED_BY_A_TOOL
    }

    assert not unaccounted, (
        "These links are created by the handlers but create_relationship would call them invalid. Either permit the "
        f"pair in _validate_relationship, or add it to LINKS_OWNED_BY_A_TOOL naming the tool and why: {unaccounted}"
    )


def test_a_pair_is_permitted_or_owned_but_never_both():
    """Both would mean create_relationship makes the link and also says it does not."""
    handler = RelationshipHandler.__new__(RelationshipHandler)

    both = [pair for pair in LINKS_OWNED_BY_A_TOOL if handler._validate_relationship(*pair)]

    assert not both, both


def test_every_owned_pair_names_a_tool_and_a_reason():
    assert LINKS_OWNED_BY_A_TOOL, "an empty list would make the drift test vacuous"

    for pair, (tool, reason) in LINKS_OWNED_BY_A_TOOL.items():
        assert tool and reason, pair
        assert "_" in tool or " " in tool, f"{pair} should name the tool and its parameter, got {tool!r}"
        assert len(reason) > 40, f"{pair} should say why, got {reason!r}"


def test_the_task_parent_pair_is_the_one_we_know_about():
    """Written down so that resolving it the other way - permitting the pair - has to change this test deliberately."""
    assert ("task", "task", "parent") in LINKS_OWNED_BY_A_TOOL
    tool, reason = LINKS_OWNED_BY_A_TOOL[("task", "task", "parent")]
    assert "update_task" in tool and "parent_task_id" in tool
    assert "field_edit" in reason, "the reason it is not a plain row is the history it would skip"
