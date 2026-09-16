#!/usr/bin/env python3
"""Prompts the server offers clients (roadmap R11).

A prompt is text the client's own model fills in and then passes to a tool. Nothing is kept on the server between
calls, which is what sank the interview tools R16 removed: they needed a long-lived process and lost their session
on restart (F-08). Prompts are also a separate MCP primitive from tools, so they cost nothing against the tool
surface budget (ADR-0002).

The capture prompt exists because the fields were there and went unused: measured in this project's own tracker,
validation_metrics was set on 0 of 18 requirements, business_rules and nonfunctional_requirements likewise.
"""

from mcp.types import GetPromptResult, Prompt, PromptArgument, PromptMessage, TextContent

CAPTURE_REQUIREMENT = "capture_requirement"

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
        )
    ]


def render_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
    """The text for one prompt. Raises ValueError for a name this server does not offer."""
    if name != CAPTURE_REQUIREMENT:
        offered = ", ".join(prompt.name for prompt in prompt_definitions())
        raise ValueError(f"Unknown prompt: {name}. This server offers: {offered}")

    about = (arguments or {}).get("about")
    text = _GUIDE if not about else f'{_GUIDE}\n\nWhat they said they need:\n"{about}"'
    return GetPromptResult(
        description="Write a lifecycle requirement and create it",
        messages=[PromptMessage(role="user", content=TextContent(type="text", text=text))],
    )
