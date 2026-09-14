"""The shared edit engine behind every update tool (roadmap R6a, TASK-0017)."""

import json
import sqlite3

import pytest

from lifecycle_mcp.handlers.base_handler import EditRefused, RevisionConflict

REQ = "REQ-0001-FUNC-00"
EDITABLE = {"title", "priority", "acceptance_criteria", "business_value"}
JSON_FIELDS = {"acceptance_criteria"}


@pytest.fixture
def handler(requirement_handler, db_manager):
    db_manager.insert_record(
        "requirements",
        {
            "id": REQ,
            "requirement_number": 1,
            "type": "FUNC",
            "title": "Original",
            "priority": "P2",
            "author": "tests",
            "acceptance_criteria": json.dumps(["one"]),
        },
    )
    return requirement_handler


def edit(handler, changes, **options):
    return handler._apply_edit(
        "requirements", "requirement", REQ, changes, editable=EDITABLE, json_fields=JSON_FIELDS, **options
    )


def stored(handler):
    return dict(handler.db.get_records("requirements", "*", "id = ?", [REQ])[0])


def edit_events(handler):
    rows = handler.db.execute_query(
        "SELECT field, from_value, to_value, actor, reason FROM lifecycle_events "
        "WHERE entity_id = ? AND event_type = 'field_edit' ORDER BY id",
        [REQ],
        fetch_all=True,
    )
    return [tuple(row) for row in rows]


def test_changed_fields_are_written_with_one_revision_bump_and_an_event_each(handler):
    result = edit(
        handler,
        {"title": "Renamed", "priority": "P2", "acceptance_criteria": ["one", "two"]},
        actor="agent",
        reason="clarified scope",
    )

    assert result.changed == ["title", "acceptance_criteria"]
    assert result.revision == 1
    assert result.before["title"] == "Original"
    record = stored(handler)
    assert record["title"] == "Renamed" and record["revision"] == 1
    assert json.loads(record["acceptance_criteria"]) == ["one", "two"]
    assert edit_events(handler) == [
        ("title", "Original", "Renamed", "agent", "clarified scope"),
        ("acceptance_criteria", '["one"]', '["one", "two"]', "agent", "clarified scope"),
    ]


def test_unchanged_values_write_nothing(handler):
    result = edit(handler, {"title": "Original", "acceptance_criteria": ["one"]})

    assert result.changed == [] and result.revision == 0
    assert stored(handler)["revision"] == 0
    assert edit_events(handler) == []


def test_stale_if_revision_is_refused_without_writing(handler):
    edit(handler, {"title": "First"})

    with pytest.raises(RevisionConflict, match="at revision 1, not 0"):
        edit(handler, {"title": "Second"}, if_revision=0)

    record = stored(handler)
    assert record["title"] == "First" and record["revision"] == 1
    assert len(edit_events(handler)) == 1


def test_current_if_revision_is_accepted(handler):
    edit(handler, {"title": "First"})
    assert edit(handler, {"title": "Second"}, if_revision=1).revision == 2


def test_fields_outside_the_editable_set_are_refused(handler):
    with pytest.raises(ValueError, match="Not editable: status"):
        edit(handler, {"status": "Validated"})
    assert stored(handler)["revision"] == 0


def test_a_rejected_value_rolls_back_every_field(handler):
    with pytest.raises(sqlite3.IntegrityError):
        edit(handler, {"title": "Renamed", "priority": "P9"})

    record = stored(handler)
    assert record["title"] == "Original" and record["priority"] == "P2" and record["revision"] == 0
    assert edit_events(handler) == []


def test_missing_record_raises_lookup_error(handler):
    with pytest.raises(LookupError, match="not found"):
        handler._apply_edit("requirements", "requirement", "REQ-9999-FUNC-00", {"title": "x"}, editable=EDITABLE)


def links(handler):
    return handler.db.execute_query("SELECT COUNT(*) FROM relationships WHERE source_id = ?", [REQ], fetch_one=True)[0]


def test_check_sees_the_stored_record_and_its_refusal_writes_nothing(handler):
    def refuse(before):
        assert before["title"] == "Original"
        raise EditRefused("not now")

    with pytest.raises(EditRefused, match="not now"):
        edit(handler, {"title": "Renamed"}, check=refuse)

    assert stored(handler)["title"] == "Original"
    assert edit_events(handler) == []


def test_link_changes_share_the_revision_bump_and_are_logged(handler):
    def relink(cur, before):
        handler._link("requirement", REQ, "requirement", "REQ-0002-FUNC-00", "informs", cursor=cur)
        return {"informs": (None, "REQ-0002-FUNC-00")}

    result = edit(handler, {"title": "Renamed"}, relink=relink, reason="split out")

    assert result.changed == ["title", "informs"] and result.revision == 1
    assert edit_events(handler)[-1] == ("informs", None, "REQ-0002-FUNC-00", "MCP User", "split out")
    assert links(handler) == 1


def test_a_refused_relink_rolls_back_the_links_it_already_wrote(handler):
    def relink(cur, before):
        handler._link("requirement", REQ, "requirement", "REQ-0002-FUNC-00", "informs", cursor=cur)
        raise EditRefused("second link not allowed")

    with pytest.raises(EditRefused):
        edit(handler, {"title": "Renamed"}, relink=relink)

    assert links(handler) == 0
    record = stored(handler)
    assert record["title"] == "Original" and record["revision"] == 0
