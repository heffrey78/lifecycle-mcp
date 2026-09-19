#!/usr/bin/env python3
"""Prompts the server offers clients (roadmap R11).

A prompt is text the client's own model fills in and then passes to a tool. Nothing is kept on the server between
calls, which is what sank the interview tools R16 removed: they needed a long-lived process and lost their session
on restart (F-08). Prompts are also a separate MCP primitive from tools, so they cost nothing against the tool
surface budget (ADR-0002).

The capture prompt exists because the fields were there and went unused: measured in this project's own tracker,
validation_metrics was set on 0 of 18 requirements, business_rules and nonfunctional_requirements likewise.

The reconcile prompt (roadmap R21) is the same argument applied to a body of work that predates the tracker. Reading a
transcript or a codebase and deciding what is new is the client model's job and it is good at it; what was missing was
the discipline of comparing before creating, which is a paragraph of instructions rather than a tool.

It searches per candidate rather than opening with the whole set, because the whole set does not fit: the first real
run of this prompt asked for 25 requirements and got back 72,858 characters, which the client refused. Listing
everything is not a starting point that grows.
"""

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

CAPTURE_REQUIREMENT = "capture_requirement"
RECONCILE_REQUIREMENTS = "reconcile_requirements"

_GUIDE = """Write a lifecycle requirement, then create it with the create_requirement tool.

Ask the person what they need, in their words, and fill these fields yourself. Do not ask them to name fields.

Required:
- type: FUNC (behaviour), NFUNC (speed, size, reliability), TECH (how it is built), BUS (policy), INTF (an interface)
- title: what changes, in a few words
- priority: P0 urgent, P1 next, P2 soon, P3 someday
- current_state: what happens today, concretely. Name the thing that is wrong, not the absence of the fix
- desired_state: what should happen instead, in one sentence

Worth filling, and warned about when missing:
- acceptance_criteria: how anyone can tell it is done. One line each, checkable without you in the room
- validation_metrics: for NFUNC, the number that settles it, such as "search p95 under 50 ms at 10k notes".
  A requirement about speed with no number cannot be checked later, only argued about

Fill when they apply:
- functional_requirements: what it has to do, one line each
- nonfunctional_requirements, technical_constraints, business_rules
- out_of_scope: what this deliberately does not cover, so it stops coming up
- business_value: why it is worth doing
- risk_level: High, Medium or Low

A worked example:

  create_requirement(
    type="NFUNC",
    title="Search stays fast as notes grow",
    priority="P1",
    current_state="Search runs unindexed over every note; at 10k notes a query takes about 900 ms.",
    desired_state="Search stays quick as the collection grows.",
    acceptance_criteria=["A search over 10k notes returns in under 50 ms at p95"],
    validation_metrics=["Search p95 under 50 ms at 10k notes, measured by the benchmark task"],
    out_of_scope=["Ranking quality, which REQ-0003-FUNC-00 covers"],
  )

Create the requirement in one call once you have the fields. The server refuses nothing here: if something is thin
it says so, and you can fill it in afterwards with update_requirement."""


_RECONCILE = """Compare what a source says about requirements with the requirements already stored, then report and \
apply the difference.

The source is a transcript, a design document, a reading of a codebase, or anything else that describes what a system
has to do. You read it; the server does not. Work in this order and do not skip a step.

1. Find the candidates in the source: each thing it says the system must do, be, or be built from.
2. For each candidate, search for what may already cover it. Call query_requirements with search_text, using the
   words a stored requirement would use rather than the words the source used, and search again with another wording
   when the first finds nothing: search_text matches substrings of the title and the desired state only, so a
   requirement whose relevant text sits in its functional requirements will not come back from an obvious query.
   Do not open by listing the whole set. query_requirements returns every field of every record, which at 25
   requirements is already about 70,000 characters - more than many clients accept in one result - and the set only
   grows. Ask for it whole only when you know it is small. Do not filter by status to make it fit: a Validated
   requirement covers a candidate exactly as well as a Draft one, and the ones most likely to cover a candidate are
   the ones already built.
3. Put every candidate in exactly one of four buckets, and name the stored requirement for the last three:
   - NEW: nothing stored covers it
   - AMENDS REQ-XXXX-TYPE-VV: a stored requirement covers it, and the source changes or adds to what it says
   - ALREADY COVERED by REQ-XXXX-TYPE-VV: stored, and the source says nothing new
   - CONTRADICTS REQ-XXXX-TYPE-VV: the source asserts something the stored requirement denies
4. Report the four buckets before you write anything, so the person can see what you are about to do, and say how
   you looked: which searches you ran, and whether you ever saw the whole set. Someone who knows you tried three
   wordings and found nothing can weigh a NEW differently from one you never checked.
5. Then apply only the first two:
   - NEW: create_requirement, with origin set to derived-from-code or derived-from-transcript, whichever the source
     was. It is created in Draft, which is where it stays until a person approves it
   - AMENDS: update_requirement on that ID, naming only the fields that change. Never create a second record for a
     requirement that already exists
   - ALREADY COVERED: do nothing at all
   - CONTRADICTS: do nothing, and say so plainly. Resolving a contradiction is the reader's decision, not yours.
     A stored requirement that disagrees with the code is the tracker doing its job, not an error to clear

What the buckets are for: a requirement is worth storing because it can disagree with the code. If you quietly
rewrite stored requirements to match the source, the tracker becomes a mirror of the source and can no longer tell
anyone that something is wrong. So the default is to report, and the only silent action is doing nothing.

Two cautions:
- Code is evidence of behaviour and silent about intent. It cannot tell you what was deliberately rejected, or why.
  Read the docs and decision records beside it, and when they disagree with the code, that disagreement is a finding
  worth reporting rather than something to average out
- If the stored set is empty, say so in the report. Everything being new is a fact about the tracker, not a finding
  about the source
- Searching can miss, and a duplicate costs more than a question. When a candidate looks new but the area is one the
  system plainly already works in, say NEW and flag that you could not confirm it, rather than creating a record that
  repeats one your searches did not reach

Use the capture_requirement prompt for the fields a good requirement carries. Aim for requirements a person can
review in one sitting: fewer, well-formed ones beat one per function."""


def prompt_definitions() -> list[Prompt]:
    """Every prompt this server offers."""
    return [
        Prompt(
            name=CAPTURE_REQUIREMENT,
            description="Guide for writing a well-formed requirement, then creating it with create_requirement",
            arguments=[
                PromptArgument(
                    name="about",
                    description="What the requirement is about, in the person's own words",
                    required=False,
                )
            ],
        ),
        Prompt(
            name=RECONCILE_REQUIREMENTS,
            description="Compare a transcript, document or codebase against the stored requirements and apply the "
            "difference as new and amended records",
            arguments=[
                PromptArgument(name="source", description="The text to reconcile, or where to read it", required=False),
                PromptArgument(name="source_kind", description="transcript, code, or document", required=False),
            ],
        ),
    ]


def render_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    """The text for one prompt. Raises ValueError for a name this server does not offer."""
    if name not in (CAPTURE_REQUIREMENT, RECONCILE_REQUIREMENTS):
        offered = ", ".join(prompt.name for prompt in prompt_definitions())
        raise ValueError(f"Unknown prompt: {name}. This server offers: {offered}")

    given = arguments or {}
    if name == RECONCILE_REQUIREMENTS:
        text = _RECONCILE
        if given.get("source_kind"):
            text += f"\n\nThe source is: {given['source_kind']}"
        if given.get("source"):
            text += f"\n\nThe source:\n{given['source']}"
        return GetPromptResult(
            description="Reconcile a source against the stored requirements",
            messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
        )

    about = given.get("about")
    text = _GUIDE if not about else f'{_GUIDE}\n\nWhat they said they need:\n"{about}"'
    return GetPromptResult(
        description="Write a lifecycle requirement and create it",
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )
