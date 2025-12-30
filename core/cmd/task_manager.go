package main

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/executor"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/planner"
	"github.com/sjhoeksma/druppie/core/internal/workflows"
)

// TaskStatus definition
type TaskStatus string

const (
	TaskStatusPending      TaskStatus = "Pending"
	TaskStatusRunning      TaskStatus = "Running"
	TaskStatusWaitingInput TaskStatus = "Waiting Input"
	TaskStatusCompleted    TaskStatus = "Completed"
	TaskStatusError        TaskStatus = "Error"
)

// TaskManager manages active planning tasks
type TaskManager struct {
	mu              sync.Mutex
	tasks           map[string]*Task
	planner         *planner.Planner
	OutputChan      chan string // Channel to send logs/output to the main CLI loop
	TaskDoneChan    chan string // Signals when a task is fully complete
	dispatcher      *executor.Dispatcher
	workflowManager *workflows.Manager
}

type Task struct {
	ID        string
	Plan      *model.ExecutionPlan
	Status    TaskStatus
	InputChan chan string // Channel to receive user input (answers)
	Ctx       context.Context
	Cancel    context.CancelFunc
}

func NewTaskManager(p *planner.Planner) *TaskManager {
	tm := &TaskManager{
		tasks:           make(map[string]*Task),
		planner:         p,
		OutputChan:      make(chan string, 100),
		TaskDoneChan:    make(chan string, 10),
		dispatcher:      executor.NewDispatcher(),
		workflowManager: workflows.NewManager(),
	}
	return tm
}

// StartTask creates a background task for a given plan and starts the execution loop
func (tm *TaskManager) StartTask(ctx context.Context, plan model.ExecutionPlan) *Task {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	ctx, cancel := context.WithCancel(ctx)
	task := &Task{
		ID:        plan.ID,
		Plan:      &plan,
		Status:    TaskStatusPending,
		InputChan: make(chan string), // Unbuffered, wait for receiver
		Ctx:       ctx,
		Cancel:    cancel,
	}
	tm.tasks[plan.ID] = task

	tm.OutputChan <- fmt.Sprintf("[Task Manager] Started task %s", plan.ID)

	go tm.runTaskLoop(task)
	return task
}

// GetTask returns a task by ID
func (tm *TaskManager) GetSingleActiveTask() *Task {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	// Return the most recent or single active task
	// Ideally we find one that is running or waiting
	for _, t := range tm.tasks {
		if t.Status != TaskStatusCompleted && t.Status != TaskStatusError {
			return t
		}
	}
	return nil
}

func (tm *TaskManager) ListTasks() []string {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	var list []string
	for id, t := range tm.tasks {
		list = append(list, fmt.Sprintf("%s [%s]", id, t.Status))
	}
	return list
}

func (tm *TaskManager) StopTask(id string) {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	if t, ok := tm.tasks[id]; ok {
		t.Cancel()
		t.Status = TaskStatusError // Cancelled
		delete(tm.tasks, id)
		tm.OutputChan <- fmt.Sprintf("[Task Manager] Stopped task %s", id)
	}
}

// runTaskLoop is the background worker for a single plan
func (tm *TaskManager) runTaskLoop(task *Task) {
	defer func() {
		// Cleanup
		task.Status = TaskStatusCompleted
		tm.TaskDoneChan <- task.ID
	}()

	task.Status = TaskStatusRunning

	// --- INTERCEPTION: NATIVE WORKFLOW ENGINE ---
	if len(task.Plan.SelectedAgents) > 0 {
		agentID := task.Plan.SelectedAgents[0]
		if wf, ok := tm.workflowManager.GetWorkflow(agentID); ok {
			tm.OutputChan <- fmt.Sprintf("🚀 [Task Manager] Switching to Native Workflow Engine for agent: %s", agentID)

			// Build Context
			wc := &workflows.WorkflowContext{
				Ctx:        task.Ctx,
				LLM:        tm.planner.GetLLM(),
				Dispatcher: tm.dispatcher,
				OutputChan: tm.OutputChan,
				InputChan:  task.InputChan,
				UpdateStatus: func(status string) {
					tm.mu.Lock()
					defer tm.mu.Unlock()
					switch status {
					case "Waiting Input":
						task.Status = TaskStatusWaitingInput
					case "Running":
						task.Status = TaskStatusRunning
					default:
						task.Status = TaskStatusRunning
					}
				},
			}

			// Execute
			err := wf.Run(wc, task.Plan.Intent.Prompt)
			if err != nil {
				tm.OutputChan <- fmt.Sprintf("❌ [Workflow] Execution failed: %v", err)
				task.Status = TaskStatusError
			} else {
				tm.OutputChan <- fmt.Sprintf("✅ [Workflow] Execution completed successfully.")
			}
			return // STOP HERE, DO NOT PROCEED TO JSON PLAN EXECUTOR
		}
	}
	// --------------------------------------------

	// Inner loop state
	// In the original main.go, this loop continuously checks plan.Steps
	for {
		select {
		case <-task.Ctx.Done():
			tm.OutputChan <- fmt.Sprintf("[%s] Task cancelled.", task.ID)
			return
		default:
			// Proceed
		}

		// 1. Identify Runnable Steps (Batch)
		var batchIndices []int
		var activeStep *model.Step

		// Helper to check dependency status
		isReady := func(step model.Step) bool {
			if len(step.DependsOn) == 0 {
				return true
			}
			for _, depID := range step.DependsOn {
				found := false
				for _, s := range task.Plan.Steps {
					if s.ID == depID {
						found = true
						if s.Status != "completed" {
							return false
						}
						break
					}
				}
				if !found {
					return false
				}
			}
			return true
		}

		// Collect all runnable steps
		for i := range task.Plan.Steps {
			if task.Plan.Steps[i].Status == "pending" && isReady(task.Plan.Steps[i]) {
				batchIndices = append(batchIndices, i)
			}
		}

		// 2. No work? Wait or Exit?
		if len(batchIndices) == 0 {
			// Check if all steps are completed
			allDone := true
			for _, s := range task.Plan.Steps {
				if s.Status != "completed" {
					allDone = false
					break
				}
			}
			if allDone && len(task.Plan.Steps) > 0 {
				tm.OutputChan <- fmt.Sprintf("[%s] All steps completed.", task.ID)
				return
			}
			// If not all done but no runnable steps, we might be stuck or waiting for external event?
			// For now, assume if 0 runnable and not all done, we are stuck?
			// Actually, if we just updated the plan, we might have new steps.
			// Let's break slightly to avoid CPU spin if actually stuck, but logic should provide update.
			return
		}

		// 3. Process Batch
		// Check for interactive steps
		for _, idx := range batchIndices {
			step := &task.Plan.Steps[idx]
			isReview := step.Action == "content-review" || step.Action == "draft_scenes"
			if step.Action == "ask_questions" || isReview {
				// Stop batching, prioritize this interactive step alone
				batchIndices = []int{idx}
				activeStep = step
				break
			}
		}

		// Parallel Execution for Automated Steps
		if activeStep == nil {
			if len(batchIndices) > 1 {
				tm.OutputChan <- fmt.Sprintf("[%s] Executing %d steps in parallel...", task.ID, len(batchIndices))
			}

			// Execute Batch
			execWG := sync.WaitGroup{}
			for _, idx := range batchIndices {
				execWG.Add(1)
				go func(i int) {
					defer execWG.Done()
					step := &task.Plan.Steps[i]
					tm.OutputChan <- fmt.Sprintf("[%s] Executing Step %d: %s (%s)", task.ID, step.ID, step.Action, step.AgentID)

					// Execute Step Logic
					// Try Executor Dispatcher first
					// We need to capture output, so we need a helper or channel bridge
					// We need to capture output, so we need a helper or channel bridge
					// Capture output to a buffer to avoid interleaving in parallel execution
					var logBuffer []string
					var logMu sync.Mutex

					outputBridge := make(chan string)
					var resultBuilder strings.Builder
					var msgWG sync.WaitGroup

					msgWG.Add(1)
					go func() {
						defer msgWG.Done()
						for msg := range outputBridge {
							// Check if it's a result or a log
							if strings.HasPrefix(msg, "RESULT_") {
								// Result processing remains same
								parts := strings.SplitN(msg, "=", 2)
								if len(parts) == 2 {
									key := strings.TrimPrefix(parts[0], "RESULT_")
									resultBuilder.WriteString(fmt.Sprintf("%s: %s\n", key, parts[1]))
								}
								// Do NOT log functional results to user console to keep clean?
								// Or log them? The user example showed RESULT_VIDEO_FILE...
								// Let's keep logging them but buffered.
								logMu.Lock()
								logBuffer = append(logBuffer, msg)
								logMu.Unlock()
							} else {
								logMu.Lock()
								logBuffer = append(logBuffer, msg)
								logMu.Unlock()
							}
						}
					}()

					// Try matching by AgentID first (e.g. "audio-creator")
					exec, err := tm.dispatcher.GetExecutor(step.AgentID)
					if err != nil {
						exec, err = tm.dispatcher.GetExecutor(step.Action)
					}

					var execErr error
					if err == nil {
						execErr = exec.Execute(task.Ctx, *step, outputBridge)
					} else {
						execErr = tm.executeStep(task.Ctx, step)
					}
					close(outputBridge)
					msgWG.Wait() // Wait for all logs to be processed

					if execErr != nil {
						logMu.Lock()
						logBuffer = append(logBuffer, fmt.Sprintf("[%s] Step %d Failed: %v", task.ID, step.ID, execErr))
						logMu.Unlock()
					}

					// Flush Logs Atomically
					tm.OutputChan <- fmt.Sprintf("--- Step %d: %s (%s) ---", step.ID, step.Action, step.AgentID)
					logMu.Lock()
					for _, line := range logBuffer {
						tm.OutputChan <- line
					}
					logMu.Unlock()
					tm.OutputChan <- fmt.Sprintf("--------------------------------")
					step.Status = "completed"
					if res := resultBuilder.String(); res != "" {
						step.Result = res
					}
				}(idx)
			}
			execWG.Wait()

			_ = tm.planner.Store.SavePlan(*task.Plan)

			// Check for auto-update triggers
			lastIdx := len(task.Plan.Steps) - 1
			finishedLast := false
			for _, idx := range batchIndices {
				if idx == lastIdx {
					finishedLast = true
					break
				}
			}
			if finishedLast {
				tm.OutputChan <- fmt.Sprintf("[%s] Determining next steps...", task.ID)
				updatedPlan, err := tm.planner.UpdatePlan(task.Ctx, task.Plan, "Autoconfirmed: Parallel batch completed.")
				if err == nil {
					task.Plan = updatedPlan
					continue
				} else {
					tm.OutputChan <- fmt.Sprintf("[%s] Error updating plan: %v", task.ID, err)
					return
				}
			}
			continue
		}

		// INTERACTIVE STEP
		// We must pause and ask for input
		task.Status = TaskStatusWaitingInput

		// Send prompt to OutputChan
		if activeStep.Action == "ask_questions" {
			tm.OutputChan <- fmt.Sprintf("[%s] [%s] Input required: %s", task.ID, activeStep.AgentID, activeStep.Action)

			// Format questions
			var assumptions []interface{}
			if as, ok := activeStep.Params["assumptions"]; ok {
				if listAs, isListAs := as.([]interface{}); isListAs {
					assumptions = listAs
				}
			}
			var questions []interface{}
			if qs, ok := activeStep.Params["questions"]; ok {
				if list, isList := qs.([]interface{}); isList {
					questions = list
				} else {
					questions = []interface{}{qs}
				}
			}

			var sb strings.Builder
			for i, q := range questions {
				assumption := ""
				if i < len(assumptions) {
					assumption = fmt.Sprintf("%v", assumptions[i])
				}
				if assumption == "" || strings.EqualFold(assumption, "unknown") {
					sb.WriteString(fmt.Sprintf("  %d. %v\n", i+1, q))
				} else {
					sb.WriteString(fmt.Sprintf("  %d. %v (Default: %s)\n", i+1, q, assumption))
				}
			}
			tm.OutputChan <- sb.String()
			tm.OutputChan <- "Options: [Type answer] | '/accept' (defaults) | '/stop'"

		} else if activeStep.Action == "content-review" || activeStep.Action == "draft_scenes" {
			tm.OutputChan <- fmt.Sprintf("\n[%s] Review content (%s):", task.ID, activeStep.AgentID)
			tm.OutputChan <- formatStepParams(activeStep.Params)
			tm.OutputChan <- "Options: [Type feedback] | '/accept' | '/stop'"
		}

		// WAIT FOR INPUT
		select {
		case <-task.Ctx.Done():
			return
		case answer := <-task.InputChan:
			// Process Answer
			task.Status = TaskStatusRunning
			activeStepIdx := batchIndices[0]

			// Logic duplication from original main.go
			if activeStep.Action == "ask_questions" {
				if answer == "/accept" || answer == "accept" {
					// Use defaults logic... simplified for simplicity here, assuming main loop might handle or we handle here
					// We need to reconstruct defaults.
					// Ideally we refactor defaults logic to helper, but let's do it inlinish
					var assumptions []interface{}
					if as, ok := activeStep.Params["assumptions"]; ok {
						if listAs, isListAs := as.([]interface{}); isListAs {
							assumptions = listAs
						}
					}
					var questions []interface{}
					if qs, ok := activeStep.Params["questions"]; ok {
						if list, isList := qs.([]interface{}); isList {
							questions = list
						} else {
							questions = []interface{}{qs}
						}
					}
					var details strings.Builder
					for i, q := range questions {
						val := "Unknown"
						if i < len(assumptions) {
							val = fmt.Sprintf("%v", assumptions[i])
						}
						details.WriteString(fmt.Sprintf("%v - %v\n", q, val))
					}
					answer = details.String()
				}
			}

			// Apply to plan
			if answer == "/accept" {
				task.Plan.Steps[activeStepIdx].Status = "completed"
				_ = tm.planner.Store.SavePlan(*task.Plan)

				if activeStepIdx == len(task.Plan.Steps)-1 {
					tm.OutputChan <- fmt.Sprintf("[%s] Determining next steps...", task.ID)
					updatedPlan, err := tm.planner.UpdatePlan(task.Ctx, task.Plan, "User accepted content.")
					if err == nil {
						task.Plan = updatedPlan
					}
				}
				continue
			}

			// Standard update
			tm.OutputChan <- fmt.Sprintf("[%s] [Planner] Determining next steps...", task.ID)
			updatedPlan, err := tm.planner.UpdatePlan(task.Ctx, task.Plan, answer)
			if err != nil {
				tm.OutputChan <- fmt.Sprintf("[%s] Error updating: %v", task.ID, err)
			} else {
				task.Plan = updatedPlan
			}
		}
	}
}

// executeStep handles the actual execution logic for a step
func (tm *TaskManager) executeStep(ctx context.Context, step *model.Step) error {
	switch step.AgentID {
	case "scene-creator":
		return tm.executeSceneCreation(ctx, step)
	default:
		// Default behavior for other agents: Just verify/simulate
		// If tools were specified, we'd handle them here.
		// Check for known tool actions in general
		if strings.HasPrefix(step.Action, "generate_") {
			tm.OutputChan <- fmt.Sprintf("[%s] executing generic generation action: %s", step.AgentID, step.Action)
			time.Sleep(1 * time.Second)
		}
		return nil
	}
}

// executeSceneCreation handles logic for the scene-creator agent
func (tm *TaskManager) executeSceneCreation(ctx context.Context, step *model.Step) error {
	// Detect tool usage based on Action or Params
	// The planner should have populated 'action' with something descriptive

	// Delegate to Block Executors
	if tm.dispatcher != nil {
		if exec, err := tm.dispatcher.GetExecutor(step.Action); err == nil {
			return exec.Execute(ctx, *step, tm.OutputChan)
		}
	}

	action := strings.ToLower(step.Action)

	// Legacy handlers for non-refactored actions

	if strings.Contains(action, "image") {
		// Simulate SDXL Image Generation
		tm.OutputChan <- fmt.Sprintf("🖼️ [SDXL] (%s) Generating Image Asset: %v", step.AgentID, step.Params)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(2 * time.Second):
		}
		tm.OutputChan <- fmt.Sprintf("✅ [SDXL] (%s) Image generated: %d_asset.png", step.AgentID, step.ID)
		return nil
	}

	if strings.Contains(action, "speech") || strings.Contains(action, "tts") || strings.Contains(action, "voice") {
		// Simulate TTS
		tm.OutputChan <- fmt.Sprintf("🗣️ [TTS] (%s) Generating Voiceover: %v", step.AgentID, step.Params)
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(1 * time.Second):
		}
		tm.OutputChan <- fmt.Sprintf("✅ [TTS] (%s) Audio generated: %d_voice.mp3", step.AgentID, step.ID)
		return nil
	}

	// Fallback
	tm.OutputChan <- fmt.Sprintf("⚠️ [Scene Creator] Unknown action '%s', skipping execution logic.", action)
	return nil
}

func formatStepParams(params map[string]interface{}) string {
	var sb strings.Builder

	// Specific handler for AV Script (V2)
	// Specific handler for AV Script (V2)
	// Check for 'av_script' OR 'scenes_draft'
	// Check for 'av_script', 'scenes_draft', 'script_outline', or 'scene_outline'
	val, ok := params["av_script"]
	if !ok {
		val, ok = params["scenes_draft"]
	}
	if !ok {
		val, ok = params["script_outline"]
	}
	if !ok {
		val, ok = params["scene_outline"]
	}

	if ok {
		sb.WriteString("🎬 **AV Script Blueprint**\n\n")
		if scenes, ok := val.([]interface{}); ok {
			for i, s := range scenes {
				if scene, ok := s.(map[string]interface{}); ok {
					// Extract fields safely
					audio := fmt.Sprintf("%v", scene["audio_text"])
					visual := fmt.Sprintf("%v", scene["visual_description"])
					if visual == "<nil>" || visual == "Unknown" || visual == "" {
						visual = fmt.Sprintf("%v", scene["visual_prompt"])
					}
					duration := fmt.Sprintf("%v", scene["duration"])
					if duration == "<nil>" || duration == "Unknown" || duration == "" {
						// Fallback to 'duration' if estimated_duration is missing
						if d, ok := scene["estimated_duration"]; ok {
							duration = fmt.Sprintf("%v", d)
						} else {
							duration = "Unknown"
						}
					}
					profile := ""
					if p, ok := scene["voice_profile"]; ok {
						profile = fmt.Sprintf(" [%v]", p)
					}

					idDisplay := fmt.Sprintf("%d", i+1)
					if sid, ok := scene["scene_id"]; ok {
						idDisplay = fmt.Sprintf("%v", sid)
					}

					sb.WriteString(fmt.Sprintf("   🎬 Scene %s [Duration: %s]%s\n", idDisplay, duration, profile))
					sb.WriteString(fmt.Sprintf("       🔈 Audio:  \"%s\"\n", audio))
					sb.WriteString(fmt.Sprintf("       👁️ Visual: \"%s\"\n\n", visual))
				}
			}
			return sb.String()
		} else if str, ok := val.(string); ok {
			sb.WriteString(str)
			return sb.String()
		}
	}

	// Generic Fallback
	for k, v := range params {
		if list, ok := v.([]interface{}); ok {
			sb.WriteString(fmt.Sprintf("%s:\n", k))
			for _, item := range list {
				sb.WriteString(fmt.Sprintf("  - %v\n", item))
			}
		} else {
			sb.WriteString(fmt.Sprintf("%s: %v\n", k, v))
		}
	}
	return sb.String()
}
