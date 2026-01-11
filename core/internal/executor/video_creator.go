package executor

import (
	"context"
	"fmt"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

// VideoCreatorExecutor handles Visual generation and assembly
type VideoCreatorExecutor struct {
	LLM llm.Provider
}

func (e *VideoCreatorExecutor) CanHandle(action string) bool {
	return action == "video_creator" || action == "video_generation"
}

func (e *VideoCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {

	// Extract Scene ID
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

	outputChan <- fmt.Sprintf("🎥 [Video Creator] Processing Scene %s...", sceneID)

	// Extract params
	visual := ""
	if v, ok := step.Params["visual_description"]; ok {
		visual = fmt.Sprintf("%v", v)
	} else if v, ok := step.Params["visual_prompt"]; ok {
		visual = fmt.Sprintf("%v", v)
	} else if v, ok := step.Params["visual_prompts"]; ok {
		visual = fmt.Sprintf("%v", v)
	}

	duration := "5s"
	if d, ok := step.Params["duration"]; ok {
		duration = fmt.Sprintf("%v", d)
	} else if d, ok := step.Params["audio_duration"]; ok {
		duration = fmt.Sprintf("%v", d)
	}

	audioFile := ""
	if f, ok := step.Params["audio_file"]; ok {
		audioFile = fmt.Sprintf("%v", f)
	}

	imageFile := ""
	if f, ok := step.Params["image_file"]; ok {
		imageFile = fmt.Sprintf("%v", f)
	}

	outputChan <- fmt.Sprintf("   👀 Visual: \"%s\"", visual)
	if imageFile != "" {
		outputChan <- fmt.Sprintf("   🖼️ Starting Image: %s", imageFile)
	}
	outputChan <- fmt.Sprintf("   ⏱️ Duration: %s", duration)

	if audioFile != "" {
		outputChan <- fmt.Sprintf("   🎵 Synced to: %s", audioFile)
	} else {
		outputChan <- "   ⚠️ No Audio ID provided, using default pacing."
	}

	// Try LLM Provider "video_creator"
	if e.LLM != nil {
		if mgr, ok := e.LLM.(*llm.Manager); ok {
			prompt := fmt.Sprintf("Create a video based on: %s", visual)
			resp, usage, err := mgr.GenerateWithProvider(ctx, "video_creator", prompt, "Generate Video")
			if err == nil && resp != "" {
				filename := fmt.Sprintf("video_scene_%s.mp4", sceneID)
				if planID != "" {
					if err := SaveAsset(planID, filename, resp); err == nil {
						outputChan <- fmt.Sprintf("✅ [Video Creator] Generated via Provider: %s", filename)
						outputChan <- fmt.Sprintf("RESULT_VIDEO_FILE=%s", filename)
						if usage.EstimatedCost > 0 || usage.TotalTokens > 0 {
							outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
						}
						return nil
					}
					outputChan <- fmt.Sprintf("⚠️ Failed to save video from provider: %v", err)
				} else {
					outputChan <- "⚠️ Plan ID missing, cannot save file."
				}
			}
		}
	}

	outputChan <- "   ⚙️ sending to ai-video-comfyui..."
	// Simulate Latency (1-5s)
	delay := time.Duration(1000+rand.Intn(4000)) * time.Millisecond
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(delay):
	}

	filename := fmt.Sprintf("video_scene_%s.mp4", sceneID)
	if planID != "" {
		basePath := fmt.Sprintf(".druppie/plans/%s/files", planID)
		_ = os.MkdirAll(basePath, 0755)
		fullPath := filepath.Join(basePath, filename)

		// Try to use ffmpeg to create a video from the image or black color
		ffmpegPath, err := exec.LookPath("ffmpeg")
		if err == nil {
			cleanDuration := strings.TrimSuffix(duration, "s")
			if cleanDuration == "" {
				cleanDuration = "1"
			}

			imgIn := filepath.Join(basePath, imageFile)
			var cmd *exec.Cmd
			if _, err := os.Stat(imgIn); err == nil && imageFile != "" {
				// Create video from still image: ffmpeg -loop 1 -i <img> -c:v libx264 -t <dur> -pix_fmt yuv420p -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -y <out>
				cmd = exec.Command(ffmpegPath, "-loop", "1", "-i", imgIn, "-c:v", "libx264", "-t", cleanDuration, "-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-y", fullPath)
			} else {
				// Fallback to black color
				cmd = exec.Command(ffmpegPath, "-f", "lavfi", "-i", fmt.Sprintf("color=c=black:s=640x360:d=%s", cleanDuration), "-pix_fmt", "yuv420p", "-y", fullPath)
			}
			_ = cmd.Run()
		} else {
			// Fallback to dummy data
			_ = SaveAsset(planID, filename, "mock_video_data")
		}
	}

	outputChan <- fmt.Sprintf("✅ [Video Creator] Asset Generated (Mock): %s", filename)
	outputChan <- fmt.Sprintf("RESULT_VIDEO_FILE=%s", filename)
	outputChan <- "RESULT_TOKEN_USAGE=0,0,0,0.00100"

	return nil
}
