// Documentation Registry
// This file acts as a simple database for the documentation files.
const DOC_REGISTRY = {
    "bouwblokken": [
        { name: "Bouwblok Definities", path: "bouwblokken/bouwblok_definities.md" },
        { name: "Build Plane", path: "bouwblokken/build_plane.md" },
        { name: "Compliance Layer", path: "bouwblokken/compliance_layer.md" },
        { name: "Druppie Core", path: "bouwblokken/druppie_core.md" },
        { name: "Druppie UI", path: "bouwblokken/druppie_ui.md" },
        { name: "Knowledge Bot", path: "bouwblokken/knowledge_bot.md" },
        { name: "Mens in de Loop", path: "bouwblokken/mens_in_de_loop.md" },
        { name: "Policy Engine", path: "bouwblokken/policy_engine.md" },
        { name: "Runtime", path: "bouwblokken/runtime.md" },
        { name: "Traceability DB", path: "bouwblokken/traceability_db.md" }
    ],
    "skills": [
        { name: "Mermaid Diagrams", path: "skills/mermaid.md" },
        { name: "Build Skill", path: "skills/build.md" },
        { name: "Deploy Skill", path: "skills/deploy.md" },
        { name: "Kubernetes Ops", path: "skills/kubernets.md" },
        { name: "Research Skill", path: "skills/research.md" },
        { name: "Test Skill", path: "skills/test.md" }
    ],
    "build_plane": [
        { name: "Build Plane", path: "build_plane/overview.md" },
        { name: "Builder Agent", path: "build_plane/builder_agent.md" },
        { name: "Foundry", path: "build_plane/foundry.md" }
    ],
    "runtime": [
        { name: "Runtime Info", path: "runtime/runtime.md" },
        { name: "Role Based Access Control (RBAC)", path: "runtime/rbac.md" },
        { name: "MCP Interface", path: "runtime/mcp_interface.md" },
        { name: "Dynamic Slot", path: "runtime/dynamic_slot.md" },
        { name: "Git", path: "runtime/git.md" }
    ],
    "compliance": [
        { name: "Overview", path: "compliance/overview.md" },
        { name: "IAM", path: "compliance/iam.md" }
    ],
    "general": [
        { name: "Project Readme", path: "README.md" }
    ]
};
