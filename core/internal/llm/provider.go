package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/google/generative-ai-go/genai"
	"github.com/sjhoeksma/druppie/core/internal/config"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"google.golang.org/api/option"
)

// Provider defines the interface for an LLM
type Provider interface {
	Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error)
	Close() error
}

// Manager holds multiple providers and routes requests
type Manager struct {
	defaultProvider Provider
	providers       map[string]Provider
	timeout         time.Duration
	retries         int
}

// NewManager initializes the LLM manager with the given configuration
func NewManager(ctx context.Context, cfg config.LLMConfig) (*Manager, error) {
	timeout := 120 * time.Second
	if cfg.TimeoutSeconds > 0 {
		timeout = time.Duration(cfg.TimeoutSeconds) * time.Second
	}
	retries := 3
	if cfg.Retries > 0 {
		retries = cfg.Retries
	}

	mgr := &Manager{
		providers: make(map[string]Provider),
		timeout:   timeout,
		retries:   retries,
	}

	// Helper to create a provider based on type and details
	// Helper to create a provider based on type and details
	createFn := func(pCfg config.ProviderConfig) (Provider, error) {
		switch strings.ToLower(pCfg.Type) {
		case "gemini":
			model := pCfg.Model
			if model == "" {
				model = "gemini-2.0-flash"
			}

			if pCfg.APIKey != "" {
				// Use API Key if provided
				client, err := genai.NewClient(ctx, option.WithAPIKey(pCfg.APIKey))
				if err != nil {
					return nil, err
				}
				return &GeminiProvider{
					genaiClient:             client,
					model:                   model,
					PricePerPromptToken:     pCfg.PricePerPromptToken,
					PricePerCompletionToken: pCfg.PricePerCompletionToken,
				}, nil
			} else {
				if pCfg.ProjectID == "" && pCfg.ClientID == "" {
					return nil, fmt.Errorf("gemini config incomplete (missing api_key or project_id/client_id)")
				}
				// Use OAuth2 Flow
				fmt.Println("No API key found. Attempting OAuth2 login...")
				client, finalProjectID, err := getGeminiClientWithAuth(ctx, pCfg.ProjectID, pCfg.ClientID, pCfg.ClientSecret)
				if err != nil {
					return nil, fmt.Errorf("failed to authenticate gemini: %w", err)
				}
				return &GeminiProvider{
					httpClient:              client,
					projectID:               finalProjectID,
					model:                   model,
					PricePerPromptToken:     pCfg.PricePerPromptToken,
					PricePerCompletionToken: pCfg.PricePerCompletionToken,
				}, nil
			}
		case "ollama":
			model := pCfg.Model
			if model == "" {
				model = "llama3"
			}
			baseURL := "http://localhost:11434"
			if pCfg.URL != "" {
				baseURL = pCfg.URL
			}
			return &OllamaProvider{
				Model:                   model,
				BaseURL:                 baseURL,
				PricePerPromptToken:     pCfg.PricePerPromptToken,
				PricePerCompletionToken: pCfg.PricePerCompletionToken,
			}, nil
		case "lmstudio":
			baseURL := "http://localhost:1234/v1"
			if pCfg.URL != "" {
				baseURL = pCfg.URL
			}
			return &LMStudioProvider{
				Model:                   pCfg.Model,
				BaseURL:                 baseURL,
				PricePerPromptToken:     pCfg.PricePerPromptToken,
				PricePerCompletionToken: pCfg.PricePerCompletionToken,
			}, nil
		case "openrouter":
			model := pCfg.Model
			if model == "" {
				model = "google/gemini-2.0-flash-exp:free"
			}
			return &OpenRouterProvider{
				Model:  model,
				APIKey: pCfg.APIKey,
			}, nil
		case "sherpa-onnx":
			// Language from configuration or default to EN
			lang := "en"
			if strings.Contains(strings.ToLower(pCfg.Model), "dutch") || strings.Contains(strings.ToLower(pCfg.Model), "nl") {
				lang = "nl"
			}
			return NewSherpaTTSProvider(pCfg.URL, lang, pCfg.Model, pCfg.PricePerWord)
		case "z.ai", "zai":
			model := pCfg.Model
			if model == "" {
				model = "glm-4"
			}
			baseURL := "https://api.z.ai/api/paas/v4"
			if pCfg.URL != "" {
				baseURL = pCfg.URL
			}
			return &ZAIProvider{
				Model:                   model,
				BaseURL:                 baseURL,
				APIKey:                  pCfg.APIKey,
				PricePerPromptToken:     pCfg.PricePerPromptToken,
				PricePerCompletionToken: pCfg.PricePerCompletionToken,
			}, nil
		case "stable-diffusion":
			// Use BaseURL field from config which maps to APIURL usually?
			// Config struct has APIURL? Let's check config struct in next step if needed,
			// but usually provider config has generic fields.
			// provider.go uses pCfg.APIURL for OpenAI, so we assume BaseURL is passed there.
			return NewStableDiffusionProvider(pCfg.URL, pCfg.Model, pCfg.PricePerRequest, mgr), nil
		default:
			return nil, fmt.Errorf("unknown provider type: %s", pCfg.Type)
		}
	}

	// 1. Load specific providers from map
	for name, pCfg := range cfg.Providers {
		p, err := createFn(pCfg)
		if err != nil {
			fmt.Printf("Warning: Failed to initialize provider '%s': %v. Skipping.\n", name, err)
			continue
		}
		mgr.providers[name] = p
	}

	/*
		// 2. Load legacy/default provider if configured directly
		if cfg.Provider != "" {
			p, err := createFn(cfg.Provider, cfg.APIKey, cfg.Model, "", "")
			if err == nil {
				mgr.providers["default"] = p // Fallback name
				// If no default set yet, make this the default
				if mgr.defaultProvider == nil {
					mgr.defaultProvider = p
				}
			}
		}
	*/

	// 3. Set Default Provider
	if cfg.DefaultProvider != "" {
		if p, ok := mgr.providers[cfg.DefaultProvider]; ok {
			mgr.defaultProvider = p
		}
	}

	// If still no default, and we have providers, pick one?
	if mgr.defaultProvider == nil && len(mgr.providers) > 0 {
		for _, p := range mgr.providers {
			mgr.defaultProvider = p
			break
		}
	}

	if mgr.defaultProvider == nil {
		return nil, fmt.Errorf("no usable default provider configured")
	}

	return mgr, nil
}

const (
	MaxRetries    = 3
	RetryDelay    = 2 * time.Second
	GlobalTimeout = 120 * time.Second // 2 minutes as upper bound
)

// Generate uses the default provider with retry and timeout logic
func (m *Manager) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	if m.defaultProvider == nil {
		return "", model.TokenUsage{}, fmt.Errorf("no default provider configured")
	}
	return m.generateWithRetry(ctx, m.defaultProvider, prompt, systemPrompt)
}

// GenerateWithProvider uses a specific provider with retry and timeout logic
func (m *Manager) GenerateWithProvider(ctx context.Context, providerName string, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	p, err := m.GetProvider(providerName)
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	return m.generateWithRetry(ctx, p, prompt, systemPrompt)
}

func (m *Manager) generateWithRetry(ctx context.Context, p Provider, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	// Use configured retries
	maxRetries := m.retries
	if maxRetries <= 0 {
		maxRetries = 1
	}

	var lastErr error
	for i := 0; i < maxRetries; i++ {
		// Create a context with timeout for this specific attempt
		attemptCtx, cancel := context.WithTimeout(ctx, m.timeout)

		if i > 0 {
			fmt.Printf("[LLM] Retry attempt %d/%d...\n", i+1, maxRetries)
		}

		resp, usage, err := p.Generate(attemptCtx, prompt, systemPrompt)
		cancel() // Ensure we release the timeout resources immediately

		if err == nil {
			return resp, usage, nil
		}

		// Check if parent context was canceled (User stopped)
		if ctx.Err() != nil {
			return "", model.TokenUsage{}, ctx.Err()
		}

		lastErr = err
		fmt.Printf("[LLM] Attempt %d failed: %v. Retrying in %v...\n", i+1, err, RetryDelay)

		// Wait before retry, listening for parent context cancellation
		select {
		case <-ctx.Done():
			return "", model.TokenUsage{}, ctx.Err()
		case <-time.After(RetryDelay):
		}
	}
	return "", model.TokenUsage{}, fmt.Errorf("llm generate failed after %d attempts: %w", maxRetries, lastErr)
}

// Close closes all providers
func (m *Manager) Close() error {
	for _, p := range m.providers {
		_ = p.Close()
	}
	return nil
}

// GetProvider returns a specific provider by name (as defined in config)
func (m *Manager) GetProvider(name string) (Provider, error) {
	if p, ok := m.providers[name]; ok {
		return p, nil
	}
	return nil, fmt.Errorf("provider '%s' not found", name)
}

// --- Gemini Provider ---

type GeminiProvider struct {
	genaiClient             *genai.Client // For API Key
	httpClient              *http.Client  // For OAuth
	projectID               string
	model                   string
	PricePerPromptToken     float64
	PricePerCompletionToken float64
}

func (p *GeminiProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	// Case 1: Standard API Key usage
	if p.genaiClient != nil {
		modelVal := p.genaiClient.GenerativeModel(p.model)
		if systemPrompt != "" {
			modelVal.SystemInstruction = genai.NewUserContent(genai.Text(systemPrompt))
		}
		resp, err := modelVal.GenerateContent(ctx, genai.Text(prompt))
		if err != nil {
			return "", model.TokenUsage{}, fmt.Errorf("gemini generation failed: %w", err)
		}
		if len(resp.Candidates) == 0 || len(resp.Candidates[0].Content.Parts) == 0 {
			return "", model.TokenUsage{}, fmt.Errorf("no response candidates")
		}
		var sb strings.Builder
		for _, part := range resp.Candidates[0].Content.Parts {
			if txt, ok := part.(genai.Text); ok {
				sb.WriteString(string(txt))
			}
		}

		usage := model.TokenUsage{}
		if resp.UsageMetadata != nil {
			usage.PromptTokens = int(resp.UsageMetadata.PromptTokenCount)
			usage.CompletionTokens = int(resp.UsageMetadata.CandidatesTokenCount)
			usage.TotalTokens = int(resp.UsageMetadata.TotalTokenCount)

			usage.EstimatedCost = (float64(usage.PromptTokens)/1000000.0)*p.PricePerPromptToken +
				(float64(usage.CompletionTokens)/1000000.0)*p.PricePerCompletionToken
		}

		return cleanResponse(sb.String()), usage, nil
	}

	// Case 2: Custom Cloud Code API (OAuth) usage
	if p.httpClient != nil {
		// Ensure Handshake is performed once to get the correct Managed Project ID
		// Since we can't easily add fields to the struct without a separate edit,
		// we will perform the handshake if the projectID provided by user doesn't look like a managed one (starts with 'gemini-')?
		// Or just perform it.
		// Actually, let's just do the handshake logic inline here.
		// OPTIMIZATION: We really should cache this. But for now, let's just make it work.

		effectiveProjectID := p.projectID // Start with user provided

		// Handshake Step 1: loadCodeAssist
		// We try to "load" the project context to see if there is a linked managed project
		handshakeURL := "https://cloudcode-pa.googleapis.com/v1internal:loadCodeAssist"

		metaData := map[string]string{
			"ideType":    "IDE_UNSPECIFIED",
			"platform":   "PLATFORM_UNSPECIFIED",
			"pluginType": "GEMINI",
		}

		loadBody := map[string]interface{}{
			"metadata":                metaData,
			"cloudaicompanionProject": p.projectID, // Tell it what we WANT to use
		}

		jsonLoad, _ := json.Marshal(loadBody)
		reqLoad, _ := http.NewRequestWithContext(ctx, "POST", handshakeURL, bytes.NewBuffer(jsonLoad))
		reqLoad.Header.Set("Content-Type", "application/json")
		reqLoad.Header.Set("User-Agent", "google-api-nodejs-client/9.15.1")
		reqLoad.Header.Set("X-Goog-Api-Client", "gl-node/22.17.0")
		reqLoad.Header.Set("Client-Metadata", "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI")

		fmt.Printf("[Gemini] Handshake: Loading context for project '%s'...\n", p.projectID)
		respLoad, err := p.httpClient.Do(reqLoad)

		loadSuccess := false
		if err == nil {
			bodyBytes, _ := io.ReadAll(respLoad.Body)
			respLoad.Body.Close()
			fmt.Printf("[Gemini] LoadCodeAssist Status: %s, Body: %s\n", respLoad.Status, string(bodyBytes))

			if respLoad.StatusCode == http.StatusOK {
				loadSuccess = true
				var resMap map[string]interface{}
				json.Unmarshal(bodyBytes, &resMap)

				if val, ok := resMap["cloudaicompanionProject"]; ok {
					if str, ok := val.(string); ok && str != "" {
						effectiveProjectID = str
					} else if obj, ok := val.(map[string]interface{}); ok {
						if id, ok := obj["id"].(string); ok && id != "" {
							effectiveProjectID = id
						}
					}
				}
			}
		} else {
			fmt.Printf("[Gemini] LoadCodeAssist Failed: %v\n", err)
		}

		// If we didn't get a managed ID (and maybe we need one?), we could try OnboardUser.
		// But for now, let's assume loadCodeAssist returns the correct ID if the project is valid.
		// If loadCodeAssist failed (e.g. 404), maybe we NEED to onboard.

		if !loadSuccess {
			// Try OnboardUser if load failed to give us a distinct ID or if we are just starting.
			// Opencode defaults to tierId='FREE'
			fmt.Println("[Gemini] Handshake: Attempting OnboardUser...")
			onboardURL := "https://cloudcode-pa.googleapis.com/v1internal:onboardUser"
			onboardBody := map[string]interface{}{
				"tierId":   "FREE",
				"metadata": metaData,
			}
			// Note: For FREE tier, we do NOT send cloudaicompanionProject in request

			jsonOnboard, _ := json.Marshal(onboardBody)
			reqOnboard, _ := http.NewRequestWithContext(ctx, "POST", onboardURL, bytes.NewBuffer(jsonOnboard))
			reqOnboard.Header = reqLoad.Header // Same headers

			respOnboard, err := p.httpClient.Do(reqOnboard)
			if err == nil {
				bodyBytes, _ := io.ReadAll(respOnboard.Body)
				respOnboard.Body.Close()
				fmt.Printf("[Gemini] OnboardUser Status: %s, Body: %s\n", respOnboard.Status, string(bodyBytes))

				if respOnboard.StatusCode == http.StatusOK {
					var resMap map[string]interface{}
					json.Unmarshal(bodyBytes, &resMap)

					// Payload: { response: { cloudaicompanionProject: { id: "..." } } }
					if respObj, ok := resMap["response"].(map[string]interface{}); ok {
						if projObj, ok := respObj["cloudaicompanionProject"].(map[string]interface{}); ok {
							if id, ok := projObj["id"].(string); ok {
								effectiveProjectID = id
							}
						}
					}
				}
			} else {
				fmt.Printf("[Gemini] OnboardUser Failed: %v\n", err)
			}
		}

		fmt.Printf("[Gemini] Effective Project ID: %s\n", effectiveProjectID)
		url := "https://cloudcode-pa.googleapis.com/v1internal:generateContent"

		// Construct inner request payload
		// Fallback: Prepend system prompt to inputs because v1internal often fails with systemInstruction field
		finalPrompt := prompt
		if systemPrompt != "" {
			finalPrompt = fmt.Sprintf("System Instruction: %s\n\nUser Input: %s", systemPrompt, prompt)
		}

		reqPayload := map[string]interface{}{
			"contents": []map[string]interface{}{
				{
					"role": "user",
					"parts": []map[string]interface{}{
						{"text": finalPrompt},
					},
				},
			},
			"generationConfig": map[string]interface{}{
				"candidateCount": 1,
			},
		}
		// Removed systemInstruction field to avoid 404/Unknown Field errors on internal API

		// Wrap in outer envelope as expected by Cloud Code API
		reqBody := map[string]interface{}{
			"project": effectiveProjectID,
			"model":   p.model,
			"request": reqPayload,
		}

		jsonBody, err := json.Marshal(reqBody)
		if err != nil {
			return "", model.TokenUsage{}, err
		}

		req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(jsonBody))
		if err != nil {
			return "", model.TokenUsage{}, err
		}

		// Headers from Opencode
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("User-Agent", "google-api-nodejs-client/9.15.1")
		req.Header.Set("X-Goog-Api-Client", "gl-node/22.17.0")
		req.Header.Set("Client-Metadata", "ideType=IDE_UNSPECIFIED,platform=PLATFORM_UNSPECIFIED,pluginType=GEMINI")
		req.Header.Set("X-Goog-User-Project", effectiveProjectID)

		resp, err := p.httpClient.Do(req)
		if err != nil {
			return "", model.TokenUsage{}, fmt.Errorf("request failed: %w", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			body, _ := io.ReadAll(resp.Body)
			// Log full details for debugging 500s
			return "", model.TokenUsage{}, fmt.Errorf("llm generation failed: %s\nURL: %s\nBody Sent: %s\nResponse: %s",
				resp.Status, url, string(jsonBody), string(body))
		}

		// Parse Response
		var result struct {
			Candidates []struct {
				Content struct {
					Parts []struct {
						Text string `json:"text"`
					} `json:"parts"`
				} `json:"content"`
			} `json:"candidates"`
		}

		if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
			return "", model.TokenUsage{}, fmt.Errorf("failed to decode response: %w", err)
		}

		if len(result.Candidates) > 0 && len(result.Candidates[0].Content.Parts) > 0 {
			// For internal API, usage might differ, for now return empty
			return cleanResponse(result.Candidates[0].Content.Parts[0].Text), model.TokenUsage{}, nil
		}
		return "", model.TokenUsage{}, fmt.Errorf("empty response from llm")
	}

	return "", model.TokenUsage{}, fmt.Errorf("provider not initialized correctly")
}

func (p *GeminiProvider) Close() error {
	if p.genaiClient != nil {
		return p.genaiClient.Close()
	}
	return nil
}

// --- Ollama Provider ---

type OllamaProvider struct {
	Model                   string
	BaseURL                 string
	PricePerPromptToken     float64
	PricePerCompletionToken float64
}

func (p *OllamaProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	url := fmt.Sprintf("%s/api/generate", p.BaseURL)

	// Ollama API payload
	payload := map[string]interface{}{
		"model":  p.Model,
		"prompt": prompt,
		"system": systemPrompt,
		"stream": false,
		"format": "json", // Force JSON since we usually want structure
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(body))
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("ollama request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return "", model.TokenUsage{}, fmt.Errorf("ollama error %d: %s", resp.StatusCode, string(bodyBytes))
	}

	var result struct {
		Response string `json:"response"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to decode ollama response: %w", err)
	}

	return cleanResponse(result.Response), model.TokenUsage{}, nil
}

func (p *OllamaProvider) Close() error {
	return nil
}

// --- LM Studio Provider (OpenAI Compatible) ---

type LMStudioProvider struct {
	Model                   string
	BaseURL                 string
	PricePerPromptToken     float64
	PricePerCompletionToken float64
}

func (p *LMStudioProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	url := fmt.Sprintf("%s/chat/completions", p.BaseURL)

	payload := map[string]interface{}{
		"messages": []map[string]string{
			{"role": "system", "content": systemPrompt},
			{"role": "user", "content": prompt},
		},
		"model":       "local-model", // LM Studio often ignores this or expects a loaded model name
		"temperature": 0.7,
		"max_tokens":  -1,
		"stream":      false,
	}
	// If a specific model is requested, pass it
	if p.Model != "" {
		payload["model"] = p.Model
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(body))
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("lmstudio request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return "", model.TokenUsage{}, fmt.Errorf("lmstudio error %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// OpenAI format response
	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
			TotalTokens      int `json:"total_tokens"`
		} `json:"usage"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to decode lmstudio response: %w", err)
	}

	if len(result.Choices) == 0 {
		return "", model.TokenUsage{}, fmt.Errorf("no content from lmstudio")
	}

	// Capture usage if available
	usage := model.TokenUsage{
		PromptTokens:     result.Usage.PromptTokens,
		CompletionTokens: result.Usage.CompletionTokens,
		TotalTokens:      result.Usage.TotalTokens,
	}
	usage.EstimatedCost = (float64(usage.PromptTokens)/1000000.0)*p.PricePerPromptToken +
		(float64(usage.CompletionTokens)/1000000.0)*p.PricePerCompletionToken

	return cleanResponse(result.Choices[0].Message.Content), usage, nil
}

func (p *LMStudioProvider) Close() error {
	return nil
}

// --- OpenRouter Provider ---

type OpenRouterProvider struct {
	Model  string
	APIKey string
}

func (p *OpenRouterProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	url := "https://openrouter.ai/api/v1/chat/completions"

	payload := map[string]interface{}{
		"messages": []map[string]string{
			{"role": "system", "content": systemPrompt},
			{"role": "user", "content": prompt},
		},
		"model":       p.Model,
		"temperature": 0.7,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(body))
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if p.APIKey != "" {
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", p.APIKey))
	}
	req.Header.Set("HTTP-Referer", "druppie")
	req.Header.Set("X-Title", "Druppie Core")

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("openrouter request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return "", model.TokenUsage{}, fmt.Errorf("openrouter error %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// OpenAI format response
	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
			TotalTokens      int `json:"total_tokens"`
		} `json:"usage"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to decode openrouter response: %w", err)
	}

	if len(result.Choices) == 0 {
		return "", model.TokenUsage{}, fmt.Errorf("no content from openrouter")
	}

	usage := model.TokenUsage{
		PromptTokens:     result.Usage.PromptTokens,
		CompletionTokens: result.Usage.CompletionTokens,
		TotalTokens:      result.Usage.TotalTokens,
	}

	return cleanResponse(result.Choices[0].Message.Content), usage, nil
}

func (p *OpenRouterProvider) Close() error {
	return nil
}

// Helper to strip markdown code blocks and reasoning traces
func cleanResponse(text string) string {
	text = strings.TrimSpace(text)

	// Remove <think>...</think> blocks (DeepSeek style)
	if start := strings.Index(text, "<think>"); start != -1 {
		if end := strings.Index(text, "</think>"); end != -1 {
			// Remove the thinking block including tags
			text = text[:start] + text[end+len("</think>"):]
		}
	}
	text = strings.TrimSpace(text)

	if strings.HasPrefix(text, "```json") {
		text = strings.TrimPrefix(text, "```json")
		text = strings.TrimSuffix(text, "```")
	} else if strings.HasPrefix(text, "```") {
		text = strings.TrimPrefix(text, "```")
		text = strings.TrimSuffix(text, "```")
	}
	return strings.TrimSpace(text)
}

// --- Z.AI Provider ---

type ZAIProvider struct {
	Model                   string
	BaseURL                 string
	APIKey                  string
	PricePerPromptToken     float64
	PricePerCompletionToken float64
}

func (p *ZAIProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	// OpenAI compatible endpoint construction
	// If BaseURL is "https://api.z.ai/api/paas/v4", we append "/chat/completions"
	url := fmt.Sprintf("%s/chat/completions", strings.TrimSuffix(p.BaseURL, "/"))

	payload := map[string]interface{}{
		"messages": []map[string]string{
			{"role": "system", "content": systemPrompt},
			{"role": "user", "content": prompt},
		},
		"model":       p.Model,
		"temperature": 0.7,
		"stream":      false,
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(body))
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	if p.APIKey != "" {
		req.Header.Set("Authorization", fmt.Sprintf("Bearer %s", p.APIKey))
	}

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("z.ai request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		bodyBytes, _ := io.ReadAll(resp.Body)
		return "", model.TokenUsage{}, fmt.Errorf("z.ai error %d: %s", resp.StatusCode, string(bodyBytes))
	}

	// OpenAI format response
	var result struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage struct {
			PromptTokens     int `json:"prompt_tokens"`
			CompletionTokens int `json:"completion_tokens"`
			TotalTokens      int `json:"total_tokens"`
		} `json:"usage"`
	}

	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to decode z.ai response: %w", err)
	}

	if len(result.Choices) == 0 {
		return "", model.TokenUsage{}, fmt.Errorf("no content from z.ai")
	}

	usage := model.TokenUsage{
		PromptTokens:     result.Usage.PromptTokens,
		CompletionTokens: result.Usage.CompletionTokens,
		TotalTokens:      result.Usage.TotalTokens,
	}
	usage.EstimatedCost = (float64(usage.PromptTokens)/1000000.0)*p.PricePerPromptToken +
		(float64(usage.CompletionTokens)/1000000.0)*p.PricePerCompletionToken

	return cleanResponse(result.Choices[0].Message.Content), usage, nil
}

func (p *ZAIProvider) Close() error {
	return nil
}
