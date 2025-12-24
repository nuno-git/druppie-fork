# Agents Overview

This directory contains the definitions for the **Agents** in the Druppie ecosystem. 
Unlike static skills, Agents are autonomous entities configured with specific instructions, capabilities, and tools. Each agent file defines the **operational contract**, **standards**, and **processing logic** (state machine) that an Agent must follow.

By formalizing agents as specifications, we ensure:
- **Consistency**: All agents follow the same patterns (e.g., Mermaid-driven logic).
- **Quality**: Best practices (testing, security, compliance) are embedded in the agent definition.
- **Traceability**: Decisions and outputs can be mapped back to the requirements.

## Available Agents

| Agent | Description | Version |
| :--- | :--- | :--- |
| **[Architect Agent](./architect.md)** | Primary architecture agent using ArchiMate. Focuses on Enterprise and Solution Architecture. | 1.0.0 |
| **[Business Analyst](./business_analyst.md)** | Eliciting and structuring requirements. Translates vague intent into structured specs. | 1.0.0 |
| **[Data Scientist](./data_scientist.md)** | Spec-driven data science agent. Handles analysis, ML, and data pipelines. | 1.0.0 |
| **[Tester](./tester.md)** | QA and testing strategies. Ensures validation and verification. | 1.0.0 |

## Usage
These Markdown files are used to configure the Agent runtime. they contain:
- **Metadata**: Name, ID, Version, Model.
- **Instructions**: The system prompt defining the persona and behavior.
- **Configuration**: potentially tools and allowed skills (though mostly self-contained now).
