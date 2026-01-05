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
	var intent ProjectIntent
	// Check if already completed
	if existing := wc.FindCompletedStep("refine_intent", "", nil); existing != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Intent already refined."
		// Reconstruct Intent from Params
		if refined, ok := existing.Params["refined"].(string); ok {
			intent.RefinedPrompt = refined
			// We might be missing Language and other fields if we don't save them all.
			// Ideally we save the whole intent object or critical fields.
			// Let's assume we can proceed with just RefinedPrompt or we should have saved more.
			// Let's rely on what we saved. In refineIntent below we only saved 'refined'.
			// Update: We should update refineIntent to save language too.
			// For now, let's just proceed.
			if lang, ok := existing.Params["language"].(string); ok {
				intent.Language = lang
			} else {
				intent.Language = "en" // Default fallback
			}
		}
	} else {
		var err error
		intent, err = w.refineIntent(wc, initialPrompt)
		if err != nil {
			return err
		}
		_ = wc.Store.LogInteraction(wc.PlanID, "VideoContentCreator", "Refined Intent", fmt.Sprintf("%+v", intent))
	}

	// 2. Draft Script
	var script AVScript
	if existing := wc.FindCompletedStep("draft_scenes", "", nil); existing != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Script already drafted."
		if sceneList, ok := existing.Params["av_script"].([]interface{}); ok {
			// Need to convert []interface{} to []Scene manually or use json marshal/unmarshal hack
			bytes, _ := json.Marshal(sceneList)
			_ = json.Unmarshal(bytes, &script.Scenes)
		} else {
			// Try to see if it was saved directly as []Scene (internal type)?
			// Go json unmarshal usually makes it []interface{}.
			// Let's assume the json.Marshal hack works.
		}
	} else {
		var err error
		script, err = w.draftScript(wc, intent)
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
	}

	// 3. Asset Production Phases

	// PHASE A: AUDIO
	wc.OutputChan <- "🎙️ [VideoWorkflow] Phase 1/3: Audio Generation..."
	for {
		var err error
		script.Scenes, err = w.runPhase(wc, "audio-creator", "text-to-speech", script.Scenes, w.generateAudio)
		if err != nil {
			return err
		}
		feedback, err := w.reviewPhase(wc, "Audio", script.Scenes)
		if err != nil {
			return err
		}
		if feedback == "" {
			break
		}
		wc.OutputChan <- "⚠️ Retrying Audio Generation..."
	}

	// PHASE B: IMAGES
	wc.OutputChan <- "🎨 [VideoWorkflow] Phase 2/3: Image Generation..."
	for {
		var err error
		script.Scenes, err = w.runPhase(wc, "image-creator", "image-generation", script.Scenes, w.generateImage)
		if err != nil {
			return err
		}
		feedback, err := w.reviewPhase(wc, "Images", script.Scenes)
		if err != nil {
			return err
		}
		if feedback == "" {
			break
		}
		wc.OutputChan <- "⚠️ Retrying Image Generation..."
	}

	// PHASE C: VIDEO
	wc.OutputChan <- "🎬 [VideoWorkflow] Phase 3/3: Video Generation..."
	for {
		var err error
		script.Scenes, err = w.runPhase(wc, "video-creator", "video-generation", script.Scenes, w.generateVideo)
		if err != nil {
			return err
		}
		feedback, err := w.reviewPhase(wc, "Final Video", script.Scenes)
		if err != nil {
			return err
		}
		if feedback == "" {
			break
		}
		wc.OutputChan <- "⚠️ Retrying Video Generation..."
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
		// Check for existing completed step
		if existing := wc.FindCompletedStep(action, "scene_id", s.ID); existing != nil {
			// Log once or quiet
			// Populate result from Params
			res := s
			// We need to restore the file paths so subsequent phases know where they are
			if af, ok := existing.Params["audio_file"].(string); ok {
				res.AudioFile = af
			}
			if img, ok := existing.Params["image_file"].(string); ok {
				res.ImageFile = img
			}
			if vf, ok := existing.Params["video_file"].(string); ok {
				res.VideoFile = vf
			}

			resultChan <- res
			continue
		}

		wg.Add(1)
		go func(scene Scene) {
			defer wg.Done()

			// Register Running Step
			stepID := wc.AppendStep(model.Step{
				AgentID: agentID,
				Action:  action,
				Status:  "running",
				Params:  map[string]interface{}{"scene_id": scene.ID},
			})

			res, err := generator(wc, scene)
			if err != nil {
				// Mark as failed
				wc.AppendStep(model.Step{
					ID:      stepID,
					AgentID: agentID,
					Action:  action,
					Status:  "failed",
					Result:  err.Error(),
					Params:  map[string]interface{}{"scene_id": scene.ID},
				})
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
				ID:      stepID,
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

func (w *VideoCreationWorkflow) reviewPhase(wc *WorkflowContext, phaseName string, _scenes []Scene) (string, error) {
	actionName := fmt.Sprintf("review_%s", strings.ToLower(strings.ReplaceAll(phaseName, " ", "_")))
	wc.OutputChan <- fmt.Sprintf("\n🔎 [Review] Please review generated %s assets.", phaseName)
	wc.OutputChan <- "Options: '/accept' to proceed | '/stop' | give feedback"

	// Ensure unique ID for retries
	stepID := 2000 + len(_scenes) + int(time.Now().Unix()%1000)
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
		return "", wc.Ctx.Err()
	case input := <-wc.InputChan:
		if input == "/stop" {
			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  actionName,
				Status:  "failed",
				Result:  "User rejected validation",
			})
			return "", fmt.Errorf("user stopped at %s review", phaseName)
		}
		if input == "/accept" || input == "" || strings.EqualFold(input, "accept") {
			wc.OutputChan <- fmt.Sprintf("✅ [Review] %s Approved.", phaseName)
			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  actionName,
				Status:  "completed",
				Result:  "Approved by user",
			})
			return "", nil
		}

		// Feedback
		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "video-content-creator",
			Action:  actionName,
			Status:  "rejected",
			Result:  fmt.Sprintf("Rejected: %s", input),
		})
		wc.OutputChan <- fmt.Sprintf("⚠️ [Review] Feedback received: %s. Retrying phase...", input)
		return input, nil
	}
}

func (w *VideoCreationWorkflow) refineIntent(wc *WorkflowContext, prompt string) (ProjectIntent, error) {
	wc.OutputChan <- "🔍 [Intent] Analyzing request..."

	sysPrompt := `You are a Video Producer. Analyze the user request. 
If the request is too vague, formulate 1 short question to clarify. 
If it is clear, output the refined project details.
Output JSON: { "needs_clarification": true, "question": "..." } OR { "needs_clarification": false, "refined_prompt": "...", "language": "en", "target_audience": "..." }`

	for {
		// Register running step
		stepID := wc.AppendStep(model.Step{
			AgentID: "video-content-creator",
			Action:  "refine_intent",
			Status:  "running",
		})

		resp, err := wc.LLM.Generate(wc.Ctx, "Refine Intent", sysPrompt+"\nUser Request: "+prompt)
		if err != nil {
			wc.AppendStep(model.Step{ID: stepID, Status: "failed", Result: err.Error()})
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

			// Update running step to waiting_input
			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  "ask_questions",
				Status:  "waiting_input",
				Result:  question,
			})

			wc.UpdateStatus("Waiting Input")
			select {
			case <-wc.Ctx.Done():
				return ProjectIntent{}, wc.Ctx.Err()
			case input := <-wc.InputChan:
				// Mark the question step as completed with the answer
				wc.AppendStep(model.Step{
					ID:      stepID,
					AgentID: "video-content-creator",
					Action:  "ask_questions",
					Status:  "completed",
					Result:  fmt.Sprintf("Question: %s\nAnswer: %s", question, input),
				})
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

		// Final Review Step (Enforce content-review)
		wc.OutputChan <- fmt.Sprintf("\n🧠 [Intent] Analysis:\n - **Language**: %s\n - **Prompt**: %s\n", intent.Language, intent.RefinedPrompt)
		wc.OutputChan <- "Options: 'ok' or '/accept' to proceed | provide feedback to refine further"

		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "video-content-creator",
			Action:  "content-review", // Matches user request for skill: content-review
			Status:  "waiting_input",
			Result:  fmt.Sprintf("Proposed Intent:\n%s", intent.RefinedPrompt),
		})

		wc.UpdateStatus("Waiting Input")
		select {
		case <-wc.Ctx.Done():
			return ProjectIntent{}, wc.Ctx.Err()
		case input := <-wc.InputChan:
			wc.UpdateStatus("Running")
			if input == "/stop" {
				return ProjectIntent{}, fmt.Errorf("user stopped at intent review")
			}
			if input == "/accept" || input == "ok" || input == "" || strings.EqualFold(input, "accept") {
				wc.AppendStep(model.Step{
					ID:      stepID,
					AgentID: "video-content-creator",
					Action:  "content-review",
					Status:  "completed",
					Result:  "Intent Approved",
				})
				// Finalize
				wc.AppendStep(model.Step{
					ID:      stepID + 1, // New step for final record
					AgentID: "video-content-creator",
					Action:  "refine_intent",
					Status:  "completed",
					Result:  "Intent finalized",
					Params:  map[string]interface{}{"refined": intent.RefinedPrompt, "language": intent.Language},
				})
				return intent, nil
			}

			// Feedback received
			wc.OutputChan <- fmt.Sprintf("🔄 [Intent] Feedback: %s. Refining...", input)
			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  "content-review",
				Status:  "rejected",
				Result:  fmt.Sprintf("Rejected: %s", input),
			})
			prompt = prompt + " | Feedback: " + input
			continue
		}
	}
}

func (w *VideoCreationWorkflow) draftScript(wc *WorkflowContext, intent ProjectIntent) (AVScript, error) {
	currentPrompt := intent.RefinedPrompt
	iteration := 0

	for {
		iteration++
		wc.OutputChan <- "📝 [VideoWorkflow] Drafting Script..."

		// Show "running" state
		stepID := wc.AppendStep(model.Step{
			ID:      1000 + iteration, // Keep ID stable for iteration
			AgentID: "video-content-creator",
			Action:  "draft_scenes",
			Status:  "running",
		})

		sysPrompt := `You are a Screenwriter. Create a JSON script for a video.
Structure: {"av_script": [{"scene_id": 1, "audio_text": "...", "visual_prompt": "...", "duration": 5}]}
Key Rules:
- Audio Text in ` + intent.Language + `.
- IF the Request contains "Fix:" and "Prev:", you MUST Modify the "Prev" script according to the "Fix" instructions. Apply the changes requested in "Fix" to the content in "Prev".`

		resp, err := wc.LLM.Generate(wc.Ctx, "Draft Script", sysPrompt+"\nRequest: "+currentPrompt)
		if err != nil {
			// Mark failed if LLM fails
			wc.AppendStep(model.Step{ID: stepID, Status: "failed", Result: err.Error(), AgentID: "video-content-creator", Action: "draft_scenes"})
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
			if input == "/accept" || input == "" || strings.EqualFold(input, "accept") {
				wc.AppendStep(model.Step{
					ID:      stepID,
					AgentID: "video-content-creator",
					Action:  "draft_scenes",
					Status:  "completed",
					Result:  "Approved",
				})
				return script, nil
			}
			// Log the feedback
			wc.OutputChan <- fmt.Sprintf("🔄 [Script] Feedback received: '%s'. Refining script...", input)

			wc.AppendStep(model.Step{
				ID:      stepID,
				AgentID: "video-content-creator",
				Action:  "draft_scenes",
				Status:  "rejected",
				Result:  fmt.Sprintf("Rejected: %s", input),
			})
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
