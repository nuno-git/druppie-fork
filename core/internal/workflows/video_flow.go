package workflows

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"strconv"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

type VideoCreationWorkflow struct{}

func (w *VideoCreationWorkflow) Name() string { return "video_content_creator" }

// Data Structures for State
type ProjectIntent struct {
	OriginalPrompt string
	RefinedPrompt  string
	Language       string
	TargetAudience string
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
	// Check if already completed (Planner uses 'ask_questions' for the initial phase)
	if existing := wc.FindCompletedStep("ask_questions", "", nil); existing != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Intent already refined."
		if lang, ok := existing.Params["language"].(string); ok {
			intent.Language = lang
		} else {
			intent.Language = "nl" // Default for this plan
		}
		// Refined prompt might be in the result or prompt field of intent
		intent.RefinedPrompt = initialPrompt
	} else if existing := wc.FindCompletedStep("refine_intent", "", nil); existing != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Intent already refined (refine_intent)."
		intent.RefinedPrompt, _ = existing.Params["refined_prompt"].(string)
		intent.Language, _ = existing.Params["language"].(string)
		intent.TargetAudience, _ = existing.Params["target_audience"].(string)
		if intent.RefinedPrompt == "" {
			intent.RefinedPrompt = initialPrompt
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
	if existing := wc.FindCompletedStep("content_review", "", nil); existing != nil && existing.Params["av_script"] != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Script already drafted (from content_review)."
		if sceneList, ok := existing.Params["av_script"].([]interface{}); ok {
			bytes, _ := json.Marshal(sceneList)
			_ = json.Unmarshal(bytes, &script.Scenes)
		}
	} else if existing := wc.FindCompletedStep("draft_scenes", "", nil); existing != nil {
		wc.OutputChan <- "⏩ [VideoWorkflow] Resuming: Script already drafted."
		if sceneList, ok := existing.Params["av_script"].([]interface{}); ok {
			bytes, _ := json.Marshal(sceneList)
			_ = json.Unmarshal(bytes, &script.Scenes)
		}
	} else {
		var err error
		script, err = w.draftScript(wc, intent)
		if err != nil {
			return err
		}
		wc.OutputChan <- fmt.Sprintf("✅ [VideoWorkflow] Script Approved: %d scenes.", len(script.Scenes))
		_ = wc.Store.LogInteraction(wc.PlanID, "VideoContentCreator", "Approved Script", w.formatScript(script))
	}

	// 3. Asset Production Phases

	// PHASE A: AUDIO
	wc.OutputChan <- "🎙️ [VideoWorkflow] Phase 1/3: Audio Generation..."
	for {
		var err error
		script.Scenes, err = w.runPhase(wc, "audio_creator", "text_to_speech", script.Scenes, func(wc *WorkflowContext, s Scene) (Scene, *model.TokenUsage, error) {
			return w.generateAudio(wc, s, intent.Language)
		})
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
		script.Scenes, err = w.runPhase(wc, "image_creator", "image_generation", script.Scenes, w.generateImage)
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
		script.Scenes, err = w.runPhase(wc, "video_creator", "video_generation", script.Scenes, w.generateVideo)
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
	finalVideo, usage, err := w.mergeVideo(wc, script.Scenes)
	if err != nil {
		return err
	}
	wc.AppendStep(model.Step{
		AgentID: "video_content_creator",
		Action:  "content_merge",
		Status:  "completed",
		Params:  map[string]interface{}{"av_script": script.Scenes},
		Result:  fmt.Sprintf("RESULT_VIDEO_FILE=%s", finalVideo),
		Usage:   usage,
	})

	wc.OutputChan <- "🎉 [VideoWorkflow] Workflow Completed Successfully!"
	return nil
}

// runPhase executes a generator function for all scenes in parallel
func (w *VideoCreationWorkflow) runPhase(wc *WorkflowContext, agentID, action string, scenes []Scene, generator func(*WorkflowContext, Scene) (Scene, *model.TokenUsage, error)) ([]Scene, error) {
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

			res, usagePtr, err := generator(wc, scene)
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
				Usage:   usagePtr,
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
		AgentID: "video_content_creator",
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
				AgentID: "video_content_creator",
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
				AgentID: "video_content_creator",
				Action:  actionName,
				Status:  "completed",
				Result:  "Approved by user",
			})
			return "", nil
		}

		// Feedback
		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "video_content_creator",
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
If the request is too vague, formulate 1 short question to clarify (in the user's language). 
If it is clear, output the refined project details.
Detect the language of the user request (e.g. 'nl', 'en', 'fr') and use it for the "language" field.
Output JSON: { "needs_clarification": true, "question": "..." } OR { "needs_clarification": false, "refined_prompt": "...", "language": "detected_code", "target_audience": "..." }`
	// Try to load prompt from agent definition
	if agent, err := wc.GetAgent("video_content_creator"); err == nil {
		if p, ok := agent.Prompts["refine_intent"]; ok && p != "" {
			sysPrompt = p
		}
	}

	refineStepID := 0
	questionStepID := 0
	var cumulativeUsage model.TokenUsage

	for {
		// Register running step
		refineStepID = wc.AppendStep(model.Step{
			ID:      refineStepID,
			AgentID: "video_content_creator",
			Action:  "refine_intent",
			Status:  "running",
			Usage:   &cumulativeUsage,
		})

		// Retrieve Provider from Agent Definition
		var providerName string
		if agent, err := wc.GetAgent("video_content_creator"); err == nil {
			providerName = agent.Provider
		}

		resp, usagePtr, err := wc.CallLLM(sysPrompt+"\nUser Request: "+prompt, "Refine Intent", providerName)
		if usagePtr != nil {
			cumulativeUsage.PromptTokens += usagePtr.PromptTokens
			cumulativeUsage.CompletionTokens += usagePtr.CompletionTokens
			cumulativeUsage.TotalTokens += usagePtr.TotalTokens
			cumulativeUsage.EstimatedCost += usagePtr.EstimatedCost
		}

		if wc.UpdateTokenUsage != nil && usagePtr != nil {
			wc.UpdateTokenUsage(*usagePtr)
		}
		if err != nil {
			usageVal := model.TokenUsage{} // Default empty
			if usagePtr != nil {
				usageVal = *usagePtr
			}
			wc.AppendStep(model.Step{ID: refineStepID, Status: "failed", Result: err.Error(), Usage: &usageVal})
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

			// Update last refine_intent to complete/paused?
			// Actually just add the question step.
			questionStepID = wc.AppendStep(model.Step{
				ID:      questionStepID,
				AgentID: "video_content_creator",
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
					ID:      questionStepID,
					AgentID: "video_content_creator",
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
		intent.TargetAudience, _ = raw["target_audience"].(string)
		intent.Parameters = raw

		// 4. Mark "refine_intent" as COMPLETED with Usage
		wc.AppendStep(model.Step{
			ID:      refineStepID,
			AgentID: "video_content_creator",
			Action:  "refine_intent",
			Status:  "completed",
			Result:  "Intent refined",
			Usage:   &cumulativeUsage,
		})

		// 5. Create NEW step for content_review
		reviewStepID := wc.AppendStep(model.Step{
			AgentID: "video_content_creator",
			Action:  "content_review", // Matches user request for skill: content_review
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
					ID:      reviewStepID,
					AgentID: "video_content_creator",
					Action:  "content_review",
					Status:  "completed",
					Result:  "Intent Approved",
				})
				// Finalize (Optional: Record final intent params if needed, or just return)
				// We already marked refine_intent as completed.
				return intent, nil
			}

			// Feedback received
			wc.OutputChan <- fmt.Sprintf("🔄 [Intent] Feedback: %s. Refining...", input)
			wc.AppendStep(model.Step{
				ID:      reviewStepID,
				AgentID: "video_content_creator",
				Action:  "content_review",
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
	draftStepID := 0
	reviewStepID := 0
	var cumulativeUsage model.TokenUsage

	for {
		iteration++
		if iteration > 5 {
			return AVScript{}, fmt.Errorf("failed to draft valid script after 5 attempts")
		}
		wc.OutputChan <- "📝 [VideoWorkflow] Drafting Script..."

		// Show "running" state
		draftStepID = wc.AppendStep(model.Step{
			ID:      draftStepID,
			AgentID: "video_content_creator",
			Action:  "draft_scenes",
			Status:  "running",
			Usage:   &cumulativeUsage,
		})

		sysPrompt := `You are a Screenwriter. Create a JSON script for a video.
Structure: {"av_script": [{"scene_id": 1, "audio_text": "...", "visual_prompt": "...", "duration": 5}]}
Key Rules:
- Audio Text in %LANGUAGE%.
- IF the Request contains "Fix:" and "Prev:", you MUST Modify the "Prev" script according to the "Fix" instructions. Apply the changes requested in "Fix" to the content in "Prev".`

		// Try to load prompt from agent definition
		if agent, err := wc.GetAgent("video_content_creator"); err == nil {
			if p, ok := agent.Prompts["draft_script"]; ok && p != "" {
				sysPrompt = p
			}
		}

		// Replace placeholders
		sysPrompt = strings.ReplaceAll(sysPrompt, "%LANGUAGE%", intent.Language)

		// Retrieve Provider from Agent Definition
		var providerName string
		if agent, err := wc.GetAgent("video_content_creator"); err == nil {
			providerName = agent.Provider
		}

		// Enrich request with intent details
		reqPrompt := currentPrompt
		if intent.Language != "" {
			reqPrompt += "\nLanguage: " + intent.Language
		}
		if intent.TargetAudience != "" {
			reqPrompt += "\nTarget Audience: " + intent.TargetAudience
		}

		resp, usagePtr, err := wc.CallLLM(sysPrompt+"\nRequest: "+reqPrompt, "Draft Script", providerName)
		if usagePtr != nil {
			cumulativeUsage.PromptTokens += usagePtr.PromptTokens
			cumulativeUsage.CompletionTokens += usagePtr.CompletionTokens
			cumulativeUsage.TotalTokens += usagePtr.TotalTokens
			cumulativeUsage.EstimatedCost += usagePtr.EstimatedCost
		}

		if wc.UpdateTokenUsage != nil && usagePtr != nil {
			wc.UpdateTokenUsage(*usagePtr)
		}
		if err != nil {
			usageVal := model.TokenUsage{}
			if usagePtr != nil {
				usageVal = *usagePtr
			}
			wc.AppendStep(model.Step{ID: draftStepID, Status: "failed", Result: err.Error(), AgentID: "video_content_creator", Action: "draft_scenes", Usage: &usageVal})
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

		if len(script.Scenes) == 0 {
			wc.OutputChan <- "⚠️ [VideoWorkflow] Script generated with 0 scenes. Retrying..."
			continue
		}

		wc.OutputChan <- "\n🎥 **Review Draft Script:**"
		wc.OutputChan <- w.formatScript(script)
		wc.OutputChan <- "Options: [Type feedback] | '/accept' to proceed"

		// Mark generation completed
		wc.AppendStep(model.Step{
			ID:      draftStepID,
			AgentID: "video_content_creator",
			Action:  "draft_scenes",
			Status:  "completed",
			Result:  "Script Drafted",
			Params:  map[string]interface{}{"av_script": script.Scenes},
			Usage:   &cumulativeUsage,
		})

		// Create Review Step
		reviewStepID = wc.AppendStep(model.Step{
			ID:      reviewStepID,
			AgentID: "video_content_creator",
			Action:  "draft_scenes_review",
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
					ID:      reviewStepID,
					AgentID: "video_content_creator",
					Action:  "draft_scenes_review",
					Status:  "completed",
					Result:  "Approved",
				})
				return script, nil
			}
			// Log the feedback
			wc.OutputChan <- fmt.Sprintf("🔄 [Script] Feedback received: '%s'. Refining script...", input)

			wc.AppendStep(model.Step{
				ID:      reviewStepID,
				AgentID: "video_content_creator",
				Action:  "draft_scenes_review",
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

func (w *VideoCreationWorkflow) generateAudio(wc *WorkflowContext, s Scene, language string) (Scene, *model.TokenUsage, error) {
	executor, _ := wc.Dispatcher.GetExecutor("text-to-speech")
	execChan := make(chan string, 100)
	var capturedFile string
	var usage *model.TokenUsage
	go func() {
		params := map[string]interface{}{
			"audio_text": s.AudioText,
			"scene_id":   s.ID,
			"plan_id":    wc.PlanID,
		}
		if language != "" {
			params["language"] = language
		}
		_ = executor.Execute(wc.Ctx, model.Step{Action: "text_to_speech", Params: params}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_AUDIO_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_AUDIO_FILE=")
		}
		if strings.HasPrefix(msg, "RESULT_DURATION=") {
			dStr := strings.TrimPrefix(msg, "RESULT_DURATION=")
			dStr = strings.TrimSuffix(dStr, "s")
			if dInt, err := strconv.Atoi(dStr); err == nil {
				s.Duration = dInt
			}
		}
		if u := parseUsage(msg); u != nil {
			usage = u
		}
	}
	if capturedFile != "" {
		s.AudioFile = capturedFile
	} else {
		s.AudioFile = fmt.Sprintf("audio_scene_%d.mp3", s.ID)
	}
	return s, usage, nil
}

func (w *VideoCreationWorkflow) generateImage(wc *WorkflowContext, s Scene) (Scene, *model.TokenUsage, error) {
	executor, _ := wc.Dispatcher.GetExecutor("image_generation")
	execChan := make(chan string, 100)
	var capturedFile string
	var usage *model.TokenUsage
	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{Action: "image_generation", Params: map[string]interface{}{"visual_prompt": s.VisualPrompt, "scene_id": s.ID, "plan_id": wc.PlanID}}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_IMAGE_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_IMAGE_FILE=")
		}
		if u := parseUsage(msg); u != nil {
			usage = u
		}
	}
	if capturedFile != "" {
		s.ImageFile = capturedFile
	} else {
		s.ImageFile = fmt.Sprintf("image_scene_%d.png", s.ID)
	}
	return s, usage, nil
}

func (w *VideoCreationWorkflow) generateVideo(wc *WorkflowContext, s Scene) (Scene, *model.TokenUsage, error) {
	executor, _ := wc.Dispatcher.GetExecutor("video_generation")
	execChan := make(chan string, 100)
	var capturedFile string
	var usage *model.TokenUsage
	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{Action: "video_generation", Params: map[string]interface{}{"visual_prompt": s.VisualPrompt, "audio_file": s.AudioFile, "image_file": s.ImageFile, "duration": s.Duration, "scene_id": s.ID, "plan_id": wc.PlanID}}, execChan)
		close(execChan)
	}()
	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_VIDEO_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_VIDEO_FILE=")
		}
		if u := parseUsage(msg); u != nil {
			usage = u
		}
	}
	if capturedFile != "" {
		s.VideoFile = capturedFile
	} else {
		s.VideoFile = fmt.Sprintf("video_scene_%d.mp4", s.ID)
	}
	return s, usage, nil
}

func parseUsage(msg string) *model.TokenUsage {
	if strings.HasPrefix(msg, "RESULT_TOKEN_USAGE=") {
		parts := strings.Split(strings.TrimPrefix(msg, "RESULT_TOKEN_USAGE="), ",")
		if len(parts) >= 3 {
			p, _ := strconv.Atoi(parts[0])
			c, _ := strconv.Atoi(parts[1])
			t, _ := strconv.Atoi(parts[2])
			var cost float64
			if len(parts) >= 4 {
				cost, _ = strconv.ParseFloat(parts[3], 64)
			}
			return &model.TokenUsage{
				PromptTokens:     p,
				CompletionTokens: c,
				TotalTokens:      t,
				EstimatedCost:    cost,
			}
		}
	}
	return nil
}

func (w *VideoCreationWorkflow) mergeVideo(wc *WorkflowContext, scenes []Scene) (string, *model.TokenUsage, error) {
	executor, err := wc.Dispatcher.GetExecutor("content_merge")
	if err != nil {
		return "", nil, err
	}

	execChan := make(chan string, 100)
	var capturedFile string
	var usage *model.TokenUsage

	go func() {
		_ = executor.Execute(wc.Ctx, model.Step{
			Action: "content_merge",
			Params: map[string]interface{}{
				"av_script": scenes,
				"plan_id":   wc.PlanID,
			},
		}, execChan)
		close(execChan)
	}()

	for msg := range execChan {
		wc.OutputChan <- fmt.Sprintf("  %s", msg)
		if strings.HasPrefix(msg, "RESULT_VIDEO_FILE=") {
			capturedFile = strings.TrimPrefix(msg, "RESULT_VIDEO_FILE=")
		}
		if u := parseUsage(msg); u != nil {
			usage = u
		}
	}

	if usage != nil && wc.UpdateTokenUsage != nil {
		wc.UpdateTokenUsage(*usage)
	}

	return capturedFile, usage, nil
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
