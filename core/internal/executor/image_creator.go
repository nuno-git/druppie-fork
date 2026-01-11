package executor

import (
	"context"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

// ImageCreatorExecutor handles Image generation (SDXL)
type ImageCreatorExecutor struct {
	LLM llm.Provider
}

func (e *ImageCreatorExecutor) CanHandle(action string) bool {
	return action == "image_creator" || action == "image_generation" || action == "generate_images"
}

func (e *ImageCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	// Extract Scene ID
	sceneID := fmt.Sprintf("%d", step.ID)
	if sID, ok := step.Params["scene_id"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
	}
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	}

	outputChan <- fmt.Sprintf("🎨 [Image Creator] Processing Scene %s...", sceneID)

	// Extract Prompt
	prompt := ""
	if p, ok := step.Params["visual_prompt"]; ok {
		prompt = fmt.Sprintf("%v", p)
	} else if p, ok := step.Params["visual_prompts"]; ok {
		prompt = fmt.Sprintf("%v", p)
	} else if p, ok := step.Params["prompt"]; ok {
		prompt = fmt.Sprintf("%v", p)
	} else if p, ok := step.Params["image_prompt"]; ok {
		prompt = fmt.Sprintf("%v", p)
	} else if p, ok := step.Params["visual_description"]; ok {
		prompt = fmt.Sprintf("%v", p)
	} else { // Generic fallback
		prompt = fmt.Sprintf("%v", step.Params["p"])
	}
	if prompt == "" || prompt == "<nil>" {
		prompt = "Abstract digital art"
	}

	outputChan <- fmt.Sprintf("   📝 Logic: Generating image for \"%s\"", prompt)

	// 1. Try LLM Provider "image_creator"
	if e.LLM != nil {
		if mgr, ok := e.LLM.(*llm.Manager); ok {
			// Check if provider exists (or we can just try Call)
			// Manager.GenerateWithProvider handles retrieval
			resp, usage, err := mgr.GenerateWithProvider(ctx, "image_creator", prompt, "Generate Image")
			if err == nil && resp != "" {
				filename := fmt.Sprintf("image_scene_%s.png", sceneID)
				if planID != "" {
					if err := SaveAsset(planID, filename, resp); err == nil {
						outputChan <- fmt.Sprintf("✅ [Image Creator] Generated via Provider: %s", filename)
						outputChan <- fmt.Sprintf("RESULT_IMAGE_FILE=%s", filename)
						outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
						return nil
					}
					outputChan <- fmt.Sprintf("⚠️ Failed to save image from provider: %v", err)
				} else {
					outputChan <- "⚠️ Plan ID missing, cannot save file."
				}
			} else {
				// Log only if error is NOT "provider not found"?
				// Actually GenerateWithProvider returns error if not found.
				// We fall back silently if it fails?
				// Maybe log "Provider 'image_creator' not found or failed, using mock."
				// outputChan <- fmt.Sprintf("Provider check: %v", err)
			}
		}
	}

	// Simulate Latency (Fallback)
	delay := time.Duration(1000+rand.Intn(4000)) * time.Millisecond
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(delay):
	}

	filename := fmt.Sprintf("image_scene_%s.png", sceneID)
	// Mock: create a dummy file if planID is available
	if planID != "" {
		basePath := fmt.Sprintf(".druppie/plans/%s/files", planID)
		_ = os.MkdirAll(basePath, 0755)
		fullPath := filepath.Join(basePath, filename)

		// Try to use ffmpeg to create a real 1x1 black png
		ffmpegPath, err := exec.LookPath("ffmpeg")
		if err == nil {
			// ffmpeg -f lavfi -i color=c=black:s=1x1:d=1 -frames:v 1 -y <file>
			cmd := exec.Command(ffmpegPath, "-f", "lavfi", "-i", "color=c=black:s=1x1:d=1", "-frames:v", "1", "-y", fullPath)
			_ = cmd.Run()
		} else {
			// Fallback to dummy data
			_ = SaveAsset(planID, filename, "mock_image_data")
		}
	}

	outputChan <- fmt.Sprintf("✅ [Image Creator] Generated (Mock): %s", filename)
	outputChan <- fmt.Sprintf("RESULT_IMAGE_FILE=%s", filename)
	outputChan <- "RESULT_TOKEN_USAGE=0,0,0,0.00100"

	return nil
}
