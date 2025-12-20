# Skills Overview

This directory contains the **Skill Definitions** for the Druppie platform.
Skills are specialized capabilities that Agents possess. Each skill file defines the **operational contract**, **standards**, and **processing logic** (state machine) that an Agent must follow when performing tasks related to that domain.

By formalizing skills as specifications, we ensure:
- **Consistency**: All agents follow the same patterns (e.g., Mermaid-driven logic).
- **Quality**: Best practices (testing, security, compliance) are embedded in the skill definition.
- **Traceability**: Decisions and outputs can be mapped back to the skill's requirements.

---

## 🏗️ Role-Based Skills

These skills simulate specific human roles within a project team, focusing on process and methodology.

- **[Architect (ArchiMate)](./architect.md)**
  - **Focus**: Enterprise and Solution Architecture, ArchiMate modeling.
  - **Key Outputs**: Architecture packages, ArchiMate diagrams, ADRs (Architecture Decision Records), Roadmaps.
  - **Logic**: From Intake to Motivation Modeling, Baseline/Target analysis, and Governance.

- **[Business Analyst](./business_analyst.md)**
  - **Focus**: Requirements gathering, stakeholder analysis, and user story definition.
  - **Key Outputs**: User stories, Acceptance Criteria, Process flows, Requirement specs.
  - **Logic**: Translates vague intent into structured, testable requirements.

- **[Test / QA](./test.md)**
  - **Focus**: Validation, verification, and quality assurance.
  - **Key Outputs**: Test plans, Test cases, Defect reports, Quality assessments.
  - **Logic**: Ensures requirements are met through rigorous testing cycles (from Unit to E2E).

---

## 💻 Tech Stack Skills

These skills provide deep technical expertise in specific programming languages and runtime environments.

- **[Node.js](./nodejs.md)**
  - **Focus**: Backend development, APIs, CLI tools, and web services.
  - **Standards**: TypeScript-first, ESM, strict linting/testing.
  - **Key Outputs**: Production-ready code, Dockerfiles, CI workflows, Kubernetes manifests.

- **[Python (Data Science)](./python.md)**
  - **Focus**: Data Science, Machine Learning, Data Engineering, and Analysis.
  - **Standards**: Reproducible environments (poetry/uv), Data validation, Notebook-to-Production pipelines.
  - **Key Outputs**: Python packages, Analysis notebooks, Trained models, Validation reports.

- **[Kubernetes Ops](./kubernets.md)**
  - **Focus**: Runtime operations, deployment configuration, and cluster management.
  - **Key Outputs**: Manifests (Deployment, Service, Ingress), Helm charts, Kustomize configurations.
  - **Logic**: Manages the deployment lifecycle and runtime stability.

---

## 🧠 Core Capabilities

Foundational skills that support the logic or communication of other agents.

- **[Mermaid Diagrams](./mermaid.md)**
  - **Focus**: Visualizing logic, workflows, and state machines.
  - **Usage**: Used by *all* other skills to visualize their internal state machine and decision logic.
  - **Key Outputs**: Flowcharts, Sequence diagrams, State diagrams.

---

## 🚀 How to use a Skill

When an Agent adopts a skill (e.g., "Act as a Node.js Developer"), it loads the corresponding `.md` file and adheres to the **Operational Contract** defined therein:

1.  **Check Inputs**: Does the request match the `Input` scope?
2.  **Follow State Machine**: Execute the steps defined in the `Processing Logic` (often visualized with Mermaid).
3.  **Enforce Standards**: Apply the `Required Standards` (coding style, testing, patterns).
4.  **Produce Outputs**: Generate the artifacts listed in the `Output` section.
