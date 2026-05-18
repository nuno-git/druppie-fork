"""Test script for CAO/WAZO MCP server connection."""

import asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def test_cao_wazo_mcp():
    """Test connection to CAO/WAZO MCP server."""

    server_url = "https://cao-wazo-mcp.salmonbay-a93ad59f.westeurope.azurecontainerapps.io/mcp"
    api_key = "KeKGUzXmY0HN7WTSwn7eAQeaTfVrp4fDF57DKbqpKR3M6vr53ScJjsK1URkUswUb"

    print(f"Testing connection to: {server_url}")
    print(f"API Key: {api_key[:20]}...")

    # Try with different auth methods
    methods = [
        ("No auth", {}),
        ("Bearer header", {"headers": {"Authorization": f"Bearer {api_key}"}}),
        ("X-API-Key header", {"headers": {"X-API-Key": api_key}}),
    ]

    for method_name, kwargs in methods:
        print(f"\n{'='*60}")
        print(f"Testing: {method_name}")
        print(f"{'='*60}")

        try:
            # Create transport with custom kwargs
            transport = StreamableHttpTransport(server_url, **kwargs)
            client = Client(transport)

            async with client:
                # List available tools
                tools = await client.list_tools()
                print(f"✓ Connection successful!")
                print(f"  Available tools ({len(tools)}):")
                for tool in tools:
                    print(f"    - {tool.name}: {tool.description[:80] if tool.description else 'No description'}...")

                # Test calling a tool
                if tools:
                    test_tool = tools[0].name
                    print(f"\n  Testing tool: {test_tool}")

                    try:
                        # Try calling with a simple test question
                        result = await client.call_tool(
                            test_tool,
                            {"question": "Wat zijn de werktijden?"}
                        )
                        print(f"  ✓ Tool call successful!")
                        print(f"  Result preview: {str(result)[:200]}...")
                    except Exception as e:
                        print(f"  ✗ Tool call failed: {e}")

        except Exception as e:
            print(f"✗ Connection failed: {type(e).__name__}: {e}")

    print(f"\n{'='*60}")
    print("Test complete")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(test_cao_wazo_mcp())