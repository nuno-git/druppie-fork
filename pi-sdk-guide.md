# Pi.dev SDK Guide

The Pi.dev SDK provides programmatic access to AI agent capabilities for building custom interfaces, integrating agent reasoning into applications, and creating automated workflows.

## Quick Start

### Installation

```bash
npm install @mariozechner/pi-coding-agent
```

### Basic Usage

```typescript
import { AuthStorage, createAgentSession, ModelRegistry, SessionManager } from "@mariozechner/pi-coding-agent";

// Set up credential storage and model registry
const authStorage = AuthStorage.create();
const modelRegistry = ModelRegistry.create(authStorage);

const { session } = await createAgentSession({
  sessionManager: SessionManager.inMemory(),
  authStorage,
  modelRegistry,
});

// Subscribe to events for streaming output
session.subscribe((event) => {
  if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
    process.stdout.write(event.assistantMessageEvent.delta);
  }
});

// Send a prompt
await session.prompt("What files are in the current directory?");
```

## Core Concepts

### 1. AgentSession

The main session object that manages agent lifecycle, message history, model state, and event streaming.

```typescript
interface AgentSession {
  // Send a prompt and wait for completion
  prompt(text: string, options?: PromptOptions): Promise<void>;
  
  // Queue messages during streaming
  steer(text: string): Promise<void>;
  followUp(text: string): Promise<void>;
  
  // Subscribe to events (returns unsubscribe function)
  subscribe(listener: (event: AgentSessionEvent) => void): () => void;
  
  // Session info
  sessionFile: string | undefined;
  sessionId: string;
  
  // Model control
  setModel(model: Model): Promise<void>;
  setThinkingLevel(level: ThinkingLevel): void;
  cycleModel(): Promise<void>;
  cycleThinkingLevel(): ThinkingLevel | undefined;
  
  // State access
  agent: Agent;
  model: Model | undefined;
  thinkingLevel: ThinkingLevel;
  messages: AgentMessage[];
  isStreaming: boolean;
  
  // Additional methods
  navigateTree(targetId: string, options?: { summarize?: boolean; customInstructions?: string; replaceInstructions?: boolean; label?: string }): Promise<{ editorText?: string; cancelled: boolean }>;
  
  // Compaction and abort
  compact(customInstructions?: string): Promise<void>;
  abortCompaction(): void;
  abort(): Promise<void>;
  
  // Cleanup
  dispose(): void;
}
```

### 2. AgentSessionRuntime

Use the runtime API when you need to replace the active session and rebuild cwd-bound runtime state.

```typescript
import {
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  getAgentDir,
  SessionManager,
} from "@mariozechner/pi-coding-agent";

const createRuntime: CreateAgentSessionRuntimeFactory = async ({ cwd, sessionManager, sessionStartEvent }) => {
  const services = await createAgentSessionServices({ cwd });
  return {
    ...(await createAgentSessionFromServices({
      services,
      sessionManager,
      sessionStartEvent,
    })),
    services,
    diagnostics: services.diagnostics,
  };
};

const runtime = await createAgentSessionRuntime(createRuntime, {
  cwd: process.cwd(),
  agentDir: getAgentDir(),
  sessionManager: SessionManager.create(process.cwd()),
});

// Replace the active session with a fresh one
await runtime.newSession();

// Replace the active session with another saved session
await runtime.switchSession("/path/to/session.jsonl");

// Replace the active session with a fork from a specific user entry
await runtime.fork("entry-id");
```

## Customization Examples

### 1. Custom Model Selection

```typescript
import { getModel } from "@mariozechner/pi-ai";
import { AuthStorage, createAgentSession, ModelRegistry } from "@mariozechner/pi-coding-agent";

const authStorage = AuthStorage.create();
const modelRegistry = ModelRegistry.create(authStorage);

// Find specific built-in model
const opus = getModel("anthropic", "claude-opus-4-5");
if (!opus) throw new Error("Model not found");

const { session } = await createAgentSession({
  model: opus,
  thinkingLevel: "high", // off, minimal, low, medium, high, xhigh
  authStorage,
  modelRegistry,
});
```

### 2. Custom System Prompt

```typescript
import { createAgentSession, DefaultResourceLoader } from "@mariozechner/pi-coding-agent";

const loader = new DefaultResourceLoader({
  systemPromptOverride: () => "You are a helpful assistant. Be concise and direct.",
});
await loader.reload();

const { session } = await createAgentSession({ resourceLoader: loader });
```

### 3. Custom Tools

```typescript
import { Type } from "typebox";
import { createAgentSession, defineTool } from "@mariozechner/pi-coding-agent";

// Define a custom tool
const statusTool = defineTool({
  name: "status",
  label: "Status",
  description: "Get system status",
  parameters: Type.Object({}),
  execute: async (_toolCallId, params) => ({
    content: [{ type: "text", text: `Uptime: ${process.uptime()}s` }],
    details: {},
  }),
});

// Pass custom tools directly
const { session } = await createAgentSession({
  customTools: [statusTool],
});
```

### 4. Using Built-in Tools

```typescript
import {
  codingTools,        // read, bash, edit, write (default)
  readOnlyTools,      // read, grep, find, ls
  readTool, bashTool, editTool, writeTool,
  grepTool, findTool, lsTool,
} from "@mariozechner/pi-coding-agent";

// Use read-only tool set
const { session } = await createAgentSession({
  tools: readOnlyTools,
});

// Pick specific tools
const { session: customSession } = await createAgentSession({
  tools: [readTool, bashTool, grepTool],
});
```

### 5. Tools with Custom Working Directory

**Important:** When specifying a custom `cwd` AND providing explicit `tools`, use tool factory functions:

```typescript
import {
  createCodingTools,      // Creates [read, bash, edit, write] for specific cwd
  createReadOnlyTools,     // Creates [read, grep, find, ls] for specific cwd
  createReadTool,
  createBashTool,
} from "@mariozechner/pi-coding-agent";

const cwd = "/path/to/project";

// Use factory for tool sets
const { session } = await createAgentSession({
  cwd,
  tools: createCodingTools(cwd), // Tools resolve paths relative to cwd
});

// Or pick specific tools
const { session: customSession } = await createAgentSession({
  cwd,
  tools: [createReadTool(cwd), createBashTool(cwd)],
});
```

### 6. Custom Extensions

```typescript
import { createAgentSession, DefaultResourceLoader } from "@mariozechner/pi-coding-agent";

const loader = new DefaultResourceLoader({
  additionalExtensionPaths: ["/path/to/my-extension.ts"],
  extensionFactories: [
    (pi) => {
      pi.on("agent_start", () => {
        console.log("[Custom Extension] Agent starting");
      });
    },
  ],
});

await loader.reload();

const { session } = await createAgentSession({ resourceLoader: loader });
```

### 7. Session Management

```typescript
import {
  createAgentSession,
  SessionManager,
} from "@mariozechner/pi-coding-agent";

// In-memory (no persistence)
const { session: inMemory } = await createAgentSession({
  sessionManager: SessionManager.inMemory(),
});

// New persistent session
const { session: persisted } = await createAgentSession({
  sessionManager: SessionManager.create(process.cwd()),
});

// Continue most recent
const { session: continued, modelFallbackMessage } = await createAgentSession({
  sessionManager: SessionManager.continueRecent(process.cwd()),
});

// Open specific file
const { session: opened } = await createAgentSession({
  sessionManager: SessionManager.open("/path/to/session.jsonl"),
});

// List sessions
const currentProjectSessions = await SessionManager.list(process.cwd());
const allSessions = await SessionManager.listAll(process.cwd());
```

### 8. Custom Settings

```typescript
import { createAgentSession, SettingsManager, SessionManager } from "@mariozechner/pi-coding-agent";

// With overrides
const settingsManager = SettingsManager.create();
settingsManager.applyOverrides({
  compaction: { enabled: false },
  retry: { enabled: true, maxRetries: 5 },
});

const { session } = await createAgentSession({ settingsManager });

// In-memory (no file I/O, for testing)
const { session: testSession } = await createAgentSession({
  settingsManager: SettingsManager.inMemory({ compaction: { enabled: false } }),
  sessionManager: SessionManager.inMemory(),
});
```

### 9. Event Handling

```typescript
session.subscribe((event) => {
  switch (event.type) {
    // Streaming text from assistant
    case "message_update":
      if (event.assistantMessageEvent.type === "text_delta") {
        process.stdout.write(event.assistantMessageEvent.delta);
      }
      if (event.assistantMessageEvent.type === "thinking_delta") {
        // Thinking output (if thinking enabled)
      }
      break;

    // Tool execution
    case "tool_execution_start":
      console.log(`Tool: ${event.toolName}`);
      break;
    case "tool_execution_end":
      console.log(`Result: ${event.isError ? "error" : "success"}`);
      break;

    // Message lifecycle
    case "message_start":
      console.log("New message starting");
      break;
    case "message_end":
      console.log("Message complete");
      break;

    // Agent lifecycle
    case "agent_start":
      console.log("Agent started processing prompt");
      break;
    case "agent_end":
      console.log("Agent finished");
      break;

    // Turn lifecycle (one LLM response + tool calls)
    case "turn_start":
      console.log("Turn starting");
      break;
    case "turn_end":
      console.log("Turn ended");
      break;

    // Session events (queue, compaction, retry)
    case "queue_update":
      console.log("Queue updated:", event.steering, event.followUp);
      break;
    case "compaction_start":
      console.log("Compaction started");
      break;
  }
});
```

### 10. API Key Management

```typescript
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

// Default: uses ~/.pi/agent/auth.json and ~/.pi/agent/models.json
const authStorage = AuthStorage.create();
const modelRegistry = ModelRegistry.create(authStorage);

// Runtime API key override (not persisted to disk)
authStorage.setRuntimeApiKey("anthropic", "sk-my-temp-key");

// Custom auth storage location
const customAuth = AuthStorage.create("/my/app/auth.json");
const customRegistry = ModelRegistry.create(customAuth, "/my/app/models.json");

const { session } = await createAgentSession({
  sessionManager: SessionManager.inMemory(),
  authStorage: customAuth,
  modelRegistry: customRegistry,
});
```

## Advanced Configuration

### Complete Customization Example

```typescript
import { getModel } from "@mariozechner/pi-ai";
import { Type } from "typebox";
import {
  AuthStorage,
  bashTool,
  createAgentSession,
  DefaultResourceLoader,
  defineTool,
  ModelRegistry,
  readTool,
  SessionManager,
  SettingsManager,
} from "@mariozechner/pi-coding-agent";

// Set up auth storage (custom location)
const authStorage = AuthStorage.create("/custom/agent/auth.json");

// Runtime API key override (not persisted)
if (process.env.MY_KEY) {
  authStorage.setRuntimeApiKey("anthropic", process.env.MY_KEY);
}

// Model registry (no custom models.json)
const modelRegistry = ModelRegistry.create(authStorage);

// Inline tool
const statusTool = defineTool({
  name: "status",
  label: "Status",
  description: "Get system status",
  parameters: Type.Object({}),
  execute: async () => ({
    content: [{ type: "text", text: `Uptime: ${process.uptime()}s` }],
    details: {},
  }),
});

const model = getModel("anthropic", "claude-opus-4-5");
if (!model) throw new Error("Model not found");

// In-memory settings with overrides
const settingsManager = SettingsManager.inMemory({
  compaction: { enabled: false },
  retry: { enabled: true, maxRetries: 2 },
});

const loader = new DefaultResourceLoader({
  cwd: process.cwd(),
  agentDir: "/custom/agent/",
  settingsManager,
  systemPromptOverride: () => "You are a minimal assistant. Be concise.",
});
await loader.reload();

const { session } = await createAgentSession({
  cwd: process.cwd(),
  agentDir: "/custom/agent/",
  model,
  thinkingLevel: "off",
  authStorage,
  modelRegistry,
  tools: [readTool, bashTool],
  customTools: [statusTool],
  resourceLoader: loader,
  sessionManager: SessionManager.inMemory(),
  settingsManager,
});

session.subscribe((event) => {
  if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
    process.stdout.write(event.assistantMessageEvent.delta);
  }
});

await session.prompt("Get status and list files.");
```

## Run Modes

### Interactive Mode

```typescript
import {
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  getAgentDir,
  InteractiveMode,
  SessionManager,
} from "@mariozechner/pi-coding-agent";

const createRuntime: CreateAgentSessionRuntimeFactory = async ({ cwd, sessionManager, sessionStartEvent }) => {
  const services = await createAgentSessionServices({ cwd });
  return {
    ...(await createAgentSessionFromServices({ services, sessionManager, sessionStartEvent })),
    services,
    diagnostics: services.diagnostics,
  };
};

const runtime = await createAgentSessionRuntime(createRuntime, {
  cwd: process.cwd(),
  agentDir: getAgentDir(),
  sessionManager: SessionManager.create(process.cwd()),
});

const mode = new InteractiveMode(runtime, {
  migratedProviders: [],
  modelFallbackMessage: undefined,
  initialMessage: "Hello",
  initialImages: [],
  initialMessages: [],
});

await mode.run();
```

### Print Mode

```typescript
import {
  type CreateAgentSessionRuntimeFactory,
  createAgentSessionFromServices,
  createAgentSessionRuntime,
  createAgentSessionServices,
  getAgentDir,
  runPrintMode,
  SessionManager,
} from "@mariozechner/pi-coding-agent";

const createRuntime: CreateAgentSessionRuntimeFactory = async ({ cwd, sessionManager, sessionStartEvent }) => {
  const services = await createAgentSessionServices({ cwd });
  return {
    ...(await createAgentSessionFromServices({ services, sessionManager, sessionStartEvent })),
    services,
    diagnostics: services.diagnostics,
  };
};

const runtime = await createAgentSessionRuntime(createRuntime, {
  cwd: process.cwd(),
  agentDir: getAgentDir(),
  sessionManager: SessionManager.create(process.cwd()),
});

await runPrintMode(runtime, {
  mode: "text",
  initialMessage: "Hello",
  initialImages: [],
  messages: ["Follow up"],
});
```

## Key Resources

- **Official Documentation**: https://pi.dev/docs/latest/sdk
- **GitHub Examples**: https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent/examples/sdk
- **Package**: `@mariozechner/pi-coding-agent`

## Common Use Cases

1. **Build custom UIs**: Web, desktop, or mobile interfaces for AI agents
2. **Integrate agent capabilities**: Add AI reasoning to existing applications
3. **Create automated pipelines**: Build workflows with agent reasoning
4. **Build custom tools**: Create tools that spawn sub-agents
5. **Test agent behavior**: Programmatically test and validate agent responses

## Tips for Easy Customization

1. **Start with defaults**: Begin with `createAgentSession()` without parameters, then add customizations
2. **Use tool factories**: When specifying custom `cwd`, always use `createCodingTools()` or similar factory functions
3. **Subscribe to events**: Event streams provide real-time feedback and enable responsive UIs
4. **Manage sessions properly**: Use `SessionManager` for persistence and tree-based branching
5. **Override selectively**: Use `DefaultResourceLoader` with selective overrides rather than replacing everything
6. **Use in-memory for testing**: `SessionManager.inMemory()` and `SettingsManager.inMemory()` simplify testing