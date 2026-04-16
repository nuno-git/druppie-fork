"""Deploy the Vergunning Vinder agent to Azure AI Foundry.

Reads finder-agent.yaml and deploys it to the druppie-resource Foundry project
using the azure-ai-projects SDK.

Usage:
    python deploy-finder-agent.py

Requires:
    - FOUNDRY_PROJECT_ENDPOINT set in .env
    - FOUNDRY_API_KEY set in .env (or az login for DefaultAzureCredential)
    - pip install azure-ai-projects azure-identity python-dotenv pyyaml
"""

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = Path(__file__).parent
AGENT_YAML = SCRIPT_DIR / "finder-agent.yaml"


def main():
    # Load agent definition from YAML
    with open(AGENT_YAML) as f:
        agent_def = yaml.safe_load(f)

    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    api_key = os.environ.get("FOUNDRY_API_KEY")

    if not endpoint:
        print("ERROR: FOUNDRY_PROJECT_ENDPOINT is not set in .env")
        sys.exit(1)

    # Initialize client — agents API requires token-based auth
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(),
    )
    print(f"Authenticated with DefaultAzureCredential to {endpoint}")

    # Build tools
    from azure.ai.projects.models import (
        BingGroundingTool,
        PromptAgentDefinition,
    )

    tool_map = {
        "bing_grounding": BingGroundingTool,
    }

    tools = []
    for tool_name in agent_def.get("tools", []):
        tool_cls = tool_map.get(tool_name)
        if tool_cls:
            tools.append(tool_cls())
            print(f"  Tool: {tool_name}")
        else:
            print(f"  WARNING: Unknown tool '{tool_name}', skipping")

    # If Bing Grounding connection is not yet configured in the Foundry
    # portal, deploy without tools first. The tool can be added later
    # by re-running this script once the connection exists.
    if "--no-tools" in sys.argv:
        print("  NOTE: --no-tools flag set, deploying without tools")
        tools = []

    # Build agent definition
    model_id = agent_def["model"]["id"]
    instructions = agent_def["instructions"]
    agent_name = agent_def["name"]

    definition = PromptAgentDefinition(
        model=model_id,
        instructions=instructions,
        tools=tools if tools else None,
    )

    print(f"\nDeploying agent '{agent_name}'...")
    print(f"  Model: {model_id}")
    print(f"  Tools: {[t for t in agent_def.get('tools', [])]}")

    # Deploy
    result = client.agents.create_version(
        agent_name=agent_name,
        definition=definition,
    )

    print(f"\nSUCCESS: Agent deployed!")
    print(f"  Agent ID: {result.id}")
    print(f"  Name: {result.name}")
    print(f"  Version: {getattr(result, 'version', 'N/A')}")


if __name__ == "__main__":
    main()
