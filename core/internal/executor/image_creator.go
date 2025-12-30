package executor

import (
	"context"
	"fmt"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// ImageCreatorExecutor handles Image generation (SDXL)
type ImageCreatorExecutor struct{}

func (e *ImageCreatorExecutor) CanHandle(action string) bool {
	return action == "image-creator" || action == "image-generation" || action == "generate_images"
}

func (e *ImageCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	// Extract Scene ID
	sceneID := fmt.Sprintf("%d", step.ID)
	if sID, ok := step.Params["scene_id"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
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
		prompt = fmt.Sprintf("%v", p)
	}

	outputChan <- fmt.Sprintf("   📝 Logic: Generating image for \"%s\"", prompt)

	// Simulate Latency
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(2000 * time.Millisecond):
	}

	filename := fmt.Sprintf("image_scene_%s.png", sceneID)
	outputChan <- fmt.Sprintf("✅ [Image Creator] Generated: %s", filename)
	outputChan <- fmt.Sprintf("RESULT_IMAGE_FILE=%s", filename)

	return nil
}
