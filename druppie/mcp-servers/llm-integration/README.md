# LLM Integration MCP Module

Centralized LLM abstraction layer with multi-provider support and automatic failover for the Druppie platform.

## Overview

This module provides a unified MCP (Model Context Protocol) interface for accessing Large Language Models from multiple providers:

- **OpenAI** (GPT-4, GPT-3.5-turbo)
- **Anthropic** (Claude 3 Opus, Sonnet, Haiku)
- **Ollama** (Local models)

## Features

- **Multi-provider support**: Use OpenAI, Anthropic, and local Ollama models via a single API
- **Automatic failover**: Automatically switches to the next provider on rate limits or errors
- **Token counting**: Accurate token counting with cost estimation
- **Streaming support**: Stream responses for real-time applications
- **Centralized credentials**: API keys managed via environment variables
- **Structured logging**: JSON-formatted logs with metadata (no content logging)

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDERS` | JSON array of provider configs | Auto-detect from API keys |
| `OPENAI_API_KEY` | OpenAI API key | None |
| `ANTHROPIC_API_KEY` | Anthropic API key | None |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `LLM_LOG_LEVEL` | Logging level | `INFO` |
| `LLM_LOG_RETENTION_DAYS` | Log retention in days | `30` |
| `MCP_PORT` | Server port | `9003` |

### Provider Priority Configuration

Configure provider priority via `LLM_PROVIDERS`:

```bash
export LLM_PROVIDERS='[{"name": "openai", "priority": 1}, {"name": "anthropic", "priority": 2}, {"name": "ollama", "priority": 3}]'
```

## Usage

### Running the Server

```bash
python server.py
```

The server will start on port 9003 (or the port specified in `MCP_PORT`).

### MCP Tools

#### `chat_completion`

Execute a chat completion with automatic failover.

**Parameters:**
- `messages` (required): List of message objects with `role` and `content`
- `model` (optional): Model identifier
- `stream` (optional): Whether to stream the response
- `max_tokens` (optional): Maximum tokens to generate
- `temperature` (optional): Sampling temperature (0-2)

**Example:**
```python
{
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    "model": "gpt-3.5-turbo"
}
```

**Response:**
```python
{
    "success": True,
    "content": "Hello! How can I help you today?",
    "model": "gpt-3.5-turbo",
    "provider": "openai",
    "usage": {
        "prompt_tokens": 25,
        "completion_tokens": 10,
        "total_tokens": 35
    },
    "estimated_cost": 0.00007,
    "finish_reason": "stop"
}
```

#### `count_tokens`

Count tokens for given text.

**Parameters:**
- `text` (required): Text to count tokens for
- `model` (optional): Model identifier

**Example:**
```python
{
    "text": "Hello, world!",
    "model": "gpt-3.5-turbo"
}
```

**Response:**
```python
{
    "success": True,
    "token_count": 4,
    "model": "gpt-3.5-turbo"
}
```

#### `list_providers`

List available providers and their status.

**Response:**
```python
{
    "success": True,
    "providers": [
        {
            "name": "openai",
            "priority": 1,
            "available": True,
            "models": ["gpt-3.5-turbo"]
        },
        {
            "name": "anthropic",
            "priority": 2,
            "available": True,
            "models": ["claude-3-sonnet-20240229"]
        }
    ]
}
```

## Health Endpoints

- `GET /health` - Health check
- `GET /ready` - Readiness check

## Architecture

```
module-llm-integration/
├── MODULE.yaml              # Module metadata
├── server.py                # FastMCP server entry point
├── v1/
│   ├── __init__.py
│   ├── module.py            # Module lifecycle
│   ├── tools.py             # MCP tool definitions
│   ├── providers.py         # LiteLLM provider abstraction
│   ├── config.py            # Configuration management
│   ├── logging.py           # Structured logging
│   └── models.py            # Pydantic models
├── tests/                   # Unit tests
├── requirements.txt
└── README.md
```

## Testing

Run tests with:

```bash
python -m pytest tests/
```

Or run individual test files:

```bash
python -m unittest tests.test_config
python -m unittest tests.test_providers
python -m unittest tests.test_tools
```

## Security

- API keys are read from environment variables only
- No API keys or content are logged
- Only metadata (timestamps, provider, token counts) is logged
- Logs are retained for 30 days

## License

Part of the Druppie platform - see main repository for license information.
