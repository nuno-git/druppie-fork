import { Type, type Static } from "@sinclair/typebox";
import type { ExtensionAPI, ToolDefinition } from "@mariozechner/pi-coding-agent";

import { SandboxGitOps } from "./sandbox-git.js";
import { pushBundleIsolated } from "./sandbox-push.js";
import { selectGitProvider } from "./git-providers.js";
import type { SandboxClient } from "./sandbox-client.js";
import type { RunningSandbox } from "./types.js";

const pushSchema = Type.Object({
  branch: Type.String({ description: "Branch name to push" }),
  remote_url: Type.Optional(Type.String({ description: "Override remote URL (defaults to origin)" })),
});

const prSchema = Type.Object({
  head: Type.String({ description: "Head branch (your changes)" }),
  base: Type.String({ description: "Base branch to merge into" }),
  title: Type.String({ description: "PR title" }),
  body: Type.Optional(Type.String({ description: "PR body/description" })),
});

export function registerGitTools(
  pi: ExtensionAPI,
  client: SandboxClient,
  sandbox: RunningSandbox,
): void {
  const gitOps = new SandboxGitOps(client);

  const pushToRemote: ToolDefinition<typeof pushSchema, undefined> = {
    name: "push_to_remote",
    label: "Push to Remote",
    description:
      "Create a git bundle inside the sandbox and push it to the remote repository " +
      "from an isolated throwaway container. The sandbox never sees the push credentials.",
    parameters: pushSchema,
    async execute(_toolCallId, rawParams, _signal, _onUpdate, _ctx) {
      const params = rawParams as Static<typeof pushSchema>;
      const provider = selectGitProvider();
      const token = await provider.resolveToken();
      if (!token) {
        return {
          content: [{ type: "text" as const, text: "Error: no git token available. Set GITHUB_TOKEN or GitHub App env vars." }],
          details: undefined,
        };
      }

      try {
        await gitOps.createBundle();
        const bundleHostPath = `${sandbox.bundleHostDir}/run.bundle`;
        const remoteUrl = params.remote_url || process.env.PI_AGENT_REMOTE_URL || "";
        if (!remoteUrl) {
          return {
            content: [{ type: "text" as const, text: "Error: no remote URL. Set PI_AGENT_REMOTE_URL or pass remote_url parameter." }],
            details: undefined,
          };
        }

        const pushResult = pushBundleIsolated({
          bundleHostPath,
          remoteUrl,
          branch: params.branch,
          token,
        });

        if (!pushResult.ok) {
          return {
            content: [{ type: "text" as const, text: `Push failed: ${pushResult.output}` }],
            details: undefined,
          };
        }
        return {
          content: [{ type: "text" as const, text: `Successfully pushed ${params.branch} to remote.\n${pushResult.output}` }],
          details: undefined,
        };
      } catch (err) {
        return {
          content: [{ type: "text" as const, text: `Push error: ${err instanceof Error ? err.message : String(err)}` }],
          details: undefined,
        };
      }
    },
  };

  const createPr: ToolDefinition<typeof prSchema, undefined> = {
    name: "create_pr",
    label: "Create Pull Request",
    description:
      "Create or ensure a pull request exists on the git provider (GitHub or Gitea). " +
      "Idempotent — returns the existing PR URL if one is already open.",
    parameters: prSchema,
    async execute(_toolCallId, rawParams, _signal, _onUpdate, _ctx) {
      const params = rawParams as Static<typeof prSchema>;
      const provider = selectGitProvider();
      const token = await provider.resolveToken();
      if (!token) {
        return {
          content: [{ type: "text" as const, text: "Error: no git token available." }],
          details: undefined,
        };
      }

      const remoteUrl = process.env.PI_AGENT_REMOTE_URL || "";
      if (!remoteUrl) {
        return {
          content: [{ type: "text" as const, text: "Error: no remote URL. Set PI_AGENT_REMOTE_URL." }],
          details: undefined,
        };
      }

      try {
        const result = await provider.ensurePullRequest({
          remoteUrl,
          head: params.head,
          base: params.base,
          token,
          title: params.title,
          body: params.body ?? "",
        });

        if (result.action === "skipped") {
          return {
            content: [{ type: "text" as const, text: `PR creation skipped: ${result.message}` }],
            details: undefined,
          };
        }

        const verb = result.action === "created" ? "Created" : "Already exists";
        return {
          content: [{
            type: "text" as const,
            text: `${verb} PR #${result.number}: ${result.url}`,
          }],
          details: undefined,
        };
      } catch (err) {
        return {
          content: [{ type: "text" as const, text: `PR error: ${err instanceof Error ? err.message : String(err)}` }],
          details: undefined,
        };
      }
    },
  };

  pi.registerTool(pushToRemote);
  pi.registerTool(createPr);
}
