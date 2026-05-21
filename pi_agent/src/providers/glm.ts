/**
 * GLM Coding provider — Z.AI's OpenAI-compatible endpoint.
 *
 * Uses the dedicated coding endpoint: https://api.z.ai/api/coding/paas/v4
 * Models: glm-5.1, glm-5, glm-4.7, glm-4.5-air
 */

export const GLM_CODING_BASE_URL = "https://api.z.ai/api/coding/paas/v4";
export const GLM_PROVIDER = "glm-coding";

export interface GlmModelDef {
  id: string;
  name: string;
  reasoning: boolean;
  contextWindow: number;
  maxTokens: number;
}

export const GLM_MODELS: GlmModelDef[] = [
  {
    id: "glm-5.1",
    name: "GLM-5.1",
    reasoning: true,
    contextWindow: 204800,
    maxTokens: 131072,
  },
  {
    id: "glm-5",
    name: "GLM-5",
    reasoning: true,
    contextWindow: 204800,
    maxTokens: 131072,
  },
  {
    id: "glm-4.7",
    name: "GLM-4.7",
    reasoning: true,
    contextWindow: 128000,
    maxTokens: 65536,
  },
  {
    id: "glm-4.5-air",
    name: "GLM-4.5 Air",
    reasoning: false,
    contextWindow: 128000,
    maxTokens: 65536,
  },
];

/** Build the provider config for ModelRegistry.registerProvider() */
export function getGlmProviderConfig(apiKey: string) {
  return {
    name: GLM_PROVIDER,
    baseUrl: GLM_CODING_BASE_URL,
    apiKey,
    api: "openai-completions" as const,
    models: GLM_MODELS.map((m) => ({
      id: m.id,
      name: m.name,
      reasoning: m.reasoning,
      input: ["text" as const],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: m.contextWindow,
      maxTokens: m.maxTokens,
      compat: {
        supportsDeveloperRole: false,
        maxTokensField: "max_tokens" as const,
      },
    })),
  };
}
