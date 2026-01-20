"""LLM Service for code generation using actual LLM calls.

Uses Z.AI GLM API (OpenAI-compatible) for:
- Intent analysis (Router)
- Code generation (Agent)
"""

import os
import json
import re
from pathlib import Path
from typing import Any
from flask import current_app

import httpx
import structlog

logger = structlog.get_logger()


class ChatZAI:
    """Z.AI Chat Model using GLM API (OpenAI-compatible)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "GLM-4.7",
        base_url: str = "https://api.z.ai/api/coding/paas/v4",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or os.getenv("ZAI_API_KEY", "")
        self.model = model or os.getenv("ZAI_MODEL", "GLM-4.7")
        self.base_url = base_url or os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, messages: list[dict], **kwargs) -> str:
        """Send chat completion request and return content."""
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }

        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=headers)

            if response.status_code != 200:
                raise ValueError(f"Z.AI API error {response.status_code}: {response.text}")

            data = response.json()

        if not data.get("choices"):
            raise ValueError("No response from Z.AI")

        content = data["choices"][0].get("message", {}).get("content", "")
        return self._clean_response(content)

    def _clean_response(self, text: str) -> str:
        """Clean the response text (remove thinking blocks, code fences)."""
        text = text.strip()

        # Remove <think>...</think> blocks
        while "<think>" in text and "</think>" in text:
            start = text.find("<think>")
            end = text.find("</think>") + len("</think>")
            text = text[:start] + text[end:]

        text = text.strip()

        # Remove markdown code fences for JSON
        if text.startswith("```json"):
            text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
        elif text.startswith("```"):
            text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

        return text.strip()


# Router prompt for intent analysis
ROUTER_SYSTEM_PROMPT = """You are an intent analysis system for Druppie, a governance AI platform.

Analyze the user's request and classify it into ONE of these three actions:

1. create_project: User wants to BUILD something NEW
   - Create a new application, website, service, tool
   - Build a new feature from scratch
   - Start a new project
   - ONLY use this if user explicitly wants something NEW and it does NOT match an existing project

2. update_project: User wants to MODIFY something EXISTING
   - Fix a bug in existing code
   - Update or improve existing features
   - Refactor existing code
   - Add features to an existing project
   - User references a project by name or describes something similar to an existing project

3. general_chat: User is asking a question or having a conversation
   - Asking how something works
   - Requesting explanations
   - General questions not requiring code changes

IMPORTANT: When existing projects are provided in the context, you MUST:
- Check if the user's request matches or references any existing project
- If user mentions a project name that matches an existing project, use update_project
- If user describes features similar to an existing project, ask or assume update_project
- Set target_project_id to the matching project's ID when updating
- Only use create_project if the user explicitly wants a NEW project different from existing ones

Extract relevant project context:
- project_name: Name of the project (use existing name if updating)
- target_project_id: ID of existing project to update (null if creating new)
- app_type: Type of app (todo, calculator, blog, chat, counter, dashboard, api, etc.)
- technologies: Technologies to use (react, vue, flask, express, etc.)
- features: List of features requested

Respond ONLY with valid JSON:
{
    "action": "create_project|update_project|general_chat",
    "prompt": "Summarized intent",
    "answer": "Direct answer if general_chat, otherwise null",
    "project_context": {
        "project_name": "name of the project",
        "target_project_id": "id of existing project to update, or null",
        "app_type": "type of application",
        "technologies": ["list", "of", "techs"],
        "features": ["feature1", "feature2"]
    }
}"""

# Code generation prompt
CODE_GEN_SYSTEM_PROMPT = """You are an expert software developer. Generate complete, working code for the requested application.

You MUST respond with valid JSON containing all the files to create:

{
    "files": [
        {
            "path": "relative/path/to/file.ext",
            "content": "complete file content here"
        }
    ],
    "summary": "Brief description of what was created"
}

IMPORTANT:
- Generate COMPLETE, working code - not placeholders or stubs
- Include ALL necessary files (package.json, index.html, styles, etc.)
- For React/Vite apps: include package.json, vite.config.js, index.html, src/main.jsx, src/App.jsx, src/styles.css
- For Flask apps: include app.py, requirements.txt, templates/
- Make the app visually appealing with modern CSS
- The code should work immediately when run"""


class LLMService:
    """Service for LLM-based code generation using actual API calls."""

    def __init__(self):
        self.workspace_path = None
        self._llm = None

    def get_workspace_path(self) -> Path:
        """Get the workspace path from config."""
        if self.workspace_path is None:
            self.workspace_path = Path(
                current_app.config.get("WORKSPACE_PATH", "/app/workspace")
            )
        return self.workspace_path

    def get_llm(self) -> ChatZAI:
        """Get or create the LLM client."""
        if self._llm is None:
            self._llm = ChatZAI(
                api_key=os.getenv("ZAI_API_KEY"),
                model=os.getenv("ZAI_MODEL", "GLM-4.7"),
                base_url=os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"),
            )
        return self._llm

    def analyze_request(
        self,
        message: str,
        existing_projects: list[dict[str, Any]] | None = None,
        current_project: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze user request using LLM to determine what to build.

        Args:
            message: The user's request message
            existing_projects: Optional list of user's existing projects with keys:
                - id: Project ID
                - name: Project name
                - repo_url: Repository URL (optional)
                - description: Project description (optional)
            current_project: Optional current project context if user is working
                on a specific project (same structure as existing_projects items)

        Returns:
            dict with app_info including action, target_project_id for updates
        """
        logger.info(
            "analyzing_request",
            message=message[:100],
            existing_projects_count=len(existing_projects) if existing_projects else 0,
            has_current_project=current_project is not None,
        )

        try:
            llm = self.get_llm()

            # Build the user message with project context
            user_content = self._build_router_message(
                message, existing_projects, current_project
            )

            messages = [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ]

            response = llm.chat(messages)
            logger.debug("router_response", response=response[:500])

            # Parse JSON response
            data = self._parse_json(response)

            action = data.get("action", "general_chat")
            context = data.get("project_context", {})

            # Build app_info from context
            app_info = {
                "action": action,
                "app_type": context.get("app_type", "generic"),
                "name": context.get("project_name", "my-app"),
                "description": data.get("prompt", message),
                "features": context.get("features", []),
                "technologies": context.get("technologies", []),
                "target_project_id": context.get("target_project_id"),
                "answer": data.get("answer"),
            }

            logger.info(
                "request_analyzed",
                action=action,
                app_type=app_info["app_type"],
                name=app_info["name"],
                target_project_id=app_info.get("target_project_id"),
            )

            return app_info

        except Exception as e:
            logger.error("analyze_request_failed", error=str(e))
            # Fallback to basic extraction
            return {
                "action": "create_project",
                "app_type": "generic",
                "name": "my-app",
                "description": message,
                "features": [],
                "target_project_id": None,
            }

    def _build_router_message(
        self,
        message: str,
        existing_projects: list[dict[str, Any]] | None,
        current_project: dict[str, Any] | None,
    ) -> str:
        """Build the user message for the router with project context."""
        parts = []

        # Add current project context if available
        if current_project:
            parts.append("CURRENT PROJECT CONTEXT:")
            parts.append(f"- Name: {current_project.get('name', 'Unknown')}")
            parts.append(f"- ID: {current_project.get('id', 'Unknown')}")
            if current_project.get("repo_url"):
                parts.append(f"- Repo: {current_project['repo_url']}")
            if current_project.get("description"):
                parts.append(f"- Description: {current_project['description']}")
            parts.append("")

        # Add existing projects list if available
        if existing_projects:
            parts.append("USER'S EXISTING PROJECTS:")
            for proj in existing_projects[:10]:  # Limit to 10 projects for context
                proj_line = f"- {proj.get('name', 'Unknown')} (ID: {proj.get('id', 'Unknown')})"
                if proj.get("repo_url"):
                    proj_line += f" - {proj['repo_url']}"
                parts.append(proj_line)
            parts.append("")

        # Add the actual user message
        parts.append("USER REQUEST:")
        parts.append(message)

        return "\n".join(parts)

    def generate_app(
        self,
        plan_id: str,
        app_info: dict[str, Any],
        auto_commit: bool = True,
        auto_build: bool = False,
        auto_run: bool = False,
        created_by: str | None = None,
        username: str | None = None,
        email: str | None = None,
    ) -> dict[str, Any]:
        """Generate application files using LLM.

        Args:
            plan_id: Unique plan/project ID
            app_info: App configuration from analyze_request()
            auto_commit: Commit files to Git and push to Gitea
            auto_build: Build Docker image after generation
            auto_run: Run the Docker container after building
            created_by: User who created the project (Keycloak sub ID)
            username: Keycloak username for Gitea account
            email: User's email for Gitea account

        Returns:
            Result dict with success status, files, repo_url, app_url, etc.
        """
        from .project import project_service
        from .builder import builder_service

        workspace = self.get_workspace_path() / plan_id
        workspace.mkdir(parents=True, exist_ok=True)

        app_type = app_info.get("app_type", "generic")
        app_name = app_info.get("name", "my-app")
        description = app_info.get("description", "")
        features = app_info.get("features", [])

        logger.info(
            "generating_app",
            plan_id=plan_id,
            app_type=app_type,
            app_name=app_name,
        )

        # Generate code using LLM
        try:
            files_created = self._generate_code_with_llm(
                workspace, app_type, app_name, description, features
            )
        except Exception as e:
            logger.error("llm_generation_failed", error=str(e))
            # Fallback to templates
            files_created = self._generate_fallback(workspace, app_type, app_name, description)

        result = {
            "success": True,
            "workspace": str(workspace),
            "files_created": files_created,
            "app_info": app_info,
        }

        # Create project with Gitea repo (private, under user's account)
        if auto_commit:
            try:
                project = project_service.create_project(
                    name=app_name,
                    description=description,
                    created_by=created_by,
                    plan_id=plan_id,
                    username=username,
                    email=email,
                )

                # Commit and push to Gitea
                if project_service.commit_and_push(
                    project,
                    message=f"Initial commit: {app_name}",
                    author=created_by,
                ):
                    result["repo_url"] = project.repo_url
                    result["project"] = project.to_dict()

            except Exception as e:
                logger.error("git_commit_failed", error=str(e))
                result["git_error"] = str(e)

        # Build Docker image
        if auto_build:
            try:
                build_result = builder_service.build_project(plan_id)
                result["build"] = build_result

                # Run container if requested
                if auto_run and build_result.get("success"):
                    run_result = builder_service.run_project(plan_id)
                    result["run"] = run_result
                    if run_result.get("success"):
                        result["app_url"] = run_result.get("url")

            except Exception as e:
                logger.error("build_failed", error=str(e))
                result["build_error"] = str(e)

        logger.info(
            "app_generated",
            plan_id=plan_id,
            files_count=len(files_created),
            has_repo=bool(result.get("repo_url")),
        )

        return result

    def _generate_code_with_llm(
        self,
        workspace: Path,
        app_type: str,
        app_name: str,
        description: str,
        features: list[str],
    ) -> list[str]:
        """Generate code using LLM."""
        llm = self.get_llm()

        # Build the generation prompt
        features_str = "\n".join(f"- {f}" for f in features) if features else "Basic functionality"

        user_prompt = f"""Create a complete {app_type} application called "{app_name}".

Description: {description}

Features:
{features_str}

Requirements:
- Generate a complete, working application
- Use modern best practices
- Make it visually appealing with CSS
- Include all necessary files to run the app
- For web apps, use React with Vite OR plain HTML/CSS/JS
- For Python apps, use Flask

Generate ALL the files needed."""

        messages = [
            {"role": "system", "content": CODE_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        logger.info("calling_llm_for_code_generation", app_type=app_type)
        response = llm.chat(messages)
        logger.debug("code_gen_response_length", length=len(response))

        # Parse the response
        data = self._parse_json(response)
        files = data.get("files", [])

        if not files:
            raise ValueError("No files generated by LLM")

        # Write files to workspace
        files_created = []
        for file_info in files:
            file_path = file_info.get("path", "")
            content = file_info.get("content", "")

            if not file_path or not content:
                continue

            # Create directories if needed
            full_path = workspace / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            full_path.write_text(content)
            files_created.append(file_path)
            logger.debug("file_written", path=file_path)

        logger.info("files_generated", count=len(files_created))
        return files_created

    def _generate_fallback(
        self,
        workspace: Path,
        app_type: str,
        app_name: str,
        description: str,
    ) -> list[str]:
        """Generate fallback template when LLM fails."""
        logger.warning("using_fallback_template", app_type=app_type)

        files = []

        # Simple HTML/CSS/JS app as fallback
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{app_name}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">
        <h1>{app_name}</h1>
        <p>{description}</p>
        <div id="app"></div>
    </div>
    <script src="app.js"></script>
</body>
</html>
"""
        (workspace / "index.html").write_text(index_html)
        files.append("index.html")

        styles_css = """* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    padding: 2rem;
}

.container {
    max-width: 800px;
    margin: 0 auto;
    background: white;
    padding: 2rem;
    border-radius: 16px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
}

h1 {
    color: #333;
    margin-bottom: 1rem;
}

p {
    color: #666;
    margin-bottom: 1.5rem;
}

#app {
    padding: 1rem;
    background: #f5f5f5;
    border-radius: 8px;
}
"""
        (workspace / "styles.css").write_text(styles_css)
        files.append("styles.css")

        app_js = """// App initialization
document.addEventListener('DOMContentLoaded', function() {
    const app = document.getElementById('app');
    app.innerHTML = '<p>App is ready! Add your functionality here.</p>';
});
"""
        (workspace / "app.js").write_text(app_js)
        files.append("app.js")

        readme = f"""# {app_name}

{description}

## Getting Started

Open `index.html` in your browser.

Generated by Druppie Governance Platform.
"""
        (workspace / "README.md").write_text(readme)
        files.append("README.md")

        return files

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from LLM response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            return {}
