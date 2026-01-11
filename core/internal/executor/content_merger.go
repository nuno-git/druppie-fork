package executor

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// ContentMergerExecutor follows the 'content-merge' block specification.
// It simulates the use of ffmpeg to stitch scenes together.
type ContentMergerExecutor struct{}

func (e *ContentMergerExecutor) CanHandle(action string) bool {
	a := strings.ReplaceAll(strings.ToLower(action), "-", "_")
	return a == "content_merge"
}

func (e *ContentMergerExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	planID, _ := step.Params["plan_id"].(string)
	if planID == "" {
		return fmt.Errorf("plan_id is required for content_merge")
	}

	ffmpegPath, err := exec.LookPath("ffmpeg")
	if err != nil {
		outputChan <- "⚠️ [Content Merge] FFmpeg not found in PATH. Falling back to simulation mode."
		return e.simulate(ctx, step, outputChan)
	}

	outputChan <- fmt.Sprintf("🎬 [Content Merge] Initializing FFmpeg at %s...", ffmpegPath)

	// 1. Identify Scenes and Paths
	basePath := fmt.Sprintf(".druppie/plans/%s/files", planID)
	_ = os.MkdirAll(basePath, 0755)

	var sceneFiles []string
	var audioFiles []string
	var muxedFiles []string
	totalDuration := 0

	if scriptRaw, ok := step.Params["av_script"]; ok {
		// Robust parsing: convert to JSON and back to generic map slice
		// This avoids issues with concrete types from other packages (like workflows.Scene)
		bytes, _ := json.Marshal(scriptRaw)
		var scenes []map[string]interface{}
		if err := json.Unmarshal(bytes, &scenes); err == nil {
			for i, sceneMap := range scenes {
				vFile, _ := sceneMap["video_file"].(string)
				if vFile == "" {
					vFile = fmt.Sprintf("video_scene_%d.mp4", i+1)
				}
				aFile, _ := sceneMap["audio_file"].(string)
				if aFile == "" {
					aFile = fmt.Sprintf("audio_scene_%d.mp3", i+1)
				}

				sceneFiles = append(sceneFiles, vFile)
				audioFiles = append(audioFiles, aFile)

				if d, ok := sceneMap["duration"].(float64); ok {
					totalDuration += int(d)
				} else {
					totalDuration += 5
				}
			}
		}
	}

	if len(sceneFiles) == 0 {
		return fmt.Errorf("no scenes found in av_script for plan %s. cannot merge.", planID)
	}

	// 2. Multiplex Audio/Video for each scene
	for i := 0; i < len(sceneFiles); i++ {
		vIn := filepath.Join(basePath, sceneFiles[i])
		aIn := filepath.Join(basePath, audioFiles[i])
		muxOut := filepath.Join(basePath, fmt.Sprintf("muxed_scene_%d.mp4", i+1))

		outputChan <- fmt.Sprintf("⚙️ [Content Merge] Muxing Scene %d: [V] %s + [A] %s", i+1, sceneFiles[i], audioFiles[i])

		// ffmpeg -i video.mp4 -i audio.mp3 -c:v copy -c:a aac -map 0:v:0 -map 1:a:0 -shortest -y muxed.mp4
		cmd := exec.CommandContext(ctx, ffmpegPath,
			"-i", vIn,
			"-i", aIn,
			"-c:v", "copy",
			"-c:a", "aac",
			"-map", "0:v:0",
			"-map", "1:a:0",
			"-shortest",
			"-y", muxOut)

		if out, err := cmd.CombinedOutput(); err != nil {
			outputChan <- fmt.Sprintf("❌ [FFmpeg Error] Muxing failed for scene %d: %v\nOutput: %s", i+1, err, string(out))
			return fmt.Errorf("FFmpeg muxing failed: %v", err)
		}
		muxedFiles = append(muxedFiles, fmt.Sprintf("muxed_scene_%d.mp4", i+1))
	}

	// 3. Concatenate
	outputChan <- fmt.Sprintf("🎬 [Content Merge] Concatenating %d muxed segments...", len(muxedFiles))
	concatFile := filepath.Join(basePath, "concat_list.txt")
	var sb strings.Builder
	for _, f := range muxedFiles {
		sb.WriteString(fmt.Sprintf("file '%s'\n", f))
	}
	if err := os.WriteFile(concatFile, []byte(sb.String()), 0644); err != nil {
		return fmt.Errorf("failed to create concat list: %w", err)
	}

	finalFile := "final_production.mp4"
	finalPath := filepath.Join(basePath, finalFile)
	// ffmpeg -f concat -safe 0 -i concat_list.txt -c copy -y final_production.mp4
	concatCmd := exec.CommandContext(ctx, ffmpegPath,
		"-f", "concat",
		"-safe", "0",
		"-i", concatFile,
		"-c", "copy",
		"-y", finalPath)

	if out, err := concatCmd.CombinedOutput(); err != nil {
		outputChan <- fmt.Sprintf("❌ [FFmpeg Error] Final concatenation failed: %v\nOutput: %s", err, string(out))
		return fmt.Errorf("FFmpeg concatenation failed: %v", err)
	}

	// Cleanup temp files
	_ = os.Remove(concatFile)
	for _, f := range muxedFiles {
		_ = os.Remove(filepath.Join(basePath, f))
	}

	outputChan <- fmt.Sprintf("✅ [Content Merge] Final video rendered: %s", finalFile)
	outputChan <- "RESULT_VIDEO_FILE=" + finalFile

	// 4. Usage Cost
	computeCost := 0.005 + (float64(totalDuration) * 0.0002)
	outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=0,0,0,%f", computeCost)

	return nil
}

func (e *ContentMergerExecutor) simulate(ctx context.Context, step model.Step, outputChan chan<- string) error {
	totalDuration := 0
	var sceneCount int
	if scriptRaw, ok := step.Params["av_script"]; ok {
		var scenes []interface{}
		bytes, _ := json.Marshal(scriptRaw)
		_ = json.Unmarshal(bytes, &scenes)
		sceneCount = len(scenes)
		for _, s := range scenes {
			if m, ok := s.(map[string]interface{}); ok {
				if d, ok := m["duration"].(float64); ok {
					totalDuration += int(d)
				} else {
					totalDuration += 5
				}
			}
		}
	}

	outputChan <- fmt.Sprintf("⚙️ [Simulated Merge] Processing %d segments...", sceneCount)
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(2 * time.Second):
	}

	finalFile := "final_production.mp4"
	outputChan <- fmt.Sprintf("✅ [Simulated Merge] Final video rendered: %s", finalFile)
	outputChan <- "RESULT_VIDEO_FILE=" + finalFile

	computeCost := 0.005 + (float64(totalDuration) * 0.0002)
	outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=0,0,0,%f", computeCost)
	return nil
}
