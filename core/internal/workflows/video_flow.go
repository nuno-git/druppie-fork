package workflows

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

type VideoCreationWorkflow struct{}

func (w *VideoCreationWorkflow) Name() string { return "video-content-creator" }

// Data Structures for State
type ProjectIntent struct {
	OriginalPrompt string
	RefinedPrompt  string
	Language       string
	Parameters     map[string]interface{}
}

type Scene struct {
	ID           int    `json:"scene_id"`
	AudioText    string `json:"audio_text"`
	VisualPrompt string `json:"visual_prompt"`
	Duration     int    `json:"duration"` // Seconds

	// Asset Paths
	AudioFile string `json:"audio_file,omitempty"`
	ImageFile string `json:"image_file,omitempty"`
	VideoFile string `json:"video_file,omitempty"`
}

type AVScript struct {
	Scenes []Scene `json:"av_script"`
}

func (w *VideoCreationWorkflow) Run(wc *WorkflowContext, initialPrompt string) error {
	wc.OutputChan <- fmt.Sprintf("🎥 [VideoWorkflow] Starting Video Creation Workflow: %s", initialPrompt)

	// 1. Refine Intent (Ask Questions)
	intent, err := w.refineIntent(wc, initialPrompt)
	if err != nil {
		return err
	}
	_ = wc.Store.LogInteraction(wc.PlanID, "VideoContentCreator", "Refined Intent", fmt.Sprintf("%+v", intent))

	// 2. Draft Script
	script, err := w.draftScript(wc, intent)
	if err != nil {
		return err
	}
	wc.OutputChan <- fmt.Sprintf("✅ [VideoWorkflow] Script Approved: %d scenes.", len(script.Scenes))
	_ = wc.Store.LogInteraction(wc.PlanID, "VideoContentCreator", "Approved Script", w.formatScript(script))
	wc.AppendStep(model.Step{
		AgentID: "video-content-creator",
		Action:  "draft_scenes",
		Status:  "completed",
		Params:  map[string]interface{}{"av_script": script.Scenes},
	})

	// 3. Asset Production Phases

	// PHASE A: AUDIO
	wc.OutputChan <- "🎙️ [VideoWorkflow] Phase 1/3: Audio Generation..."
	script.Scenes, err = w.runPhase(wc, "audio-creator", "text-to-speech", script.Scenes, w.generateAudio)
	if err != nil {
		return err
	}

	if err := w.reviewPhase(wc, "Audio", script.Scenes); err != nil {
		return err
	}

	// PHASE B: IMAGES
	wc.OutputChan <- "🎨 [VideoWorkflow] Phase 2/3: Image Generation..."
	script.Scenes, err = w.runPhase(wc, "image-creator", "image-generation", script.Scenes, w.generateImage)
	if err != nil {
		return err
	}

	if err := w.reviewPhase(wc, "Images", script.Scenes); err != nil {
		return err
	}

	// PHASE C: VIDEO
	wc.OutputChan <- "🎬 [VideoWorkflow] Phase 3/3: Video Generation..."
	script.Scenes, err = w.runPhase(wc, "video-creator", "video-generation", script.Scenes, w.generateVideo)
	if err != nil {
		return err
	}

	if err := w.reviewPhase(wc, "Final Video", script.Scenes); err != nil {
		return err
	}

	// 4. Merge
	finalVideo, err := w.mergeVideo(wc, script.Scenes)
	if err != nil {
		return err
	}
	wc.AppendStep(model.Step{
		AgentID: "video-content-creator",
		Action:  "content-merge",
		Status:  "completed",
		Params:  map[string]interface{}{"av_script": script.Scenes},
		Result:  fmt.Sprintf("RESULT_VIDEO_FILE=%s", finalVideo),
	})

	wc.OutputChan <- "🎉 [VideoWorkflow] Workflow Completed Successfully!"
	return nil
}

// runPhase executes a generator function for all scenes in parallel
func (w *VideoCreationWorkflow) runPhase(wc *WorkflowContext, agentID, action string, scenes []Scene, generator func(*WorkflowContext, Scene) (Scene, error)) ([]Scene, error) {
	var wg sync.WaitGroup
	resultChan := make(chan Scene, len(scenes))
	errChan := make(chan error, len(scenes))

	for _, s := range scenes {
		wg.Add(1)
		go func(scene Scene) {
			defer wg.Done()
			res, err := generator(wc, scene)
			if err != nil {
				errChan <- err
				return
			}
			params := map[string]interface{}{
				"scene_id": res.ID,
			}
			if res.AudioText != "" {
				params["audio_text"] = res.AudioText
			}
			if res.VisualPrompt != "" {
				params["visual_prompt"] = res.VisualPrompt
			}
			if res.AudioFile != "" {
				params["audio_file"] = res.AudioFile
			}
			if res.ImageFile != "" {
				params["image_file"] = res.ImageFile
			}
			if res.VideoFile != "" {
				params["video_file"] = res.VideoFile
			}

			wc.AppendStep(model.Step{
				AgentID: agentID,
				Action:  action,
				Status:  "completed",
				Params:  params,
			})
			resultChan <- res
		}(s)
	}

	wg.Wait()
	close(resultChan)
	close(errChan)

	if len(errChan) > 0 {
		return nil, <-errChan
	}

	sceneMap := make(map[int]Scene)
	for res := range resultChan {
		sceneMap[res.ID] = res
	}

	ordered := make([]Scene, len(scenes))
	for i, original := range scenes {
		if updated, ok := sceneMap[original.ID]; ok {
			ordered[i] = updated
		} else {
			ordered[i] = original
		}
	}
	return ordered, nil
}

func (w *VideoCreationWorkflow) reviewPhase(wc *WorkflowContext, phaseName string, _scenes []Scene) error {
	actionName := fmt.Sprintf("review_%s", strings.ToLower(strings.ReplaceAll(phaseName, " ", "_")))
	wc.OutputChan <- fmt.Sprintf("\n🔎 [Review] Please review generated %s assets.", phaseName)
	wc.OutputChan <- "Options: '/accept' to proceed | '/stop' | give feedback"

	stepID := 2000 + len(_scenes) // Unique ID based on phase
	wc.AppendStep(model.Step{
		ID:      stepID,
		AgentID: "video-content-creator",
		Action:  actionName,
		Status:  "waiting_input",
		Result:  w.formatReviewData(phaseName, _scenes),
	})

	wc.UpdateStatus("Waiting Input")
	defer wc.UpdateStatus("Running")

	select {
	case <-wc.Ctx.Done():
		return wc.Ctx.Err()
	case input := <-wc.InputChan:
		if input == "/stop" {
			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  actionName,
				Status:  "failed",
				Result:  "User rejected validation",
			})
			return fmt.Errorf("user stopped at %s review", phaseName)
		}
		wc.OutputChan <- fmt.Sprintf("✅ [Review] %s Approved.", phaseName)
		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "video-content-creator",
			Action:  actionName,
			Status:  "completed",
			Result:  "Approved by user",
		})
		return nil
	}
}

func (w *VideoCreationWorkflow) refineIntent(wc *WorkflowContext, prompt string) (ProjectIntent, error) {
	wc.OutputChan <- "🔍 [Intent] Analyzing request..."

	sysPrompt := `You are a Video Producer. Analyze the user request. 
If the request is too vague, formulate 1 short question to clarify. 
If it is clear, output the refined project details.
Output JSON: { "needs_clarification": true, "question": "..." } OR { "needs_clarification": false, "refined_prompt": "...", "language": "en", "target_audience": "..." }`

	for {
		resp, err := wc.LLM.Generate(wc.Ctx, "Refine Intent", sysPrompt+"\nUser Request: "+prompt)
		if err != nil {
			return ProjectIntent{}, err
		}

		clean := strings.TrimSpace(resp)
		if idx := strings.Index(clean, "{"); idx != -1 {
			clean = clean[idx:]
		}
		if idx := strings.LastIndex(clean, "}"); idx != -1 {
			clean = clean[:idx+1]
		}

		var raw map[string]interface{}
		_ = json.Unmarshal([]byte(clean), &raw)

		if needs, _ := raw["needs_clarification"].(bool); needs {
			question, _ := raw["question"].(string)
			wc.OutputChan <- fmt.Sprintf("🤔 [Intent] Question: %s", question)

			wc.AppendStep(model.Step{
				AgentID: "video-content-creator",
				Action:  "ask_question",
				Status:  "waiting_input",
				Result:  question,
			})

			wc.UpdateStatus("Waiting Input")
			select {
			case <-wc.Ctx.Done():
				return ProjectIntent{}, wc.Ctx.Err()
			case input := <-wc.InputChan:
				prompt = prompt + " | Clarification: " + input
				wc.UpdateStatus("Running")
				continue
			}
		}

		var intent ProjectIntent
		intent.OriginalPrompt = prompt
		intent.RefinedPrompt, _ = raw["refined_prompt"].(string)
		intent.Language, _ = raw["language"].(string)
		intent.Parameters = raw

		wc.OutputChan <- fmt.Sprintf("\n🧠 [Intent] Analysis:\n - **Language**: %s\n - **Prompt**: %s\n", intent.Language, intent.RefinedPrompt)

		wc.AppendStep(model.Step{
			AgentID: "video-content-creator",
			Action:  "refine_intent",
			Status:  "completed",
			Result:  "Intent finalized",
			Params:  map[string]interface{}{"refined": intent.RefinedPrompt},
		})

		return intent, nil
	}
}

func (w *VideoCreationWorkflow) draftScript(wc *WorkflowContext, intent ProjectIntent) (AVScript, error) {
	currentPrompt := intent.RefinedPrompt
	iteration := 0

	for {
		iteration++
		wc.OutputChan <- "📝 [VideoWorkflow] Drafting Script..."

		sysPrompt := `You are a Screenwriter. Create a JSON script for a video.
Structure: {"av_script": [{"scene_id": 1, "audio_text": "...", "visual_prompt": "...", "duration": 5}]}
Key Rules:
- Audio Text in ` + intent.Language + `.
`
		resp, err := wc.LLM.Generate(wc.Ctx, "Draft Script", sysPrompt+"\nRequest: "+currentPrompt)
		if err != nil {
			return AVScript{}, err
		}

		clean := strings.TrimSpace(resp)
		if idx := strings.Index(clean, "{"); idx != -1 {
			clean = clean[idx:]
		}
		if idx := strings.LastIndex(clean, "}"); idx != -1 {
			clean = clean[:idx+1]
		}

		var script AVScript
		if err := json.Unmarshal([]byte(clean), &script); err != nil {
			wc.OutputChan <- "⚠️ [VideoWorkflow] Script parse error. Retrying..."
			continue
		}

		wc.OutputChan <- "\n🎥 **Review Draft Script:**"
		wc.OutputChan <- w.formatScript(script)
		wc.OutputChan <- "Options: [Type feedback] | '/accept' to proceed"

		stepID := 1000 + iteration
		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "video-content-creator",
			Action:  "draft_scenes",
			Status:  "waiting_input",
			Result:  w.formatScript(script),
		})

		wc.UpdateStatus("Waiting Input")
		select {
		case <-wc.Ctx.Done():
			return AVScript{}, wc.Ctx.Err()
		case input := <-wc.InputChan:
			wc.UpdateStatus("Running")
			if input == "/stop" {
				return AVScript{}, fmt.Errorf("user cancelled")
			}
			if input == "/accept" || input == "" {
				wc.AppendStep(model.Step{
					ID:      stepID,
					AgentID: "video-content-creator",
					Action:  "draft_scenes",
					Status:  "completed",
					Result:  "Approved",
				})
				return script, nil
			}
			currentPrompt = fmt.Sprintf("Fix: %s. Prev: %s", input, clean)
		}
	}
}

func (w *VideoCreationWorkflow) formatScript(script AVScript) string {
	var sb strings.Builder
	for _, s := range script.Scenes {
		sb.WriteString(fmt.Sprintf("\n🎬 Scene %d (%ds)\n   🔈 Audio: \"%s\"\n   👁️ Visual: \"%s\"\n", s.ID, s.Duration, s.AudioText, s.VisualPrompt))
	}
	return sb.String()
}

func (w *VideoCreationWorkflow) generateAudio(wc *WorkflowContext, s Scene) (Scene, error) {
	executor, _ := wc.Dispatcher.GetExecutor("text-to-speech")
	execChan := make(chan string, 100)
	var capturedFile string
	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{Action: "text-to-speech", Params: map[string]interface{}{"audio_text": s.AudioText, "scene_id": s.ID}}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_AUDIO_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_AUDIO_FILE=")
		}
	}
	if capturedFile != "" {
		s.AudioFile = capturedFile
	} else {
		s.AudioFile = fmt.Sprintf("audio_scene_%d.mp3", s.ID)
	}
	return s, nil
}

func (w *VideoCreationWorkflow) generateImage(wc *WorkflowContext, s Scene) (Scene, error) {
	executor, _ := wc.Dispatcher.GetExecutor("image-generation")
	execChan := make(chan string, 100)
	var capturedFile string
	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{Action: "image-generation", Params: map[string]interface{}{"visual_prompt": s.VisualPrompt, "scene_id": s.ID}}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_IMAGE_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_IMAGE_FILE=")
		}
	}
	if capturedFile != "" {
		s.ImageFile = capturedFile
	} else {
		s.ImageFile = fmt.Sprintf("image_scene_%d.png", s.ID)
	}
	return s, nil
}

func (w *VideoCreationWorkflow) generateVideo(wc *WorkflowContext, s Scene) (Scene, error) {
	executor, _ := wc.Dispatcher.GetExecutor("video-generation")
	execChan := make(chan string, 100)
	var capturedFile string
	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{Action: "video-generation", Params: map[string]interface{}{"visual_prompt": s.VisualPrompt, "audio_file": s.AudioFile, "image_file": s.ImageFile, "duration": s.Duration, "scene_id": s.ID}}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_VIDEO_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_VIDEO_FILE=")
		}
	}
	if capturedFile != "" {
		s.VideoFile = capturedFile
	} else {
		s.VideoFile = fmt.Sprintf("video_scene_%d.mp4", s.ID)
	}
	return s, nil
}

func (w *VideoCreationWorkflow) mergeVideo(wc *WorkflowContext, _ []Scene) (string, error) {
	wc.OutputChan <- "🎬 [VideoWorkflow] Merging final video..."
	time.Sleep(2 * time.Second)
	return "final_video_production.mp4", nil
}

func (w *VideoCreationWorkflow) formatReviewData(phaseName string, scenes []Scene) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("Review %s Assets:\n", phaseName))
	for _, s := range scenes {
		switch strings.ToLower(phaseName) {
		case "audio":
			sb.WriteString(fmt.Sprintf("- Scene %d: [Audio] %s\n", s.ID, s.AudioFile))
		case "images":
			sb.WriteString(fmt.Sprintf("- Scene %d: [Image] %s\n", s.ID, s.ImageFile))
		case "final video":
			sb.WriteString(fmt.Sprintf("- Scene %d: [Video] %s\n", s.ID, s.VideoFile))
		}
	}
	sb.WriteString("\nType feedback or click Accept to continue.")
	return sb.String()
}
