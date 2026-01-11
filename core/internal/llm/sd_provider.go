package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// StableDiffusionProvider implements the LLMProvider interface for Stable Diffusion.
// ./webui.sh --listen --port 7860 --api
type StableDiffusionProvider struct {
	BaseURL string
	Model   string
	Price   float64
	LLM     Provider
}

func NewStableDiffusionProvider(baseURL, modelName string, price float64, llm Provider) *StableDiffusionProvider {
	// Normalize URL
	baseURL = strings.TrimSuffix(baseURL, "/")
	if !strings.HasPrefix(baseURL, "http") {
		baseURL = "http://" + baseURL
	}
	return &StableDiffusionProvider{
		BaseURL: baseURL,
		Model:   modelName,
		Price:   price,
		LLM:     llm,
	}
}

// ... (req/resp structs) ...

type sdText2ImgRequest struct {
	Prompt         string `json:"prompt"`
	NegativePrompt string `json:"negative_prompt,omitempty"`
	Steps          int    `json:"steps,omitempty"`
	Width          int    `json:"width,omitempty"`
	Height         int    `json:"height,omitempty"`
	CfgScale       int    `json:"cfg_scale,omitempty"`
}

type sdText2ImgResponse struct {
	Images []string `json:"images"`
	Info   string   `json:"info"`
}

func (p *StableDiffusionProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	var totalUsage model.TokenUsage

	// 1. Enhance Prompt using Default LLM
	enhancedPrompt := prompt
	if p.LLM != nil {
		sysPrompt := "You are an expert Stable Diffusion prompt engineer. Rewrite the user's prompt to be detailed, descriptive, and optimized for Stable Diffusion XL. Focus on artistic style, lighting, texture, and composition. Output ONLY the refined prompt text, no explanations."

		// If systemPrompt contains specific instructions like 'style: anime', append it?
		// For now, prompt engineering is handled by the enhancing LLM.

		llmResp, llmUsage, err := p.LLM.Generate(ctx, prompt, sysPrompt)
		if err == nil {
			enhancedPrompt = strings.TrimSpace(llmResp)
			totalUsage = llmUsage
			Log(ctx, fmt.Sprintf("[SD] Enhanced Prompt: %s", enhancedPrompt))
		} else {
			Log(ctx, fmt.Sprintf("[SD] Warning: Prompt enhancement failed: %v. Using original prompt: %s", err, prompt))
		}
	} else {
		Log(ctx, fmt.Sprintf("[SD] Using original prompt: %s", prompt))
	}

	// Default params
	req := sdText2ImgRequest{
		Prompt:   enhancedPrompt,
		Steps:    25,   // Increased slightly for quality
		Width:    1024, // SDXL preference
		Height:   1024,
		CfgScale: 7,
	}

	// Parse System Prompt for overrides (apply to request directly)
	lines := strings.Split(systemPrompt, "\n")
	for _, line := range lines {
		parts := strings.SplitN(line, ":", 2)
		if len(parts) == 2 {
			key := strings.ToLower(strings.TrimSpace(parts[0]))
			val := strings.TrimSpace(parts[1])
			switch key {
			case "negative prompt", "negative_prompt":
				req.NegativePrompt = val
			case "steps":
				if n, err := strconv.Atoi(val); err == nil {
					req.Steps = n
				}
			case "width":
				if n, err := strconv.Atoi(val); err == nil {
					req.Width = n
				}
			case "height":
				if n, err := strconv.Atoi(val); err == nil {
					req.Height = n
				}
			case "cfg_scale", "cfg scale":
				if n, err := strconv.Atoi(val); err == nil {
					req.CfgScale = n
				}
			}
		}
	}

	bodyBytes, err := json.Marshal(req)
	if err != nil {
		return "", totalUsage, err
	}

	url := fmt.Sprintf("%s/sdapi/v1/txt2img", p.BaseURL)
	httpReq, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(bodyBytes))
	if err != nil {
		return "", totalUsage, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := http.DefaultClient.Do(httpReq)
	if err != nil {
		return "", totalUsage, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", totalUsage, fmt.Errorf("SD API Error %d: %s", resp.StatusCode, string(body))
	}

	var parsed sdText2ImgResponse
	if err := json.NewDecoder(resp.Body).Decode(&parsed); err != nil {
		return "", totalUsage, fmt.Errorf("failed to decode response: %w", err)
	}

	if len(parsed.Images) == 0 {
		return "", totalUsage, fmt.Errorf("no images returned")
	}

	// Add SD execution cost
	totalUsage.EstimatedCost += p.Price

	// Return first image as base64 data URI
	return fmt.Sprintf("base64,%s", parsed.Images[0]), totalUsage, nil
}

func (p *StableDiffusionProvider) Close() error {
	return nil
}
