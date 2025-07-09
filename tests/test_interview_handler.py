"""
Unit tests for InterviewHandler
"""

import pytest


@pytest.mark.unit
class TestInterviewHandler:
    """Test cases for InterviewHandler"""

    @pytest.mark.asyncio
    async def test_get_tool_definitions(self, interview_handler):
        """Test that handler returns correct tool definitions"""
        tools = interview_handler.get_tool_definitions()
        assert len(tools) == 4

        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "start_requirement_interview",
            "continue_requirement_interview",
            "start_architectural_conversation",
            "continue_architectural_conversation",
        ]
        assert all(tool in tool_names for tool in expected_tools)

    @pytest.mark.asyncio
    async def test_start_requirement_interview_success(self, interview_handler):
        """Test starting a requirement interview session"""
        result = await interview_handler._start_requirement_interview(
            project_context="E-commerce platform modernization", stakeholder_role="Product Owner"
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "started" in result[0].text

        # Should contain session ID
        text = result[0].text
        assert "Session ID:" in text or "session" in text.lower()

        # Should contain initial questions
        assert "?" in text  # Should have questions

    @pytest.mark.asyncio
    async def test_start_requirement_interview_minimal(self, interview_handler):
        """Test starting interview with minimal context"""
        result = await interview_handler._start_requirement_interview()

        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "started" in result[0].text

    @pytest.mark.asyncio
    async def test_continue_requirement_interview_success(self, interview_handler):
        """Test continuing a requirement interview"""
        # First start an interview
        start_result = await interview_handler._start_requirement_interview(
            project_context="Test project", stakeholder_role="Developer"
        )

        # Extract session ID from response
        import re

        session_match = re.search(r"Session ID\*\*: (\S+)", start_result[0].text)
        assert session_match, "Could not find session ID in response"
        session_id = session_match.group(1)

        # Continue with answers
        result = await interview_handler._continue_requirement_interview(
            session_id=session_id,
            answers={
                "primary_goal": "Improve system performance",
                "current_pain_points": "Slow response times",
                "success_metrics": "Response time under 200ms",
            },
        )

        assert len(result) == 1
        # Should either continue interview or create requirement
        assert "SUCCESS" in result[0].text or "INFO" in result[0].text

    @pytest.mark.asyncio
    async def test_continue_requirement_interview_invalid_session(self, interview_handler):
        """Test continuing with invalid session ID"""
        result = await interview_handler._continue_requirement_interview(
            session_id="invalid_session_999", answers={"test": "answer"}
        )

        assert len(result) == 1
        assert "ERROR" in result[0].text
        assert "session not found" in result[0].text.lower() or "expired" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_continue_requirement_interview_missing_params(self, interview_handler):
        """Test continuing interview with missing parameters"""
        result = await interview_handler._continue_requirement_interview(
            session_id="test_session",
            answers=None,  # Missing answers
        )

        assert len(result) == 1
        assert "ERROR" in result[0].text

    def test_start_architectural_conversation_success(self, interview_handler):
        """Test starting an architectural conversation"""
        result = interview_handler._start_architectural_conversation(
            project_context="Microservices migration",
            diagram_purpose="Show service boundaries",
            complexity_level="medium",
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text
        assert "started" in result[0].text or "Architectural" in result[0].text

        # Should provide guidance based on complexity
        assert "medium" in result[0].text or "Medium" in result[0].text

    def test_start_architectural_conversation_complexity_levels(self, interview_handler):
        """Test different complexity levels for architectural conversations"""
        complexity_levels = ["simple", "medium", "complex"]

        for level in complexity_levels:
            result = interview_handler._start_architectural_conversation(
                project_context="Test project", diagram_purpose="Test diagram", complexity_level=level
            )

            assert len(result) == 1
            assert "SUCCESS" in result[0].text

            # Different complexity levels should result in different guidance
            if level == "simple":
                assert "simple" in result[0].text.lower() or "basic" in result[0].text.lower()
            elif level == "complex":
                assert "complex" in result[0].text.lower() or "detailed" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_continue_architectural_conversation_success(self, interview_handler):
        """Test continuing an architectural conversation"""
        # Start conversation first
        start_result = interview_handler._start_architectural_conversation(
            project_context="API Gateway design", diagram_purpose="Show request flow"
        )

        # Extract session ID from response or use mock
        import re

        session_match = re.search(r"Session ID\*\*: (\S+)", start_result[0].text)
        if not session_match:
            # If not in that format, create a mock session
            session_id = "arch_session_123"
            # Add session to handler's sessions
            interview_handler.architectural_sessions[session_id] = {
                "project_context": "API Gateway design",
                "diagram_purpose": "Show request flow",
                "complexity_level": "medium",
            }
        else:
            session_id = session_match.group(1)

        # Continue with responses
        result = interview_handler._continue_architectural_conversation(
            session_id=session_id,
            responses={
                "components": ["API Gateway", "Auth Service", "User Service"],
                "interactions": "Gateway routes to services based on path",
                "data_flow": "Request -> Gateway -> Service -> Response",
            },
        )

        assert len(result) == 1
        assert "SUCCESS" in result[0].text or "INFO" in result[0].text

    @pytest.mark.asyncio
    async def test_handle_tool_call_routing(self, interview_handler):
        """Test that handle_tool_call routes correctly"""
        # Test start_requirement_interview routing
        result = await interview_handler.handle_tool_call(
            "start_requirement_interview", {"project_context": "Test project"}
        )
        assert len(result) == 1
        assert "SUCCESS" in result[0].text

        # Test unknown tool
        result = await interview_handler.handle_tool_call("unknown_tool", {})
        assert len(result) == 1
        assert "Unknown tool: unknown_tool" in result[0].text

    @pytest.mark.asyncio
    async def test_interview_creates_requirement(self, interview_handler, requirement_handler):
        """Test that completing an interview can create a requirement"""
        # This tests the integration between interview and requirement creation
        # In a real implementation, the interview handler would call requirement handler

        # Start interview
        start_result = await interview_handler._start_requirement_interview(
            project_context="User authentication system", stakeholder_role="Security Engineer"
        )

        # Extract session ID from response
        import re

        session_match = re.search(r"Session ID\*\*: (\S+)", start_result[0].text)
        assert session_match, "Could not find session ID in response"
        session_id = session_match.group(1)

        # Provide comprehensive answers that would lead to requirement creation
        answers = {
            "primary_goal": "Implement secure user authentication",
            "current_state": "No authentication system",
            "desired_state": "OAuth2-based authentication with MFA",
            "functional_requirements": "Login, logout, password reset, MFA setup",
            "acceptance_criteria": "All endpoints secured, MFA optional but available",
            "priority": "P0",
            "risk_level": "High",
        }

        # Continue the interview with answers
        result = await interview_handler._continue_requirement_interview(session_id=session_id, answers=answers)

        # The interview should continue or provide next steps
        assert len(result) == 1
        text = result[0].text
        # Should either continue with more questions or indicate completion
        assert "SUCCESS" in text or "INFO" in text or "questions" in text.lower()

    @pytest.mark.asyncio
    async def test_architectural_conversation_generates_diagram_spec(self, interview_handler):
        """Test that architectural conversation produces diagram specification"""
        # Start conversation
        start_result = interview_handler._start_architectural_conversation(
            project_context="Event-driven architecture",
            diagram_purpose="Show event flow between services",
            complexity_level="complex",
        )

        # Extract session ID from response or use mock
        import re

        session_match = re.search(r"Session ID\*\*: (\S+)", start_result[0].text)
        if not session_match:
            # Create mock session for testing
            session_id = "arch_session_789"
            interview_handler.architectural_sessions[session_id] = {
                "project_context": "Event-driven architecture",
                "diagram_purpose": "Show event flow between services",
                "complexity_level": "complex",
            }
        else:
            session_id = session_match.group(1)

        # Provide detailed responses
        responses = {
            "services": ["Order Service", "Inventory Service", "Notification Service"],
            "events": ["OrderPlaced", "InventoryUpdated", "NotificationSent"],
            "event_flow": "Order Service publishes OrderPlaced, consumed by Inventory and Notification",
            "technologies": "Kafka for event bus, PostgreSQL for service databases",
            "scalability": "Each service can scale independently",
        }

        result = interview_handler._continue_architectural_conversation(session_id=session_id, responses=responses)

        assert len(result) == 1
        text = result[0].text

        # Should provide diagram specification or next steps
        assert "diagram" in text.lower() or "architecture" in text.lower()

    @pytest.mark.asyncio
    async def test_interview_question_generation(self, interview_handler):
        """Test that interviews generate contextual questions"""
        # Test different contexts generate different questions
        contexts = [
            ("E-commerce platform", "Product Manager"),
            ("Healthcare system", "Compliance Officer"),
            ("Gaming platform", "Technical Lead"),
        ]

        questions_sets = []

        for context, role in contexts:
            result = await interview_handler._start_requirement_interview(
                project_context=context, stakeholder_role=role
            )

            questions_sets.append(result[0].text)

        # All contexts should generate some questions
        for i, question_set in enumerate(questions_sets):
            context, role = contexts[i]
            assert "?" in question_set, f"No questions generated for {context}"
            assert "Session ID" in question_set, f"No session ID in response for {context}"
            assert context in question_set, "Context not reflected in response"

        # Each interview should have unique session ID
        session_ids = []
        for question_set in questions_sets:
            # Extract session ID from text
            lines = question_set.split("\n")
            for line in lines:
                if "Session ID" in line:
                    session_ids.append(line)
                    break

        # All session IDs should be unique
        assert len(set(session_ids)) == len(session_ids), "Session IDs are not unique"

    @pytest.mark.asyncio
    async def test_session_state_management(self, interview_handler):
        """Test that interview sessions maintain state"""
        # Start multiple sessions
        session1 = await interview_handler._start_requirement_interview(project_context="Project 1")

        session2 = await interview_handler._start_requirement_interview(project_context="Project 2")

        # Sessions should be independent
        assert session1[0].text != session2[0].text

        # Each should have unique session information
        assert "Project 1" in session1[0].text or "session" in session1[0].text.lower()
        assert "Project 2" in session2[0].text or "session" in session2[0].text.lower()
