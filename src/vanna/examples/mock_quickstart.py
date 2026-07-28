"""
Mock quickstart example for the Vanna Agents framework.

This example shows how to create a basic agent with a mock LLM service
and have a simple conversation.

Usage:
  Template: Copy this file and modify for your needs
  Interactive: python -m vanna.examples.mock_quickstart
  REPL: from vanna.examples.mock_quickstart import create_demo_agent
  Server: python -m vanna.servers --example mock_quickstart
"""

import asyncio

from vanna import (
    AgentConfig,
    Agent,
    MemoryConversationStore,
    MockLlmService,
    User,
)
from vanna.core.registry import ToolRegistry
from vanna.core.user import RequestContext, UserResolver
from vanna.integrations.local.agent_memory import DemoAgentMemory


class DemoUserResolver(UserResolver):
    """Resolve every demo request to a local, non-privileged user."""

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="demo-user",
            username="demo",
            email="demo@example.com",
            group_memberships=[],
        )


def create_demo_agent() -> Agent:
    """Create a demo agent for REPL and server usage.

    Returns:
        Configured Agent instance
    """
    llm_service = MockLlmService(
        response_content="Hello! I'm a helpful AI assistant created using the Vanna Agents framework."
    )

    return Agent(
        llm_service=llm_service,
        tool_registry=ToolRegistry(),
        user_resolver=DemoUserResolver(),
        agent_memory=DemoAgentMemory(),
        config=AgentConfig(
            stream_responses=True,  # Enable streaming for better server experience
            include_thinking_indicators=True,
        ),
    )


async def main() -> None:
    """Run the mock quickstart example."""

    # Create agent using factory function
    agent = create_demo_agent()

    request_context = RequestContext(cookies={}, headers={})

    # Start a conversation
    conversation_id = "conversation123"
    user_message = "Hello! Can you introduce yourself?"

    print(f"User: {user_message}")
    print("Agent: ", end="")

    # Send message and collect response
    async for component in agent.send_message(
        request_context=request_context,
        message=user_message,
        conversation_id=conversation_id,
    ):
        if hasattr(component, "content"):
            print(component.content, end="")

    print()


def run_interactive() -> None:
    """Entry point for interactive usage."""
    print("Starting Vanna Agents mock quickstart demo...")
    asyncio.run(main())


if __name__ == "__main__":
    run_interactive()
