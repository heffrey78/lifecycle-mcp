#!/usr/bin/env python3
"""
LLM Question Generator for Intelligent Requirement Interviews
Generates contextual questions using LLM to improve requirement gathering
"""

import json
import logging
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class InterviewStage(Enum):
    """Interview stages for contextual question generation"""

    PROBLEM_IDENTIFICATION = "problem_identification"
    SOLUTION_DEFINITION = "solution_definition"
    DETAILS_GATHERING = "details_gathering"
    VALIDATION = "validation"


class LLMQuestionGenerator:
    """Generates intelligent questions for requirement interviews using LLM"""

    def __init__(self, llm_client=None):
        """Initialize with optional LLM client"""
        self.llm_client = llm_client
        self.max_questions = 3

    async def generate_questions(
        self,
        stage: InterviewStage,
        project_context: str = "",
        stakeholder_role: str = "",
        previous_answers: Dict[str, Any] = None,
        existing_requirements: List[Dict] = None,
    ) -> List[str]:
        """Generate 1-3 contextual questions for the interview stage"""

        if not self.llm_client:
            return self._get_fallback_questions(stage)

        try:
            if stage == InterviewStage.PROBLEM_IDENTIFICATION:
                return await self._generate_initial_questions(project_context, stakeholder_role)
            else:
                return await self._generate_progressive_questions(stage, previous_answers, existing_requirements)
        except Exception as e:
            logger.warning(f"LLM question generation failed: {e}. Using fallback questions.")
            return self._get_fallback_questions(stage)

    async def _generate_initial_questions(self, project_context: str, stakeholder_role: str) -> List[str]:
        """Generate initial questions for problem identification"""

        prompt = (
            f"You are a requirements analyst conducting an interview. "
            f"Generate 1-3 targeted questions to understand the user's requirement.\n\n"
            f"Context:\n"
            f"- Project: {project_context or 'Not specified'}\n"
            f"- User Role: {stakeholder_role or 'Not specified'}\n"
            f"- Interview Stage: Problem Identification\n\n"
            f"Focus on:\n"
            f"- Understanding the core problem/opportunity\n"
            f"- Identifying stakeholders and impact\n"
            f"- Gathering initial scope boundaries\n\n"
            f"Generate questions that help decompose requirements into actionable pieces. "
            f"Return as JSON array of strings.\n"
            f"Maximum 3 questions."
        )

        return await self._call_llm_and_parse(prompt)

    async def _generate_progressive_questions(
        self, stage: InterviewStage, previous_answers: Dict[str, Any], existing_requirements: List[Dict] = None
    ) -> List[str]:
        """Generate follow-up questions based on stage and context"""

        stage_focus = {
            InterviewStage.SOLUTION_DEFINITION: "Success criteria, constraints, desired outcomes",
            InterviewStage.DETAILS_GATHERING: "Priority, type, functional details, effort estimation",
            InterviewStage.VALIDATION: "Acceptance criteria, testing approach, completion definition",
        }

        answers_summary = self._summarize_answers(previous_answers or {})
        existing_summary = self._summarize_requirements(existing_requirements or [])

        prompt = f"""You are a requirements analyst. Based on previous answers, generate 1-3 follow-up questions.

Previous Context:
{answers_summary}

Current Stage: {stage.value.replace("_", " ").title()}
Focus Areas: {stage_focus.get(stage, "General requirement details")}

Existing Requirements Context:
{existing_summary}

Generate questions that:
1. Build on previous answers
2. Fill gaps in requirement understanding
3. Help decompose complex requirements into smaller pieces
4. Focus on scoping and implementation feasibility
5. Avoid duplicating existing requirements

Return as JSON array of strings. Maximum 3 questions."""

        return await self._call_llm_and_parse(prompt)

    async def _call_llm_and_parse(self, prompt: str) -> List[str]:
        """Call LLM and parse response into question list"""
        try:
            # This would integrate with actual LLM client
            # For now, simulate LLM call with structured response
            response = await self._simulate_llm_call(prompt)

            # Parse JSON response
            if response.startswith("[") and response.endswith("]"):
                questions = json.loads(response)
                return questions[: self.max_questions]  # Limit to max questions
            else:
                # Fallback parsing if not JSON
                return [q.strip() for q in response.split("\n") if q.strip()][: self.max_questions]

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise

    async def _simulate_llm_call(self, prompt: str) -> str:
        """Simulate LLM call - replace with actual LLM integration"""
        # This is a placeholder for actual LLM integration
        # In production, this would call OpenAI, Claude, or other LLM APIs

        if "Problem Identification" in prompt:
            return json.dumps(
                [
                    "What specific problem or pain point are you trying to solve?",
                    "Who are the primary users or stakeholders affected by this issue?",
                    "What happens if this problem remains unresolved?",
                ]
            )
        elif "Solution Definition" in prompt:
            return json.dumps(
                [
                    "What would a successful solution look like from the user's perspective?",
                    "Are there any technical or business constraints we must consider?",
                    "What is the expected timeline or urgency for this requirement?",
                ]
            )
        elif "Details Gathering" in prompt:
            return json.dumps(
                [
                    "What priority level should this requirement have (P0-P3)?",
                    "Is this primarily a functional, technical, or business requirement?",
                    "What systems or components will need to be modified?",
                ]
            )
        else:  # Validation
            return json.dumps(
                [
                    "How will we verify that this requirement has been successfully implemented?",
                    "What specific acceptance criteria must be met?",
                    "Are there any edge cases or error scenarios to consider?",
                ]
            )

    def _summarize_answers(self, answers: Dict[str, Any]) -> str:
        """Summarize previous interview answers for context"""
        if not answers:
            return "No previous answers provided."

        summary_parts = []
        for key, value in answers.items():
            if value:
                summary_parts.append(f"- {key.replace('_', ' ').title()}: {value}")

        return "\n".join(summary_parts) if summary_parts else "No significant previous answers."

    def _summarize_requirements(self, requirements: List[Dict]) -> str:
        """Summarize existing requirements for context"""
        if not requirements:
            return "No existing requirements in the system."

        summary = f"Existing requirements ({len(requirements)} total):\n"
        for req in requirements[:5]:  # Limit to first 5 for brevity
            title = req.get("title", "Untitled")
            req_type = req.get("type", "FUNC")
            summary += f"- {req_type}: {title}\n"

        if len(requirements) > 5:
            summary += f"... and {len(requirements) - 5} more"

        return summary

    def _get_fallback_questions(self, stage: InterviewStage) -> List[str]:
        """Fallback questions when LLM is unavailable"""

        fallback_questions = {
            InterviewStage.PROBLEM_IDENTIFICATION: [
                "What specific problem or opportunity are you trying to address?",
                "Who would be most impacted if this problem isn't solved?",
                "What is the current state that needs to be improved?",
            ],
            InterviewStage.SOLUTION_DEFINITION: [
                "What would success look like once this requirement is implemented?",
                "Are there any specific constraints or limitations we need to consider?",
                "What is the expected business value or impact?",
            ],
            InterviewStage.DETAILS_GATHERING: [
                "What priority would you assign to this requirement (P0=Critical, P1=High, P2=Medium, P3=Low)?",
                "What type of requirement is this (FUNC, NFUNC, TECH, BUS, INTF)?",
                "What systems or components will be affected?",
            ],
            InterviewStage.VALIDATION: [
                "How will we know this requirement has been successfully implemented?",
                "What are the specific acceptance criteria that must be met?",
                "Are there any edge cases or error scenarios to consider?",
            ],
        }

        return fallback_questions.get(stage, ["What additional details are needed for this requirement?"])
