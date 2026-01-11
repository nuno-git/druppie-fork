package executor

import (
	"context"
	"encoding/base64"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

// AudioCreatorExecutor handles TTS generation
type AudioCreatorExecutor struct {
	LLM llm.Provider
}

func (e *AudioCreatorExecutor) CanHandle(action string) bool {
	return action == "audio_creator" || action == "text_to_speech"
}

func (e *AudioCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	// Extract Scene ID for naming
	sceneID := fmt.Sprintf("%d", step.ID)
	if sID, ok := step.Params["scene_id"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
	} else if sID, ok := step.Params["scene"]; ok {
		sceneID = fmt.Sprintf("%v", sID)
	}
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
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

	// Try LLM Provider "text_to_speech"
	if e.LLM != nil {
		if mgr, ok := e.LLM.(*llm.Manager); ok {
			// Construct system prompt with metadata
			// Convention: "Generate Audio\nLanguage: <lang>\nVoice: <voice>"
			sysPrompt := "Generate Audio"

			// Detect language from step (if passed by Planner/Router)
			// Planner usually puts detected language in intent or params
			if lang, ok := step.Params["language"]; ok {
				sysPrompt += fmt.Sprintf("\nLanguage: %v", lang)
			}
			// Voice override
			if voice != "Default" {
				sysPrompt += fmt.Sprintf("\nVoice: %s", voice)
			}

			resp, usage, err := mgr.GenerateWithProvider(ctx, "audio_creator", text, sysPrompt)
			if err == nil && resp != "" {
				// Detect format
				ext := ".mp3"
				// Quick sniff of base64 data to check for RIFF (WAV)
				// Base64 for "RIFF" is "UkVG..." or similar depending on alignment, but better to decode prefix
				// "RIFF" in hex: 52 49 46 46
				// Just strip prefix and decode a chunk
				dataPayload := resp
				if strings.HasPrefix(resp, "base64,") {
					parts := strings.Split(resp, ",")
					if len(parts) > 1 {
						dataPayload = parts[len(parts)-1]
					}
				}
				// Decode first 12 bytes
				header, _ := base64.StdEncoding.DecodeString(dataPayload)
				if len(header) >= 4 && string(header[:4]) == "RIFF" {
					ext = ".wav"
				}

				filename := fmt.Sprintf("audio_scene_%s%s", sceneID, ext)
				if planID != "" {
					if err := SaveAsset(planID, filename, resp); err == nil {
						outputChan <- fmt.Sprintf("✅ [Audio Creator] Generated via Provider: %s", filename)
						outputChan <- fmt.Sprintf("RESULT_AUDIO_FILE=%s", filename)
						if usage.EstimatedCost > 0 || usage.TotalTokens > 0 {
							outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
						}
						return nil
					}
					outputChan <- fmt.Sprintf("⚠️ Failed to save audio from provider: %v", err)
				} else {
					outputChan <- "⚠️ Plan ID missing, cannot save file."
				}
			}
		}
	}

	// Simulate Latency (1-5s)
	delay := time.Duration(1000+rand.Intn(4000)) * time.Millisecond
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(delay):
	}

	// Calculate fake duration based on text length (rough calc: 15 chars ~ 1 sec)
	durationSeconds := len(text) / 15
	if durationSeconds < 2 {
		durationSeconds = 2
	}
	durationStr := fmt.Sprintf("%ds", durationSeconds)

	filename := fmt.Sprintf("audio_scene_%s.mp3", sceneID)
	// Mock file creation if planID exists
	if planID != "" {
		basePath := fmt.Sprintf(".druppie/plans/%s/files", planID)
		_ = os.MkdirAll(basePath, 0755)
		fullPath := filepath.Join(basePath, filename)

		// Try to use ffmpeg to create a real 1s silent mp3
		ffmpegPath, err := exec.LookPath("ffmpeg")
		if err == nil {
			// ffmpeg -f lavfi -i anullsrc=r=44100:cl=stereo -t <duration> -y <file>
			cmd := exec.Command(ffmpegPath, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", strconv.Itoa(durationSeconds), "-y", fullPath)
			_ = cmd.Run()
		} else {
			// Fallback to dummy data
			_ = SaveAsset(planID, filename, "mock_audio_data")
		}
	}

	outputChan <- fmt.Sprintf("✅ [Audio Creator] Generated (Mock): %s (Duration: %s)", filename, durationStr)

	// Return structural result
	outputChan <- fmt.Sprintf("RESULT_DURATION=%s", durationStr)
	outputChan <- fmt.Sprintf("RESULT_AUDIO_FILE=%s", filename)
	outputChan <- "RESULT_TOKEN_USAGE=0,0,0,0.00100"

	return nil
}
