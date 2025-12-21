// Documentation Registry
// This file acts as a simple database for the documentation files.
const DOC_REGISTRY = {
    "bouwblokken": [
        { name: "Overview", path: "bouwblokken/overview.md" },
        { name: "Bouwblok Definities", path: "bouwblokken/bouwblok_definities.md" },
        { name: "CI/CD Pipeline (Tekton)", path: "bouwblokken/ci_cd_tekton.md" },
        { name: "Database (PostgreSQL)", path: "bouwblokken/database_postgres.md" },
        { name: "Vector Database (Qdrant)", path: "bouwblokken/database_qdrant.md" },
        { name: "Geo-Database (PostGIS)", path: "bouwblokken/database_postgis.md" },
        { name: "Webserver & Certificaten (Ingress)", path: "bouwblokken/webserver_ingress.md" },
        { name: "GitOps & State (Flux)", path: "bouwblokken/gitops_flux.md" },
        { name: "Observability (PLG Stack)", path: "bouwblokken/observability_plg.md" },
        { name: "Git & Versiebeheer (Gitea)", path: "bouwblokken/git_gitea.md" },
        { name: "Traceability (Tempo & OTEL)", path: "bouwblokken/traceability_otel.md" },
        { name: "IAM (Keycloak & Azure AD)", path: "bouwblokken/iam_keycloak.md" },
        { name: "MCP Server Host", path: "bouwblokken/mcp_server.md" },
        { name: "Data Lake (MinIO)", path: "bouwblokken/data_lake_minio.md" },
        { name: "AI Dataset Versioning (DVC)", path: "bouwblokken/data_versioning_dvc.md" },
        { name: "Drone Mapping (WebODM)", path: "bouwblokken/drone_pipeline_odm.md" },
        { name: "AI Anonymizer (YOLOv8)", path: "bouwblokken/ai_anonymizer_yolo.md" },
        { name: "Workflow Engine (Argo)", path: "bouwblokken/workflow_argo.md" },
        { name: "API Gateway (Kong)", path: "bouwblokken/api_gateway_kong.md" },
        { name: "Architectuur (Archi)", path: "bouwblokken/architecture_archi.md" },
        { name: "GIS Desktop (QGIS)", path: "bouwblokken/gis_qgis.md" },
        { name: "GIS Server (GeoServer)", path: "bouwblokken/gis_geoserver.md" },
        { name: "GIS Portal (GeoNode)", path: "bouwblokken/gis_geonode.md" },
        { name: "Build Plane", path: "bouwblokken/build_plane.md" },
        { name: "Scanning & Compliance (Trivy)", path: "bouwblokken/security_scanning_trivy.md" },
        { name: "Code Quality (SonarQube)", path: "bouwblokken/code_quality_sonarqube.md" },
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
        { name: "Overview", path: "skills/overview.md" },
        { name: "Mermaid Diagrams", path: "skills/mermaid.md" },
        { name: "Kubernetes Ops", path: "skills/kubernets.md" },
        { name: "Test Skill", path: "skills/test.md" },
        { name: "Node.js Skill", path: "skills/nodejs.md" },
        { name: "Python Skill", path: "skills/python.md" },
        { name: "Architect Skill", path: "skills/architect.md" },
        { name: "Business Analyst Skill", path: "skills/business_analyst.md" }
    ],
    "build_plane": [
        { name: "Overview", path: "build_plane/overview.md" },
        { name: "Builder Agent", path: "build_plane/builder_agent.md" },
        { name: "Foundry", path: "build_plane/foundry.md" }
    ],
    "runtime": [
        { name: "Overview", path: "runtime/overview.md" },
        { name: "Policy Engine (Kyverno)", path: "runtime/policy_kyverno.md" },
        { name: "Runtime Info", path: "runtime/runtime.md" },
        { name: "Role Based Access Control (RBAC)", path: "runtime/rbac.md" },
        { name: "MCP Interface", path: "runtime/mcp_interface.md" },
        { name: "Dynamic Slot", path: "runtime/dynamic_slot.md" },
        { name: "Git", path: "runtime/git.md" }
    ],
    "compliance": [
        { name: "Overview", path: "compliance/overview.md" },
        { name: "BIO & NIS2", path: "compliance/bio_nis2.md" },
        { name: "Data Act", path: "compliance/data_act.md" },
        { name: "AI Act (EU & UvW)", path: "compliance/ai_act.md" },
        { name: "AI Register (Algoritmeregister)", path: "compliance/ai_register.md" },
        { name: "Goed Bestuur (Code)", path: "compliance/good_governance.md" },
        { name: "IAM", path: "compliance/iam.md" }
    ],
    "mcp_catalog": [
        { name: "Overview", path: "mcp/overview.md" },
        { name: "Microsoft & Azure", path: "mcp/microsoft.md" },
        { name: "Open Source Tools", path: "mcp/opensource.md" }
    ],
    "ontwerpen": [
        { name: "Overview", path: "design/overview.md" },
        { name: "Hybride Architectuur (K8s)", path: "design/hybrid_cluster_architecture.md" },
        { name: "Component Interactie (Build->Run)", path: "design/component_interaction.md" },
        { name: "Data Lifecycle & Versiebeheer", path: "design/data_lifecycle_drone.md" },
        { name: "Deployment & Rolling Updates", path: "design/deployment_strategies.md" },
        { name: "Automated Rebuild (Watchdog)", path: "design/automated_rebuild.md" },
        { name: "Secure Agentic RAG Network", path: "design/agentic_rag_network.md" },
        { name: "Continuous Compliance & Lifecycle", path: "design/compliance_lifecycle_monitoring.md" },
        { name: "Automated Testing & Documentation", path: "design/automated_testing_docs.md" }
    ],
    "scripts": [
        { name: "Overview", path: "script/overview.md" }
    ],
    "general": [
        { name: "Project Readme", path: "README.md" },
        { name: "License (MIT)", path: "LICENSE.md" },
        { name: "Het Verhaal Druppie", path: "story/story.md" }
    ]
};
