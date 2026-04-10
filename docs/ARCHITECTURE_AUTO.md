# Platform Architectuur (Auto-generated)

> Dit bestand wordt automatisch gegenereerd na elke core update.
> Laatst bijgewerkt: 2026-04-10 12:15

---

## Agents (13)

| Agent | Categorie | Beschrijving | MCP Servers | Max Iterations |
|-------|-----------|-------------|-------------|----------------|
| **Architect Agent** | execution | Designs system architecture, validates functional designs against NORA and Water | coding, registry, archimate | 50 |
| **Builder Agent** | execution | Implements code to make tests pass following TDD methodology | coding | 100 |
| **Builder Planner Agent** | quality | Creates detailed implementation plans (code standards, test strategy, solution a | coding | 30 |
| **Business Analyst Agent** | execution | Specialized in eliciting requirements, uncovering root problems, and translating | coding, registry | 50 |
| **Deployer Agent** | deployment | Handles Docker build and deployment | docker, coding | 100 |
| **Developer Agent** | execution | Writes and modifies code in git-managed workspaces | coding | 100 |
| **Planner Agent** | system | Creates execution plans and re-evaluates progress in a loop | - | 15 |
| **Reviewer Agent** | quality | Reviews code and provides feedback | coding | 50 |
| **Router Agent** | system | Analyzes user intent and routes to appropriate action | web | 10 |
| **Summarizer Agent** | execution | Creates a user-friendly completion message from agent run summaries | - | 5 |
| **Test Builder Agent** | quality | Generates comprehensive tests following TDD methodology (Red Phase) | coding | 30 |
| **Test Executor Agent** | quality | Runs tests and reports results (Green Phase verification) | coding | 25 |
| **Update Core Builder Agent** | execution | Implements changes to Druppie's own codebase and creates a PR for review | coding | 100 |

## MCP Servers (6)

### Coding (`http://module-coding:9001`)

- **Tools**: 21 (read_file, write_file, make_design, batch_write_files, list_dir, delete_file, run_git, run_tests, get_test_framework, get_coverage_report, create_pull_request, merge_pull_request, install_test_dependencies, validate_tdd, get_git_status, list_projects, read_project_file, list_project_files, validate_design, _internal_revert_to_commit, _internal_close_pull_request)
- **Approval vereist**: merge_pull_request

### Docker (`http://module-docker:9002`)

- **Tools**: 10 (build, run, stop, logs, remove, list_containers, inspect, exec_command, compose_up, compose_down)
- **Approval vereist**: build, run, remove, exec_command, compose_up, compose_down

### Filesearch (`http://module-filesearch:9004`)

- **Tools**: 4 (search_files, list_directory, read_file, get_search_stats)

### Web (`http://module-web:9005`)

- **Tools**: 6 (search_files, list_directory, read_file, fetch_url, search_web, get_page_info)

### Archimate (`http://module-archimate:9006`)

- **Tools**: 8 (list_models, get_statistics, list_elements, get_element, list_views, get_view, search_model, get_impact)

### Registry (`http://module-registry:9007`)

- **Tools**: 6 (list_modules, get_module, search_modules, list_components, get_agent, get_skill)

## Agent Categorieën

- **System** (2): Planner Agent, Router Agent
- **Execution** (6): Architect Agent, Builder Agent, Business Analyst Agent, Developer Agent, Summarizer Agent, Update Core Builder Agent
- **Quality** (4): Builder Planner Agent, Reviewer Agent, Test Builder Agent, Test Executor Agent
- **Deployment** (1): Deployer Agent
