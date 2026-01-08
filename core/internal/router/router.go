package router

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/store"
)

type Router struct {
	llm      llm.Provider
	store    store.Store
	registry *registry.Registry
	PlanID   string
	Debug    bool
}

func NewRouter(llm llm.Provider, store store.Store, reg *registry.Registry, debug bool) *Router {
	return &Router{llm: llm, store: store, registry: reg, Debug: debug}
}

const defaultSystemPrompt = `You are the Router Agent of the Druppie Platform.
Your job is to analyze the User's input and determine their Intent.
You must output a JSON object adhering to this schema:
{
  "initial_prompt": "The user's original input string",
  "prompt": "Constructed summary of what the user wants in the user's original language",
  "action": "create_project | update_project | query_registry | orchestrate_complex | general_chat",
  "category": "infrastructure | service | search | create content | unknown",
  "content_type": "video | blog | code | image | audio | ... (optional)",
  "language": "en | nl | fr | de",
  "answer": "If action is general_chat, provide the direct answer to the user's question here. Otherwise null."
}
Ensure the "action" is one of the allowed values.
Use "language" code to detect the user's input language.
IMPORTANT: The "prompt" field MUST be in the correct language as detected in "language" code. Do NOT translate it to English.
Output ONLY valid JSON.`

func (r *Router) Analyze(ctx context.Context, planID string, input string) (model.Intent, string, model.TokenUsage, error) {
	// Try to load prompt from Registry
	sysPrompt := defaultSystemPrompt
	if r.registry != nil {
		if agent, err := r.registry.GetAgent("router"); err == nil && agent.Instructions != "" {
			sysPrompt = agent.Instructions
		}
	}

	resp, usage, err := r.llm.Generate(ctx, input, sysPrompt)
	if err != nil {
		return model.Intent{}, "", model.TokenUsage{}, fmt.Errorf("llm generation failed: %w", err)
	}

	// Persistent Logging "Like Planner"
	if r.store != nil && planID != "" {
		_ = r.store.LogInteraction(planID, "Router Analyze",
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---\n--- INPUT ---\n%s\n--- END INPUT ---", sysPrompt, input),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---", resp))
	}

	// Simple cleanup if LLM adds markdown blocks
	// resp = strings.TrimPrefix(resp, "```json")
	// resp = strings.TrimSuffix(resp, "```")
	// For now assume mock returns clean JSON

	var raw struct {
		Summary       string `json:"summary"`
		InitialPrompt string `json:"initial_prompt"`
		Prompt        string `json:"prompt"`
		Action        string `json:"action"`
		Category      string `json:"category"`
		ContentType   string `json:"content_type"`
		Language      string `json:"language"`
		Answer        string `json:"answer"`
	}

	if err := json.Unmarshal([]byte(resp), &raw); err != nil {
		return model.Intent{}, resp, usage, fmt.Errorf("failed to parse router response: %w. Raw: %s", err, resp)
	}

	intent := model.Intent{
		InitialPrompt: raw.InitialPrompt,
		Prompt:        raw.Prompt,
		Action:        raw.Action,
		Category:      raw.Category,
		ContentType:   raw.ContentType,
		Language:      raw.Language,
		Answer:        raw.Answer,
	}

	// Logic fallbacks for transition/reliability
	if intent.InitialPrompt == "" {
		intent.InitialPrompt = input
	}
	if intent.Prompt == "" {
		intent.Prompt = raw.Summary
	}
	if intent.Prompt == "" {
		intent.Prompt = intent.InitialPrompt
	}

	return intent, resp, usage, nil
}
