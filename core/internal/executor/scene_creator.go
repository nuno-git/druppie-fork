package executor

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// SceneCreatorExecutor handles the complex workflow of generating a video scene
// This involves: TTS (Audio) -> Video Generation (ComfyUI) -> Assembly (FFmpeg)
type SceneCreatorExecutor struct{}

func (e *SceneCreatorExecutor) CanHandle(action string) bool {
	action = strings.ToLower(action)
	if action == "expand_loop" {
		return true
	}
	// Explicitly exclude the Lead Agent actions to prevent it from running generation simulation
	if action == "video_content_creator" ||
		action == "draft_scenes" ||
		action == "content_review" {
		return false
	}
	return strings.Contains(action, "video") ||
		strings.Contains(action, "scene") ||
		action == "scene_creator"
}

func (e *SceneCreatorExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	if step.Action == "expand_loop" {
		outputChan <- "Loop expansion handling (Metadata Step) - Completed."
		return nil
	}

	// Determine Scene ID (from params or step ID)
	sceneID := fmt.Sprintf("%d", step.ID) // Default
	if sid, ok := step.Params["scene_id"]; ok {
		sceneID = fmt.Sprintf("%v", sid)
	}

	// 1. Simulate Audio Generation (TTS)
	// In a real implementation, this would call the 'ai-text-to-speech' block using the Registry
	outputChan <- fmt.Sprintf("🗣️ [TTS] Generating Audio for Scene %s...", sceneID)

	// Simulate work
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(1 * time.Second):
	}
	outputChan <- fmt.Sprintf("✅ [TTS] Audio generated: %s_audio.mp3", sceneID)

	// 2. Simulate ComfyUI Video Generation
	// In a real implementation, this would call 'ai-video-comfyui' block
	outputChan <- fmt.Sprintf("🎥 [ComfyUI] Generating Video for Scene %s...", sceneID)

	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(3 * time.Second):
	}
	outputChan <- fmt.Sprintf("✅ [ComfyUI] Video generated: %s_video.mp4", sceneID)

	// 3. Assemble
	// In a real implementation, this would call an ffmpeg wrapper
	outputChan <- fmt.Sprintf("🎬 [FFmpeg] Assembling Scene %s...", sceneID)
	time.Sleep(500 * time.Millisecond)
	outputChan <- fmt.Sprintf("✅ [Scene Creator] Scene %s Complete: %s_scene_final.mp4", sceneID, sceneID)
	outputChan <- fmt.Sprintf("RESULT_VIDEO_FILE=%s_scene_final.mp4", sceneID)

	return nil
}
