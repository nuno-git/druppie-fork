# Druppie MCP Module Structure Guide

This document explains how MCP modules are structured in Druppie and how to add a new module (e.g., TTS - Text-to-Speech).

## 1. Where MCP Modules Are Defined and Registered

### Module Location
- **Server code**: `druppie/mcp-servers/<module-name>/`
  - Each module is a separate directory under `druppie/mcp-servers/`
  - Examples: `coding/`, `web/`, `docker/`, `archimate/`, `filesearch/`

### Configuration Registration

**Two-tier registration system**:

1. **Module Deployment (Docker Compose)**: Each module has a corresponding service in `docker-compose.yml`
2. **Tool Configuration (mcp_config.yaml)**: Defines all tools, approval requirements, and injection rules

#### 1.1 Docker Compose Registration

Each MCP module requires:
- Service definition with build context
- Environment variables
- Port mapping (for internal communication)

Example from `docker-compose.yml`:
```yaml
mcp-tts:
  build:
    context: ./druppie/mcp-servers/tts
    dockerfile: Dockerfile
  container_name: druppie-mcp-tts
  profiles: [infra, dev, prod]
  environment:
    MCP_PORT: "9008"
    # Module-specific env vars
  ports:
    - "9008:9008"
  volumes:
    # Module-specific volumes (if any)
```

#### 1.2 Tool Configuration Registration

**File**: `druppie/core/mcp_config.yaml`

Each module must be added to the `mcps` section with:
- URL (with environment variable substitution)
- Description
- Injection rules (for automatic parameter injection)
- Tool definitions with approval requirements

Example for a TTS module:
```yaml
mcps:
  tts:
    url: ${MCP_TTS_URL:-http://mcp-tts:9008}
    description: "Text-to-Speech module for audio synthesis"
    inject:
      # Define parameters that should be auto-injected from context
      voice_id:
        from: session.preferences.voice
        hidden: true
        tools: [speak, speak_batch]
    tools:
      - name: speak
        description: "Convert text to speech and play audio"
        requires_approval: false
        parameters:
          type: object
          properties:
            text:
              type: string
              description: "Text to speak"
            voice_id:
              type: string
              description: "Voice identifier (e.g., 'en-US-AriaNeural')"
              default: "en-US-AriaNeural"
            rate:
              type: number
              description: "Speech rate (0.5-2.0, default 1.0)"
          required:
            - text
```

### Agent Integration

Agents specify which MCPs and tools they can use in their YAML definitions:

```yaml
# agents/definitions/analyst.yaml
mcps:
  tts: [speak, speak_batch]
  coding: [read_file, write_file]
```

### Approval System

Tools can have approval requirements (both global defaults and agent-specific overrides):

```yaml
tools:
  - name: speak
    requires_approval: true  # Global default
    required_role: developer  # Only developers can approve

# Or agent-specific override:
# approval_overrides:
#   tts:speak:
#     requires_approval: false
#     required_role: None
```

## 2. File Structure of an Existing Module

### Example Module: `web` (bestand-zoeker)

```
druppie/mcp-servers/web/
├── server.py           # FastMCP server entry point
├── module.py           # Business logic module
├── Dockerfile          # Container build instructions
├── requirements.txt    # Python dependencies
└── puppeteer-config.json  # Optional: configuration for browser automation
```

### Example Module: `coding`

```
druppie/mcp-servers/coding/
├── server.py              # FastMCP server (300+ lines, most complex)
├── module.py              # Business logic
├── mermaid_validator.py   # Validation logic
├── retry_module.py        # Retry/revert utilities
├── testing_module.py      # Test execution logic
├── Dockerfile
└── requirements.txt
```

### Detailed File Descriptions

#### 2.1 `server.py` - FastMCP Server Entry Point

**Purpose**: Creates the FastMCP server, defines tools with decorators.

**Key Elements**:
```python
from fastmcp import FastMCP
from module import WebModule

# Create server with metadata
mcp = FastMCP("Bestand Zoeker MCP Server")

# Initialize business logic
module = WebModule(search_root=SEARCH_ROOT)

# Define tools
@mcp.tool()
async def fetch_url(url: str) -> dict:
    """Fetch and return content from a URL."""
    return await module.fetch_url(url=url)

@mcp.tool()
async def search_web(query: str, num_results: int = 5) -> dict:
    """Search web for information."""
    return await module.search_web(query=query, num_results=num_results)

if __name__ == "__main__":
    # HTTP server configuration
    import uvicorn
    from starlette.routing import Route
    from starlette.responses import JSONResponse

    app = mcp.http_app()

    async def health(request):
        return JSONResponse({"status": "healthy", "service": "bestand-zoeker"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9004"))

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
```

**Key Patterns**:
- Uses FastMCP's `@mcp.tool()` decorator
- Tools are async functions (for network calls)
- Returns dictionaries with success/error status
- Includes health check endpoint
- Environment variable for port configuration

#### 2.2 `module.py` - Business Logic

**Purpose**: Contains all business logic, independent of FastMCP/HTTP.

**Key Elements**:
```python
class WebModule:
    """Business logic module for web operations."""

    def __init__(self, search_root):
        self.search_root = Path(search_root)

    async def fetch_url(self, url: str) -> dict:
        """Fetch and return content from a URL."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(url)

                return {
                    "success": True,
                    "url": url,
                    "status_code": response.status_code,
                    "content": response.text[:10000],
                }
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url,
            }

    # Other methods...
```

**Best Practices**:
- No dependencies on FastMCP, Starlette, or HTTP frameworks
- Pure Python business logic
- Async methods where applicable
- Proper error handling with return status dictionaries
- Logging for debugging

#### 2.3 `Dockerfile`

**Purpose**: Container definition for the MCP server.

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server.py .
COPY module.py .

# Run the server
CMD ["python", "server.py"]
```

**Note**: For modules needing Docker daemon access (like `docker` module), you need to:
```dockerfile
# Add volume mount for Docker socket
RUN apt-get install -y docker.io
VOLUME /var/run/docker.sock
```

#### 2.4 `requirements.txt`

**Purpose**: Python dependencies for the module.

Example:
```
fastmcp>=2.0.0,<3.0.0
httpx>=0.25.0
uvicorn>=0.24.0
# Module-specific dependencies
pydub>=0.25.0
numpy>=1.24.0
```

## 3. Configuration Files and Schemas Required

### 3.1 mcp_config.yaml (Tool Configuration)

**Location**: `druppie/core/mcp_config.yaml`

**Required Sections**:
1. **Module URL**: Environment variable substitution with default
2. **Description**: Human-readable description
3. **Injection Rules**: Auto-inject parameters from context (optional)
4. **Tool Definitions**: Each tool with approval requirements and parameters

**Schema Example**:
```yaml
mcps:
  <module-name>:
    url: ${MCP_<MODULE>_URL:-http://mcp-<module>:<port>}
    description: "<Human-readable description>"
    inject:
      <param_name>:
        from: <context.path>
        hidden: <true|false>
        tools: [<tool1>, <tool2>]
    tools:
      - name: <tool_name>
        description: "<Tool description>"
        requires_approval: <true|false>
        required_role: "<role_name>"
        parameters:
          type: object
          properties:
            <param_name>:
              type: <string|number|boolean|array|object>
              description: "<Description>"
              default: "<default_value>"
              enum: ["value1", "value2"]  # Optional
          required:
            - <required_param>
```

### 3.2 docker-compose.yml (Service Configuration)

**Required Sections**:
1. **Service name**: `mcp-<module-name>`
2. **Build context**: Path to module directory
3. **Environment variables**: Module-specific configs
4. **Port mapping**: For internal communication
5. **Volumes**: Optional, for filesystem access
6. **Profiles**: Should use `[infra, dev, prod]`

**Schema Example**:
```yaml
mcp-tts:
  build:
    context: ./druppie/mcp-servers/tts
    dockerfile: Dockerfile
  container_name: druppie-mcp-tts
  profiles: [infra, dev, prod]
  environment:
    MCP_PORT: "9008"
    VOICE_PROVIDER: "azure"  # Module-specific
    AZURE_API_KEY: "${AZURE_API_KEY}"
  ports:
    - "9008:9008"
  volumes:
    # Optional: data persistence
    - tts_cache:/cache
```

### 3.3 Agent YAML (Tool Access)

**Required Sections**:
1. **MCPs list**: Which MCPs and tools the agent can use

```yaml
# Example for analyst agent
mcps:
  tts: [speak, speak_batch]
  web: [search_web, fetch_url]
  coding: [read_file]
```

## 4. How MCP Module Works End-to-End

### 4.1 Module Initialization

1. **Container starts**:
   ```bash
   docker compose --profile dev up -d mcp-tts
   ```

2. **Server starts**:
   - Reads environment variables
   - Initializes business logic module
   - Registers FastMCP server
   - Exposes HTTP endpoints at `http://mcp-tts:9008/mcp`

3. **MCP discovery**:
   - Agent requests tools via `tools/list`
   - FastMCP returns registered tools with schemas

### 4.2 Tool Execution Flow

1. **Agent decides to use a tool** (e.g., `tts:speak`)
2. **Approval check**:
   - Agent definition checked for `approval_overrides`
   - Falls back to `mcp_config.yaml` defaults
3. **Parameter injection**:
   - Hidden parameters filled from context (session, project)
4. **HTTP call to MCP server**:
   - FastMCP Client → `http://mcp-tts:9008/mcp/tools/call`
   - Tool executes via `module.py` methods
5. **Response handling**:
   - Success/error status returned
   - Tool call logged to database
6. **Agent receives result** and continues workflow

### 4.3 Key Components

| Component | File | Purpose |
|-----------|------|---------|
| MCP Server | `server.py` | FastMCP entry point, tool registration |
| Business Logic | `module.py` | Pure Python logic, no HTTP dependencies |
| Container Def | `Dockerfile` | Docker build instructions |
| Dependencies | `requirements.txt` | Python packages |
| Tool Config | `mcp_config.yaml` | Approval rules, injection rules |
| Service Def | `docker-compose.yml` | Deployment configuration |
| Agent Config | `<agent>.yaml` | Tool access permissions |

## 5. Steps to Add a New TTS Module

### Step 1: Create Module Directory

```bash
mkdir -p druppie/mcp-servers/tts
cd druppie/mcp-servers/tts
```

### Step 2: Implement Business Logic (`module.py`)

```python
"""TTS MCP Server - Business Logic Module.

Contains all business logic for text-to-speech synthesis.
"""

import logging
from pathlib import Path

logger = logging.getLogger("tts-mcp")

class TTSModule:
    """Business logic module for TTS operations."""

    def __init__(self, cache_dir="/tmp/tts-cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def speak(self, text: str, voice_id: str = "en-US-AriaNeural",
                    rate: float = 1.0) -> dict:
        """Convert text to speech and play audio.

        Args:
            text: Text to speak
            voice_id: Voice identifier
            rate: Speech rate (0.5-2.0)

        Returns:
            dict with success status, audio file path, and metadata
        """
        try:
            # TTS synthesis logic here
            # For example, using Azure TTS SDK
            import azure.cognitiveservices.speech as speechsdk

            # Generate audio file
            output_path = self.cache_dir / f"speak_{uuid.uuid4()}.mp3"

            # Speech synthesis
            config = speechsdk.SpeechConfig(subscription=os.getenv("AZURE_KEY"),
                                           region=os.getenv("AZURE_REGION"))
            config.speech_synthesis_voice_name = voice_id
            synthesizer = speechsdk.SpeechSynthesizer(config, None)

            result = synthesizer.speak_text_async(text).get()

            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio_data = result.audio_data
                output_path.write_bytes(audio_data)
                return {
                    "success": True,
                    "text": text,
                    "voice_id": voice_id,
                    "rate": rate,
                    "audio_path": str(output_path),
                    "duration_seconds": result.audio_duration.total_seconds(),
                }
            else:
                return {
                    "success": False,
                    "error": str(result.error_details),
                    "text": text,
                }

        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": text,
            }

    async def speak_batch(self, texts: list[str], voice_id: str = "en-US-AriaNeural",
                          rate: float = 1.0) -> dict:
        """Speak multiple texts sequentially.

        Args:
            texts: List of texts to speak
            voice_id: Voice identifier
            rate: Speech rate

        Returns:
            dict with batch results
        """
        results = []
        for i, text in enumerate(texts):
            result = await self.speak(text, voice_id, rate)
            results.append({
                "index": i,
                "text": text,
                "result": result,
            })

        success_count = sum(1 for r in results if r["result"]["success"])

        return {
            "success": success_count > 0,
            "total": len(texts),
            "success_count": success_count,
            "failed_count": len(texts) - success_count,
            "results": results,
        }
```

### Step 3: Implement FastMCP Server (`server.py`)

```python
"""TTS MCP Server.

Provides tools for text-to-speech synthesis.
Uses FastMCP framework for HTTP transport.
"""

import os
import logging

from fastmcp import FastMCP

from module import TTSModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("tts-mcp")

mcp = FastMCP("TTS MCP Server")

# Initialize business logic
module = TTSModule(cache_dir=os.getenv("TTS_CACHE_DIR", "/tmp/tts-cache"))


@mcp.tool()
async def speak(text: str, voice_id: str = "en-US-AriaNeural",
               rate: float = 1.0) -> dict:
    """Convert text to speech and play audio.

    Args:
        text: Text to speak
        voice_id: Voice identifier (e.g., 'en-US-AriaNeural', 'en-GB-SoniaNeural')
        rate: Speech rate (0.5 = slower, 2.0 = faster, default 1.0)

    Returns:
        Audio file path, duration, and metadata
    """
    return await module.speak(text=text, voice_id=voice_id, rate=rate)


@mcp.tool()
async def speak_batch(texts: list[str], voice_id: str = "en-US-AriaNeural",
                      rate: float = 1.0) -> dict:
    """Speak multiple texts sequentially.

    Args:
        texts: List of texts to speak
        voice_id: Voice identifier
        rate: Speech rate

    Returns:
        Batch processing results with individual status
    """
    return await module.speak_batch(texts=texts, voice_id=voice_id, rate=rate)


if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    app = mcp.http_app()

    async def health(request):
        return JSONResponse({
            "status": "healthy",
            "service": "tts",
            "cache_dir": os.getenv("TTS_CACHE_DIR", "/tmp/tts-cache"),
        })

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9008"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
```

### Step 4: Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server.py .
COPY module.py .

# Create cache directory for TTS output
RUN mkdir -p /tmp/tts-cache

CMD ["python", "server.py"]
```

### Step 5: Create requirements.txt

```
fastmcp>=2.0.0,<3.0.0
uvicorn>=0.24.0
azure-cognitiveservices-speech>=1.36.0
pydub>=0.25.0
numpy>=1.24.0
```

### Step 6: Register in mcp_config.yaml

Add to `druppie/core/mcp_config.yaml`:

```yaml
mcps:
  # ... existing modules ...

  tts:
    url: ${MCP_TTS_URL:-http://mcp-tts:9008}
    description: "Text-to-Speech module for audio synthesis"
    inject:
      voice_id:
        from: session.preferences.voice
        hidden: true
        tools: [speak, speak_batch]
    tools:
      - name: speak
        description: "Convert text to speech and play audio"
        requires_approval: false
        parameters:
          type: object
          properties:
            text:
              type: string
              description: "Text to speak"
            voice_id:
              type: string
              description: "Voice identifier (e.g., 'en-US-AriaNeural')"
              default: "en-US-AriaNeural"
            rate:
              type: number
              description: "Speech rate (0.5-2.0, default 1.0)"
              minimum: 0.5
              maximum: 2.0
          required:
            - text
      - name: speak_batch
        description: "Speak multiple texts sequentially"
        requires_approval: false
        parameters:
          type: object
          properties:
            texts:
              type: array
              description: "List of texts to speak"
              items:
                type: string
            voice_id:
              type: string
              description: "Voice identifier"
              default: "en-US-AriaNeural"
            rate:
              type: number
              description: "Speech rate"
              default: 1.0
          required:
            - texts
```

### Step 7: Register in docker-compose.yml

Add to `docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  mcp-tts:
    build:
      context: ./druppie/mcp-servers/tts
      dockerfile: Dockerfile
    container_name: druppie-mcp-tts
    profiles: [infra, dev, prod]
    environment:
      MCP_PORT: "9008"
      TTS_CACHE_DIR: /tmp/tts-cache
      AZURE_API_KEY: ${AZURE_API_KEY}
      AZURE_REGION: ${AZURE_REGION:-eastus}
    ports:
      - "9008:9008"
    volumes:
      - tts_cache:/tmp/tts-cache
    networks:
      - druppie-new-network

# ... later in the file ...

  # Add to backend environment variables
  druppie-backend-dev:
    environment:
      # ... existing env vars ...
      MCP_TTS_URL: ${MCP_TTS_URL:-http://mcp-tts:9008}
    depends_on:
      - mcp-tts

volumes:
  # ... existing volumes ...
  tts_cache:
    driver: local
```

### Step 8: Create Agent Integration (Optional)

Create or update an agent YAML to use TTS tools:

```yaml
# agents/definitions/business_analyst.yaml
id: business_analyst
name: Business Analyst Agent
description: Analyzes requirements and creates documentation
category: execution

mcps:
  tts: [speak, speak_batch]  # Add TTS tools
  coding: [read_file, write_file]
  web: [search_web]

# ... rest of agent config ...
```

### Step 9: Test the Module

1. **Build and start the module**:
   ```bash
   docker compose --profile dev up -d mcp-tts
   ```

2. **Check container logs**:
   ```bash
   docker compose logs -f druppie-mcp-tts
   ```

3. **Verify health endpoint**:
   ```bash
   curl http://localhost:9008/health
   ```

4. **Test via FastMCP client**:
   ```python
   from fastmcp import Client

   client = Client("http://mcp-tts:9008/mcp")
   result = await client.call_tool("speak", {"text": "Hello, world!"})
   print(result)
   ```

5. **Test in agent workflow**:
   - Create a session with an agent that has TTS enabled
   - Use the `speak` tool in your prompts
   - Verify audio playback and response handling

### Step 10: Verify Integration

1. **Check approval workflow**:
   - Agent should be able to call `tts:speak` without approval
   - Review tool usage in database
   - Check logs for successful executions

2. **Verify parameter injection**:
   - Test that `voice_id` is auto-injected from session preferences
   - Verify hidden parameters aren't visible in tool schemas

3. **Test error handling**:
   - Invalid API keys
   - Empty text input
   - Network errors

4. **Performance testing**:
   - Large text batches
   - Multiple concurrent calls
   - Memory usage

## 6. Additional Considerations

### 6.1 Security

- Validate all inputs to prevent injection attacks
- Sanitize file paths in TTS output
- Use environment variables for API keys
- Rate limit tool calls to prevent abuse
- Implement caching for frequently requested texts

### 6.2 Error Handling

```python
# Good error handling pattern
try:
    result = await module.speak(text, voice_id, rate)
    if not result["success"]:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "text": text,
        }
    return result
except Exception as e:
    logger.error(f"TTS error: {e}")
    return {
        "success": False,
        "error": str(e),
        "text": text,
    }
```

### 6.3 Testing

1. **Unit tests for `module.py`**:
   ```python
   # tests/mcp_servers/tts/test_module.py
   import pytest
   from druppie.mcp_servers.tts.module import TTSModule

   @pytest.mark.asyncio
   async def test_speak_success():
       module = TTSModule()
       result = await module.speak("Hello world")
       assert result["success"]
       assert result["text"] == "Hello world"
       assert "audio_path" in result
   ```

2. **Integration tests**:
   ```python
   # tests/mcp_servers/tts/test_server.py
   from fastmcp import Client

   @pytest.mark.asyncio
   async def test_speak_tool():
       client = Client("http://mcp-tts:9008/mcp")
       result = await client.call_tool("speak", {"text": "Test"})
       assert result["success"]
   ```

### 6.4 Monitoring

Add logging for debugging and monitoring:

```python
logger.info("TTS synthesis started",
            text=text[:100],
            voice_id=voice_id,
            rate=rate)

logger.debug("TTS synthesis completed",
             audio_path=output_path,
             duration_seconds=duration)
```

### 6.5 Caching

Implement caching for frequently requested texts:

```python
from functools import lru_cache

class TTSModule:
    def __init__(self):
        self.cache_dir = Path("/tmp/tts-cache")
        self.cache = {}

    @lru_cache(maxsize=1000)
    async def _cached_speak(self, text_hash: str, voice_id: str, rate: float):
        # Cache hit logic
        pass
```

## 7. Module Examples Reference

### Module: web (bestand-zoeker)
- **Server**: 107 lines
- **Module**: 285 lines
- **Tools**: 6 tools
- **Complexity**: Medium

### Module: docker
- **Server**: ~200 lines
- **Module**: ~300 lines
- **Tools**: 9 tools
- **Complexity**: High (Docker API integration)

### Module: coding
- **Server**: 73230 lines
- **Module**: ~8000 lines
- **Tools**: 20+ tools
- **Complexity**: Very High (Git, testing, validation)

### Module: archimate
- **Server**: ~300 lines
- **Module**: ~1000 lines
- **Tools**: 8 tools
- **Complexity**: High (Complex data structures, graphs)

**Recommendation**: Start simple (like `web` module), then add complexity incrementally.

## 8. Common Pitfalls

1. **Forgot to expose port in docker-compose.yml**: Client can't connect
2. **Missing environment variables**: Server fails to start
3. **Tool approval set to true for public tools**: Users can't use it
4. **Module.py imports FastMCP**: Can't test module independently
5. **Invalid JSON schema in mcp_config.yaml**: Tool calls fail
6. **Not adding module to docker-compose.yml**: Module not deployed
7. **Forgetting to register tools in mcp_config.yaml**: Agent can't discover them
8. **Using blocking I/O in async functions**: Event loop hangs

## 9. Troubleshooting

### Module won't start
```bash
# Check logs
docker compose logs druppie-mcp-tts

# Check container status
docker compose ps mcp-tts

# Verify health endpoint
curl http://localhost:9008/health
```

### Agent can't call tool
1. Check agent YAML has module in `mcps`
2. Verify tool name matches exactly in both mcp_config.yaml and server.py
3. Check approval requirements in mcp_config.yaml
4. Review agent logs for tool execution errors

### Parameter injection not working
1. Verify context path exists in `mcp_config.yaml` (e.g., `session.preferences.voice`)
2. Check hidden: true in injection rules
3. Verify `from` path uses dot notation

### TTS audio not playing
1. Check cache directory permissions
2. Verify audio file format is supported by system
3. Check file paths are accessible
4. Review error messages in response

---

## Summary

To add a TTS module to Druppie:

1. **Create module directory**: `druppie/mcp-servers/tts/`
2. **Implement business logic** in `module.py` (no HTTP dependencies)
3. **Implement FastMCP server** in `server.py` with `@mcp.tool()` decorators
4. **Create Dockerfile** and `requirements.txt`
5. **Register in mcp_config.yaml** with tool definitions and approval rules
6. **Register in docker-compose.yml** with environment variables and port mapping
7. **Test** the module independently and with agents
8. **Monitor** logs and database for tool execution

The pattern is consistent across all Druppie MCP modules: clean separation between FastMCP server (HTTP/protocol) and business logic module (pure Python).
