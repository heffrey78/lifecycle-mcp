#!/usr/bin/env python3
"""
Interview Handler for MCP Lifecycle Management Server
Handles interactive interview operations for requirements and architecture
"""

import uuid
from typing import Any

from mcp.types import TextContent

from ..llm_question_generator import InterviewStage, LLMQuestionGenerator
from .base_handler import BaseHandler
from .requirement_handler import RequirementHandler


class InterviewHandler(BaseHandler):
    """Handler for interactive interview MCP tools"""

    def __init__(self, db_manager, requirement_handler: RequirementHandler):
        """Initialize with database manager and requirement handler for creating requirements"""
        super().__init__(db_manager)
        self.requirement_handler = requirement_handler
        self.question_generator = LLMQuestionGenerator()

        # Session storage (in-memory for simplicity)
        self.interview_sessions = {}
        self.architectural_sessions = {}

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return interview tool definitions"""
        return [
            {
                "name": "start_requirement_interview",
                "description": "Start interactive requirement gathering interview",
                "inputSchema": {
                    "type": "object",
                    "properties": {"project_context": {"type": "string"}, "stakeholder_role": {"type": "string"}},
                },
            },
            {
                "name": "continue_requirement_interview",
                "description": "Continue requirement interview with answers",
                "inputSchema": {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}, "answers": {"type": "object"}},
                    "required": ["session_id", "answers"],
                },
            },
            {
                "name": "start_architectural_conversation",
                "description": "Start interactive architectural conversation for complex diagram generation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_context": {"type": "string"},
                        "diagram_purpose": {"type": "string"},
                        "complexity_level": {
                            "type": "string",
                            "enum": ["simple", "medium", "complex"],
                            "default": "medium",
                        },
                    },
                },
            },
            {
                "name": "continue_architectural_conversation",
                "description": "Continue architectural conversation with responses",
                "inputSchema": {
                    "type": "object",
                    "properties": {"session_id": {"type": "string"}, "responses": {"type": "object"}},
                    "required": ["session_id", "responses"],
                },
            },
        ]

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
        """Route tool calls to appropriate handler methods"""
        try:
            if tool_name == "start_requirement_interview":
                return await self._start_requirement_interview(**arguments)
            elif tool_name == "continue_requirement_interview":
                return await self._continue_requirement_interview(**arguments)
            elif tool_name == "start_architectural_conversation":
                return self._start_architectural_conversation(**arguments)
            elif tool_name == "continue_architectural_conversation":
                return self._continue_architectural_conversation(**arguments)
            else:
                return self._create_error_response(f"Unknown tool: {tool_name}")
        except Exception as e:
            return self._create_error_response(f"Error handling {tool_name}", e)

    async def _start_requirement_interview(self, **params) -> list[TextContent]:
        """Start interactive requirement gathering interview"""
        try:
            session_id = str(uuid.uuid4())[:8]

            # Initialize interview session
            self.interview_sessions[session_id] = {
                "project_context": params.get("project_context", ""),
                "stakeholder_role": params.get("stakeholder_role", ""),
                "gathered_data": {},
                "current_stage": InterviewStage.PROBLEM_IDENTIFICATION,
                "questions_asked": [],
            }

            # Generate intelligent questions using LLM
            questions = await self.question_generator.generate_questions(
                stage=InterviewStage.PROBLEM_IDENTIFICATION,
                project_context=params.get("project_context", ""),
                stakeholder_role=params.get("stakeholder_role", ""),
            )

            self.interview_sessions[session_id]["current_questions"] = questions

            response = f"""# Requirement Interview Started
**Session ID**: {session_id}

## Context
- **Project**: {params.get("project_context", "Not specified")}
- **Your Role**: {params.get("stakeholder_role", "Not specified")}

## Next Questions
Please answer these questions to help gather your requirement:

"""

            for i, question in enumerate(questions, 1):
                response += f"{i}. {question}\n"

            response += (
                "\nOnce you answer these, use `continue_requirement_interview` with your session ID and answers."
            )

            # Create above-the-fold response for interview start
            key_info = f"Interview session {session_id} started"
            stage_name = InterviewStage.PROBLEM_IDENTIFICATION.value.replace("_", " ").title()
            action_info = f"🎤 {len(questions)} questions | Stage: {stage_name}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, response)

        except Exception as e:
            return self._create_error_response("Failed to start requirement interview", e)

    async def _continue_requirement_interview(self, **params) -> list[TextContent]:
        """Continue requirement interview with answers"""
        # Validate required parameters
        error = self._validate_required_params(params, ["session_id", "answers"])
        if error:
            return self._create_error_response(error)

        try:
            session_id = params["session_id"]
            answers = params["answers"]

            if session_id not in self.interview_sessions:
                return self._create_error_response("Interview session not found or expired")

            session = self.interview_sessions[session_id]

            # Store answers
            for key, value in answers.items():
                session["gathered_data"][key] = value

            # Move to next stage based on current progress
            current_stage = session["current_stage"]
            next_questions = []

            if current_stage == InterviewStage.PROBLEM_IDENTIFICATION:
                session["current_stage"] = InterviewStage.SOLUTION_DEFINITION
                next_questions = await self.question_generator.generate_questions(
                    stage=InterviewStage.SOLUTION_DEFINITION,
                    previous_answers=session["gathered_data"],
                    existing_requirements=await self._get_existing_requirements(),
                )

            elif current_stage == InterviewStage.SOLUTION_DEFINITION:
                session["current_stage"] = InterviewStage.DETAILS_GATHERING
                next_questions = await self.question_generator.generate_questions(
                    stage=InterviewStage.DETAILS_GATHERING,
                    previous_answers=session["gathered_data"],
                    existing_requirements=await self._get_existing_requirements(),
                )

            elif current_stage == InterviewStage.DETAILS_GATHERING:
                session["current_stage"] = InterviewStage.VALIDATION
                next_questions = await self.question_generator.generate_questions(
                    stage=InterviewStage.VALIDATION,
                    previous_answers=session["gathered_data"],
                    existing_requirements=await self._get_existing_requirements(),
                )

            elif current_stage == InterviewStage.VALIDATION:
                # Interview complete - generate requirement
                return await self._complete_requirement_interview(session_id)

            session["current_questions"] = next_questions

            response = f"""# Interview Progress - Session {session_id}

## Your Previous Answers Recorded ✓

## Next Questions
"""

            for i, question in enumerate(next_questions, 1):
                response += f"{i}. {question}\n"

            response += f"\nStage: {session['current_stage'].value.replace('_', ' ').title()}"
            response += "\nContinue with `continue_requirement_interview` and your answers."

            # Create above-the-fold response for interview continuation
            key_info = f"Interview session {session_id} continued"
            current_stage = session["current_stage"].value.replace("_", " ").title()
            action_info = f"🎤 {len(next_questions)} more questions | Stage: {current_stage}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, response)

        except Exception as e:
            return self._create_error_response("Failed to continue requirement interview", e)

    async def _complete_requirement_interview(self, session_id: str) -> list[TextContent]:
        """Complete interview and create requirement"""
        try:
            session = self.interview_sessions[session_id]
            data = session["gathered_data"]

            # Map interview data to requirement fields
            requirement_data = {
                "type": data.get("requirement_type", "FUNC"),
                "title": data.get("title", "Requirement from Interview"),
                "priority": data.get("priority", "P2"),
                "current_state": data.get("current_problem", "Current state not specified"),
                "desired_state": data.get("desired_outcome", "Desired state not specified"),
                "business_value": data.get("success_criteria", ""),
                "acceptance_criteria": (
                    data.get("acceptance_criteria", "").split("\n") if data.get("acceptance_criteria") else []
                ),
                "author": f"Interview Session {session_id}",
            }

            # Create the requirement using the requirement handler
            result = await self.requirement_handler._create_requirement(**requirement_data)

            # Clean up session
            del self.interview_sessions[session_id]

            interview_summary = f"""# Interview Complete!

## Requirement Created
{result[0].text}

## Interview Summary
- **Problem Identified**: {data.get("current_problem", "Not specified")}
- **Solution Desired**: {data.get("desired_outcome", "Not specified")}
- **Success Criteria**: {data.get("success_criteria", "Not specified")}
- **Priority**: {data.get("priority", "P2")}
- **Type**: {data.get("requirement_type", "FUNC")}

You can now use other tools to further develop this requirement, create tasks, or add architecture decisions.
"""

            # Create above-the-fold response for interview completion
            key_info = f"Interview session {session_id} completed"
            req_type = data.get("requirement_type", "FUNC")
            priority = data.get("priority", "P2")
            action_info = f"✅ Requirement created | Type: {req_type} | Priority: {priority}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, interview_summary)

        except Exception as e:
            return self._create_error_response("Failed to complete requirement interview", e)

    async def _get_existing_requirements(self) -> list[dict[str, Any]]:
        """Get existing requirements for context in question generation"""
        try:
            async with self.db_manager.get_connection() as conn:
                cursor = await conn.execute(
                    "SELECT id, type, title, priority, status FROM requirements ORDER BY created_at DESC LIMIT 10"
                )
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception:
            # Return empty list if query fails
            return []

    def _start_architectural_conversation(self, **params) -> list[TextContent]:
        """Start interactive architectural conversation"""
        try:
            session_id = str(uuid.uuid4())[:8]

            # Initialize architectural session
            self.architectural_sessions[session_id] = {
                "project_context": params.get("project_context", ""),
                "diagram_purpose": params.get("diagram_purpose", ""),
                "complexity_level": params.get("complexity_level", "medium"),
                "gathered_data": {},
                "current_stage": "context_gathering",
                "questions_asked": [],
            }

            # Determine first questions based on complexity and context
            questions = []
            complexity = params.get("complexity_level", "medium")

            if complexity == "simple":
                questions = [
                    "What specific components or entities should be included in the diagram?",
                    "What relationships between these entities are most important to show?",
                ]
            elif complexity == "medium":
                questions = [
                    "What is the main architectural challenge or design question this diagram should address?",
                    "Which stakeholders will be viewing this diagram and what do they need to understand?",
                    "What level of detail is appropriate (high-level overview vs detailed implementation)?",
                ]
            else:  # complex
                questions = [
                    "What are the key architectural decisions that need to be visualized?",
                    "Are there specific architectural patterns or styles being used?",
                    "What are the main data flows, dependencies, or integration points to highlight?",
                    "Are there any compliance, security, or performance considerations to show?",
                ]

            self.architectural_sessions[session_id]["current_questions"] = questions

            response = f"""# Architectural Conversation Started
**Session ID**: {session_id}

## Context
- **Project**: {params.get("project_context", "Not specified")}
- **Purpose**: {params.get("diagram_purpose", "Not specified")}
- **Complexity**: {params.get("complexity_level", "medium")}

## Next Questions
Please answer these questions to help create the most useful architectural diagram:

"""

            for i, question in enumerate(questions, 1):
                response += f"{i}. {question}\n"

            response += (
                "\nOnce you answer these, use `continue_architectural_conversation` with your session ID and responses."
            )

            # Create above-the-fold response for architectural conversation start
            key_info = f"Architectural session {session_id} started"
            purpose = params.get("diagram_purpose", "Diagram generation")
            action_info = f"🏢 {len(questions)} questions | Purpose: {purpose}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, response)

        except Exception as e:
            return self._create_error_response("Failed to start architectural conversation", e)

    def _continue_architectural_conversation(self, **params) -> list[TextContent]:
        """Continue architectural conversation with responses"""
        # Validate required parameters
        error = self._validate_required_params(params, ["session_id", "responses"])
        if error:
            return self._create_error_response(error)

        try:
            session_id = params["session_id"]
            responses = params["responses"]

            if session_id not in self.architectural_sessions:
                return self._create_error_response("Architectural conversation session not found or expired")

            session = self.architectural_sessions[session_id]

            # Store responses
            for key, value in responses.items():
                session["gathered_data"][key] = value

            # Move to next stage based on current progress
            current_stage = session["current_stage"]
            next_questions = []

            if current_stage == "context_gathering":
                session["current_stage"] = "diagram_specification"
                next_questions = [
                    "What type of diagram would be most effective (flowchart, sequence, component, etc.)?",
                    "Should the diagram focus on a specific subset of requirements or the entire project?",
                ]

            elif current_stage == "diagram_specification":
                session["current_stage"] = "detail_refinement"
                next_questions = [
                    "Are there specific visual elements or styling preferences?",
                    "Should certain elements be highlighted or emphasized?",
                ]

            elif current_stage == "detail_refinement":
                # Conversation complete - generate diagram
                return self._complete_architectural_conversation(session_id)

            session["current_questions"] = next_questions

            response = f"""# Architectural Conversation Progress - Session {session_id}

## Your Previous Responses Recorded ✓

## Next Questions
"""

            for i, question in enumerate(next_questions, 1):
                response += f"{i}. {question}\n"

            response += f"\nStage: {session['current_stage'].replace('_', ' ').title()}"
            response += "\nContinue with `continue_architectural_conversation` and your responses."

            # Create above-the-fold response for architectural conversation continuation
            key_info = f"Architectural session {session_id} continued"
            current_stage = session["current_stage"].replace("_", " ").title()
            action_info = f"🏢 {len(next_questions)} more questions | Stage: {current_stage}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, response)

        except Exception as e:
            return self._create_error_response("Failed to continue architectural conversation", e)

    def _complete_architectural_conversation(self, session_id: str) -> list[TextContent]:
        """Complete architectural conversation and generate diagram"""
        try:
            session = self.architectural_sessions[session_id]
            data = session["gathered_data"]

            # Determine diagram parameters based on conversation
            diagram_type = "full_project"  # Default

            # Analyze responses to determine best diagram type
            if any("component" in str(v).lower() for v in data.values()):
                diagram_type = "architecture"
            elif any("requirement" in str(v).lower() for v in data.values()):
                diagram_type = "requirements"
            elif any("task" in str(v).lower() for v in data.values()):
                diagram_type = "tasks"
            elif any("flow" in str(v).lower() or "process" in str(v).lower() for v in data.values()):
                diagram_type = "full_project"

            # Clean up session
            del self.architectural_sessions[session_id]

            conversation_summary = f"""# Architectural Conversation Complete!

## Recommended Diagram
Based on your responses, I recommend creating a **{diagram_type}** diagram.

## Conversation Summary
- **Project Context**: {session["project_context"]}
- **Purpose**: {session["diagram_purpose"]}
- **Complexity Level**: {session["complexity_level"]}
- **Key Insights**: {data.get("main_challenge", "Based on your responses")}

Use the `create_architectural_diagrams` tool with diagram_type="{diagram_type}" to generate the diagram.
"""

            # Create above-the-fold response for architectural conversation completion
            key_info = f"Architectural session {session_id} completed"
            action_info = f"✅ Diagram recommendation: {diagram_type} | Complexity: {session['complexity_level']}"
            return self._create_above_fold_response("SUCCESS", key_info, action_info, conversation_summary)

        except Exception as e:
            return self._create_error_response("Failed to complete architectural conversation", e)
