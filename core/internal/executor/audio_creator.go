package executor

import (
	"context"
	"fmt"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// AudioCreatorExecutor handles TTS generation
type AudioCreatorExecutor struct{}

func (e *AudioCreatorExecutor) CanHandle(action string) bool {
	return action == "audio-creator" || action == "text-to-speech"
}

func (e *AudioCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	// Extract Scene ID for naming
	sceneID := fmt.Sprintf("%d", step.ID)
	if sID, ok := step.Params["scene_id"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
	} else if sID, ok := step.Params["scene"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
	}

	outputChan <- fmt.Sprintf("🎙️ [Audio Creator] Processing Scene %s...", sceneID)

	// Extract params
	text := ""
	if t, ok := step.Params["audio_text"]; ok {
		text = fmt.Sprintf("%v", t)
	} else if t, ok := step.Params["audio_texts"]; ok {
		text = fmt.Sprintf("%v", t)
	} else if t, ok := step.Params["script_segment"]; ok {
		text = fmt.Sprintf("%v", t) // Fallback
	}

	voice := "Default"
	if v, ok := step.Params["voice_profile"]; ok {
		voice = fmt.Sprintf("%v", v)
	}

	outputChan <- fmt.Sprintf("   📝 Logic: Generating speech for \"%s\" (Voice: %s)", text, voice)

	// Simulate Latency
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(1500 * time.Millisecond):
	}

	// Calculate fake duration based on text length (rough calc: 15 chars ~ 1 sec)
	durationSeconds := len(text) / 15
	if durationSeconds < 2 {
		durationSeconds = 2
	}
	durationStr := fmt.Sprintf("%ds", durationSeconds)

	filename := fmt.Sprintf("audio_scene_%s.mp3", sceneID)
	outputChan <- fmt.Sprintf("✅ [Audio Creator] Generated: %s (Duration: %s)", filename, durationStr)

	// Return structural result (Simulate writing to step result, though we just log here.
	// In real system, we'd return a result object.
	// For now, we assume the system parses logs or step is done.)

	// We can also print a special log line that the Planner might pick up?
	// The Planner currently doesn't parse executor output automatically into next step params
	// EXCEPT via the "Result" field if we had one.
	// But our Planner prompts instruct it to "EXTRACT from Result/Logs".
	// So logging clearly is good.
	outputChan <- fmt.Sprintf("RESULT_DURATION=%s", durationStr)
	outputChan <- fmt.Sprintf("RESULT_AUDIO_FILE=%s", filename)

	return nil
}
