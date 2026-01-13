package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

type SherpaTTSProvider struct {
	DefaultLang  string
	DefaultModel string
	ServiceURL   string
	PricePerWord float64
	Client       *http.Client
}

func NewSherpaTTSProvider(baseURL, lang, modelName string, pricePerWord float64) (*SherpaTTSProvider, error) {
	url := baseURL
	if url == "" {
		url = os.Getenv("SHERPA_SERVER_URL")
	}
	if url == "" {
		url = "http://sherpa-service:8081" // Default service name in docker-compose
	}

	return &SherpaTTSProvider{
		DefaultLang:  lang,
		DefaultModel: modelName,
		ServiceURL:   url,
		PricePerWord: pricePerWord,
		Client:       &http.Client{},
	}, nil
}

type GenerateRequest struct {
	Text         string `json:"text"`
	Language     string `json:"language"`
	Voice        string `json:"voice"`         // Optional
	SystemPrompt string `json:"system_prompt"` // Optional
}

type GenerateResponse struct {
	AudioBase64 string `json:"audio_base64"`
	Error       string `json:"error,omitempty"`
}

func (p *SherpaTTSProvider) Generate(ctx context.Context, prompt string, systemPrompt string) (string, model.TokenUsage, error) {
	// Construct request
	reqBody := GenerateRequest{
		Text:         prompt,
		Language:     p.DefaultLang,
		Voice:        p.DefaultModel,
		SystemPrompt: systemPrompt,
	}

	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		return "", model.TokenUsage{}, err
	}

	req, err := http.NewRequestWithContext(ctx, "POST", p.ServiceURL+"/generate", bytes.NewBuffer(bodyBytes))
	if err != nil {
		return "", model.TokenUsage{}, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := p.Client.Do(req)
	if err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to call sherpa service: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", model.TokenUsage{}, fmt.Errorf("sherpa service error (status %d): %s", resp.StatusCode, string(body))
	}

	var genResp GenerateResponse
	if err := json.NewDecoder(resp.Body).Decode(&genResp); err != nil {
		return "", model.TokenUsage{}, fmt.Errorf("failed to decode response: %w", err)
	}

	if genResp.Error != "" {
		return "", model.TokenUsage{}, fmt.Errorf("sherpa service error: %s", genResp.Error)
	}

	// Calculate Cost
	wordCount := len(strings.Fields(prompt))
	cost := float64(wordCount) * p.PricePerWord

	// genResp.AudioBase64 is already base64 encoded wav (as per server impl)
	return fmt.Sprintf("base64,%s", genResp.AudioBase64), model.TokenUsage{EstimatedCost: cost}, nil
}

func (p *SherpaTTSProvider) Close() error {
	return nil
}

// ListVoices returns available voices.
// This is a stub for now as logic moved to the service.
func ListVoices(lang string) []string {
	return []string{}
}
