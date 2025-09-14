"""
LLM prompts and strategies for requirement decomposition analysis.
Used by RequirementHandler to determine when and how to decompose requirements.
"""

import json
import re
from typing import Any


class DecompositionPromptGenerator:
    """Generates prompts for LLM-based requirement decomposition analysis."""

    @staticmethod
    def create_complexity_analysis_prompt(requirement_data: dict[str, Any]) -> str:
        """Create prompt for analyzing requirement complexity and decomposition needs."""

        prompt = f"""Analyze this software requirement for complexity and decomposition needs:

**Requirement Title:** {requirement_data.get("title", "N/A")}
**Type:** {requirement_data.get("type", "N/A")}
**Priority:** {requirement_data.get("priority", "N/A")}

**Current State:** {requirement_data.get("current_state", "N/A")}
**Desired State:** {requirement_data.get("desired_state", "N/A")}

**Functional Requirements:**
{DecompositionPromptGenerator._format_json_list(requirement_data.get("functional_requirements"))}

**Acceptance Criteria:**
{DecompositionPromptGenerator._format_json_list(requirement_data.get("acceptance_criteria"))}

**Business Value:** {requirement_data.get("business_value", "N/A")}

---

**ANALYSIS INSTRUCTIONS:**

1. **Complexity Assessment (1-10 scale):**
   - 1-3: Simple, single feature
   - 4-6: Moderate, multiple related features
   - 7-8: Complex, multiple unrelated features or workflows
   - 9-10: Epic-level, requires significant decomposition

2. **Scope Assessment:**
   - single_feature: One cohesive feature
   - multiple_features: Several related features
   - complex_workflow: Multi-step workflow across features
   - epic: Large initiative requiring multiple requirements

3. **Decomposition Indicators:**
   - Title contains "and", "multiple", "various", "all"
   - Multiple unrelated functional requirements
   - Acceptance criteria spanning different user journeys
   - Business value mentions multiple stakeholder groups
   - Gap between current and desired state is significant

4. **Good vs Bad Decomposition Examples:**
   - GOOD: "User Authentication System" → "Login", "Registration", "Password Reset"
   - BAD: "Navigation Bar" (single cohesive feature, don't decompose)
   - GOOD: "E-commerce Platform" → "Product Catalog", "Shopping Cart", "Payment Processing"
   - BAD: "Add Submit Button" (too granular, don't decompose)

**OUTPUT FORMAT (JSON only):**
{{
  "complexity_score": <1-10>,
  "scope_assessment": "<single_feature|multiple_features|complex_workflow|epic>",
  "decomposition_recommendation": "<none|suggested|required>",
  "reasoning": "<brief explanation>",
  "suggested_decomposition": [
    {{
      "title": "<sub-requirement title>",
      "type": "<FUNC|NFUNC|TECH|BUS|INTF>",
      "rationale": "<why this is a separate requirement>"
    }}
  ],
  "decomposition_confidence": <0.0-1.0>
}}

Analyze now:"""

        return prompt

    @staticmethod
    def create_decomposition_validation_prompt(
        parent_requirement: dict[str, Any], proposed_children: list[dict[str, Any]]
    ) -> str:
        """Create prompt for validating proposed requirement decomposition."""

        children_summary = "\n".join(
            [f"- {child.get('title', 'N/A')} ({child.get('type', 'N/A')})" for child in proposed_children]
        )

        prompt = f"""Validate this requirement decomposition:

**PARENT REQUIREMENT:**
Title: {parent_requirement.get("title", "N/A")}
Type: {parent_requirement.get("type", "N/A")}
Functional Requirements: {
            DecompositionPromptGenerator._format_json_list(parent_requirement.get("functional_requirements"))
        }

**PROPOSED SUB-REQUIREMENTS:**
{children_summary}

**VALIDATION CRITERIA:**
1. **Completeness**: Do the sub-requirements cover all aspects of the parent?
2. **Non-Overlap**: Are the sub-requirements distinct without redundancy?
3. **Appropriate Scope**: Is each sub-requirement implementable as a single feature?
4. **Coherence**: Do the sub-requirements logically belong together under the parent?
5. **Traceability**: Can you trace parent acceptance criteria to specific children?

**OUTPUT FORMAT (JSON only):**
{{
  "validation_result": "<approved|needs_revision|rejected>",
  "completeness_score": <0.0-1.0>,
  "coherence_score": <0.0-1.0>,
  "issues": [
    {{
      "type": "<missing_coverage|overlap|scope_too_large|scope_too_small|logical_disconnect>",
      "description": "<specific issue>",
      "affected_children": ["<child_title>"]
    }}
  ],
  "suggestions": [
    {{
      "action": "<add|remove|merge|split|rename>",
      "target": "<child_title>",
      "recommendation": "<specific suggestion>"
    }}
  ],
  "confidence": <0.0-1.0>
}}

Validate now:"""

        return prompt

    @staticmethod
    def create_interactive_decomposition_prompt(
        requirement_data: dict[str, Any], user_responses: dict[str, Any] = None
    ) -> str:
        """Create prompt for interactive decomposition conversation."""

        if not user_responses:
            # Initial decomposition interview
            prompt = f"""Start an interactive decomposition interview for this requirement:

**Requirement:** {requirement_data.get("title", "N/A")}
**Current State:** {requirement_data.get("current_state", "N/A")}
**Desired State:** {requirement_data.get("desired_state", "N/A")}

Ask 3-5 clarifying questions to understand decomposition needs. Focus on:
1. User journey boundaries
2. Feature interdependencies
3. Implementation phases
4. Stakeholder priorities
5. Technical constraints

**OUTPUT FORMAT (JSON only):**
{{
  "questions": [
    {{
      "id": "q1",
      "question": "<question text>",
      "type": "<multiple_choice|open_ended|ranking>",
      "options": ["<option1>", "<option2>"] // only for multiple_choice
    }}
  ],
  "context": "<why these questions matter for decomposition>",
  "next_stage": "awaiting_responses"
}}

Generate questions now:"""
        else:
            # Continue with responses
            responses_summary = "\n".join([f"Q: {q_id}\nA: {response}" for q_id, response in user_responses.items()])

            prompt = f"""Continue decomposition interview with user responses:

**Original Requirement:** {requirement_data.get("title", "N/A")}

**User Responses:**
{responses_summary}

Based on responses, either:
1. Ask follow-up questions if more clarity needed
2. Provide final decomposition recommendation

**OUTPUT FORMAT (JSON only):**
{{
  "action": "<more_questions|final_recommendation>",
  "questions": [ /* if more_questions */ ],
  "decomposition": [ /* if final_recommendation */
    {{
      "title": "<sub-requirement title>",
      "type": "<type>",
      "priority": "<P0|P1|P2|P3>",
      "rationale": "<based on user responses>"
    }}
  ],
  "confidence": <0.0-1.0>
}}

Continue interview:"""

        return prompt

    @staticmethod
    def _format_json_list(json_str: str | None) -> str:
        """Format JSON list/array for display in prompts."""
        if not json_str:
            return "None specified"

        try:
            items = json.loads(json_str)
            if isinstance(items, list):
                return "\n".join(f"- {item}" for item in items)
            elif isinstance(items, dict):
                return "\n".join(f"- {k}: {v}" for k, v in items.items())
            else:
                return str(items)
        except (json.JSONDecodeError, TypeError):
            return json_str

    @staticmethod
    def extract_decomposition_indicators(requirement_text: str) -> dict[str, Any]:
        """Extract linguistic indicators that suggest decomposition needs."""

        indicators = {
            "title_keywords": [],
            "conjunction_count": 0,
            "multiple_entities": [],
            "workflow_indicators": [],
            "scope_indicators": [],
        }

        text_lower = requirement_text.lower()

        # Title keywords suggesting multiple features
        title_keywords = ["and", "multiple", "various", "all", "comprehensive", "full", "complete"]
        indicators["title_keywords"] = [kw for kw in title_keywords if kw in text_lower]

        # Count conjunctions
        conjunctions = ["and", "or", "also", "plus", "including", "with"]
        indicators["conjunction_count"] = sum(text_lower.count(conj) for conj in conjunctions)

        # Multiple entity indicators
        entity_patterns = [
            r"\b(users?|customers?|admins?|managers?)\b.*\b(users?|customers?|admins?|managers?)\b",
            r"\b(create|read|update|delete)\b.*\b(create|read|update|delete)\b",
            r"\b(view|edit|manage|configure)\b.*\b(view|edit|manage|configure)\b",
        ]

        for pattern in entity_patterns:
            if re.search(pattern, text_lower):
                indicators["multiple_entities"].append(pattern)

        # Workflow indicators
        workflow_words = ["workflow", "process", "journey", "flow", "pipeline", "sequence"]
        indicators["workflow_indicators"] = [w for w in workflow_words if w in text_lower]

        # Scope indicators
        scope_words = ["system", "platform", "framework", "suite", "solution", "application"]
        indicators["scope_indicators"] = [w for w in scope_words if w in text_lower]

        return indicators


class DecompositionStrategy:
    """Strategies for different types of requirement decomposition."""

    STRATEGIES = {
        "feature_based": {
            "description": "Decompose by distinct features/capabilities",
            "suitable_for": ["FUNC", "BUS"],
            "indicators": ["multiple user actions", "different screens/interfaces"],
        },
        "user_journey": {
            "description": "Decompose by user journey stages",
            "suitable_for": ["FUNC", "BUS"],
            "indicators": ["workflow", "process", "journey", "sequence"],
        },
        "technical_layer": {
            "description": "Decompose by technical architecture layers",
            "suitable_for": ["TECH", "NFUNC"],
            "indicators": ["system components", "integration points", "APIs"],
        },
        "stakeholder_based": {
            "description": "Decompose by different user roles/stakeholders",
            "suitable_for": ["FUNC", "BUS", "INTF"],
            "indicators": ["multiple user types", "different permissions", "role-based"],
        },
        "implementation_phase": {
            "description": "Decompose by implementation/delivery phases",
            "suitable_for": ["FUNC", "TECH", "BUS"],
            "indicators": ["MVP", "phases", "iterations", "releases"],
        },
    }

    @classmethod
    def recommend_strategy(cls, requirement_data: dict[str, Any]) -> list[str]:
        """Recommend decomposition strategies based on requirement characteristics."""

        req_type = requirement_data.get("type", "")
        title = requirement_data.get("title", "").lower()
        functional_reqs = requirement_data.get("functional_requirements", "")

        recommended = []

        for strategy, details in cls.STRATEGIES.items():
            if req_type in details["suitable_for"]:
                # Check if indicators are present
                if any(
                    indicator in title or indicator in functional_reqs.lower() for indicator in details["indicators"]
                ):
                    recommended.append(strategy)

        return recommended if recommended else ["feature_based"]  # Default strategy
