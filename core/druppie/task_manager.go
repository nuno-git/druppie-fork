package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/config"
	"github.com/sjhoeksma/druppie/core/internal/executor"
	"github.com/sjhoeksma/druppie/core/internal/iam"
	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/planner"
	"github.com/sjhoeksma/druppie/core/internal/workflows"
	"gopkg.in/yaml.v2"
)

// TaskStatus definition
type TaskStatus string

const (
	TaskStatusPending      TaskStatus = "Pending"
	TaskStatusRunning      TaskStatus = "Running"
	TaskStatusWaitingInput TaskStatus = "Waiting Input"
	TaskStatusCompleted    TaskStatus = "Completed"
	TaskStatusCancelled    TaskStatus = "Cancelled"
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
	MCPManager      *mcp.Manager
}

type Task struct {
	ID        string
	Plan      *model.ExecutionPlan
	Status    TaskStatus
	InputChan chan string // Channel to receive user input (answers)
	Ctx       context.Context
	Cancel    context.CancelFunc
}

func NewTaskManager(p *planner.Planner, mcpMgr *mcp.Manager, buildEngine builder.BuildEngine) *TaskManager {

	tm := &TaskManager{
		tasks:           make(map[string]*Task),
		planner:         p,
		OutputChan:      make(chan string, 100),
		TaskDoneChan:    make(chan string, 10),
		dispatcher:      executor.NewDispatcher(buildEngine, mcpMgr),
		workflowManager: workflows.NewManager(),
		MCPManager:      mcpMgr,
	}
	// TODO: Load persistent MCP servers from config or disk here?

	return tm
}

// StartTask creates a background task for a given plan and starts the execution loop
func (tm *TaskManager) StartTask(ctx context.Context, plan model.ExecutionPlan) *Task {
	tm.mu.Lock()
	defer tm.mu.Unlock()

	// Provision Plan-Specific MCP Server if template exists
	if tm.MCPManager != nil {
		if err := tm.MCPManager.EnsurePlanServer(ctx, plan.ID); err != nil {
			fmt.Printf("[TaskManager] Warning: Failed to ensure plan server: %v\n", err)
		}
	}

	ctx, cancel := context.WithCancel(ctx)
	task := &Task{
		ID:        plan.ID,
		Plan:      &plan,
		Status:    TaskStatusPending,
		InputChan: make(chan string, 100), // Buffered to allow "type-ahead" or resume-with-input
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
		t.Status = TaskStatusCancelled // Mark as cancelled (user action)
		t.Cancel()
		delete(tm.tasks, id)
		tm.OutputChan <- fmt.Sprintf("[Task Manager] Cancelled task %s (User Stop)", id)
	}
}

// FinishTask stops the task but marks it as successfully completed (User request)
func (tm *TaskManager) FinishTask(id string) {
	tm.mu.Lock()
	defer tm.mu.Unlock()
	if t, ok := tm.tasks[id]; ok {
		t.Status = TaskStatusCompleted // Mark as completed BEFORE cancelling
		t.Cancel()
		delete(tm.tasks, id)
		tm.OutputChan <- fmt.Sprintf("[Task Manager] Finished task %s (User Requested)", id)
	}
}

// runTaskLoop is the background worker for a single plan
func (tm *TaskManager) runTaskLoop(task *Task) {
	defer func() {
		// Cleanup - set to completed only if not already in terminal state
		if task.Status != TaskStatusError && task.Status != TaskStatusCompleted {
			task.Status = TaskStatusCompleted
		}
		tm.TaskDoneChan <- task.ID
		// Remove from active tasks map
		tm.mu.Lock()
		delete(tm.tasks, task.ID)
		tm.mu.Unlock()
	}()

	task.Status = TaskStatusRunning

	// Resurrect 'cancelled', 'skipped', or 'failed' steps to allow resume.
	tm.mu.Lock()
	if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
		modified := false
		for i := range p.Steps {
			s := &p.Steps[i]
			// Check for states that indicate a stopped/interrupted execution
			if s.Status == "cancelled" || s.Status == "skipped" || s.Status == "stopped" || s.Status == "failed" || s.Status == "waiting_input" {
				tm.OutputChan <- fmt.Sprintf("[%s] 🔄 Resuming step %d (%s) - Reset status to pending.", task.ID, s.ID, s.Action)
				s.Status = "pending"
				s.Result = "" // Clear previous interruptions (but maybe we lose history? acceptable for resume)
				s.Error = ""
				modified = true
			}
		}
		if modified {
			_ = tm.planner.Store.SavePlan(p)
			task.Plan = &p // Update local reference to fresh plan
		}
	}
	tm.mu.Unlock()

	// --- INTERCEPTION: NATIVE WORKFLOW ENGINE ---
	if len(task.Plan.SelectedAgents) > 0 {
		agentID := task.Plan.SelectedAgents[0]
		if wf, ok := tm.workflowManager.GetWorkflow(agentID); ok {
			tm.OutputChan <- fmt.Sprintf("[%s] 🚀 Switching to Native Workflow Engine for agent: %s", task.ID, agentID)

			// Clear conflicting Pending steps to allow Workflow to build the plan definitively
			tm.mu.Lock()
			if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
				// We keep completed steps (history) but remove anything else (pending) to avoid duplicates with workflow logic
				// Actually, Native Workflow should OWN the step list.
				// If we have "pending" steps (generated by generic planner), they are likely wrong or redundant.
				// Let's filter out pending steps.
				newSteps := []model.Step{}
				for _, s := range p.Steps {
					if s.Status == "completed" || s.Status == "success" {
						newSteps = append(newSteps, s)
					}
				}
				if len(newSteps) != len(p.Steps) {
					p.Steps = newSteps
					_ = tm.planner.Store.SavePlan(p)
					task.Plan = &p
				}
			}
			tm.mu.Unlock()

			// Create a proxy channel to ensure all workflow logs are prefixed with Plan ID
			// This allows the server log drainer to route them to the correct log file
			proxyLogChan := make(chan string, 50)
			proxyDone := make(chan struct{})
			go func() {
				defer close(proxyDone)
				for msg := range proxyLogChan {
					// Add prefix if not already present
					if !strings.Contains(msg, "["+task.ID+"]") {
						tm.OutputChan <- fmt.Sprintf("[%s] %s", task.ID, msg)
					} else {
						tm.OutputChan <- msg
					}
				}
			}()

			// Build Context
			wc := &workflows.WorkflowContext{
				Ctx:        task.Ctx,
				LLM:        tm.planner.GetLLM(),
				Dispatcher: tm.dispatcher,
				Store:      tm.planner.Store,
				PlanID:     task.ID,
				GetAgent: func(id string) (model.AgentDefinition, error) {
					return tm.planner.Registry.GetAgent(id)
				},
				OutputChan: proxyLogChan,
				InputChan:  task.InputChan,
				UpdateStatus: func(status string) {
					tm.mu.Lock()
					defer tm.mu.Unlock()

					// Don't update if task is already completed or stopped
					if task.Status == TaskStatusCompleted || task.Status == TaskStatusError {
						return
					}

					var planStatus string
					switch status {
					case "Waiting Input":
						task.Status = TaskStatusWaitingInput
						planStatus = "waiting_input"
					case "Running":
						task.Status = TaskStatusRunning
						planStatus = "running"
					case "Completed":
						task.Status = TaskStatusCompleted
						planStatus = "completed"
					case "Stopped", "Error":
						task.Status = TaskStatusError
						planStatus = "stopped"
					default:
						// Don't blindly set to running for unknown statuses
						return
					}
					// Update plan status in store
					if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
						p.Status = planStatus
						_ = tm.planner.Store.SavePlan(p)
					}
				},
				AppendStep: func(s model.Step) int {
					tm.mu.Lock()
					defer tm.mu.Unlock()

					storedPlan, err := tm.planner.Store.GetPlan(task.ID)
					if err != nil {
						tm.OutputChan <- fmt.Sprintf("[%s] ⚠️ [TaskManager] Failed to sync plan update: %v", task.ID, err)
						return 0
					}

					// Auto-increment ID if not set
					if s.ID == 0 {
						s.ID = len(storedPlan.Steps) + 1
					}
					if s.Status == "" {
						s.Status = "completed"
					}

					// Check if step with this ID already exists - UPDATE instead of APPEND
					found := false
					for i, existing := range storedPlan.Steps {
						if existing.ID == s.ID {
							storedPlan.Steps[i] = s
							found = true
							break
						}
					}
					if !found {
						storedPlan.Steps = append(storedPlan.Steps, s)
					}

					if err := tm.planner.Store.SavePlan(storedPlan); err != nil {
						tm.OutputChan <- fmt.Sprintf("[%s] ⚠️ [TaskManager] Failed to save plan update: %v", task.ID, err)
					}

					task.Plan = &storedPlan
					return s.ID
				},
				FindCompletedStep: func(action string, paramKey string, paramValue interface{}) *model.Step {
					tm.mu.Lock()
					defer tm.mu.Unlock()

					// Always refresh from store to be safe
					p, err := tm.planner.Store.GetPlan(task.ID)
					if err != nil {
						return nil
					}

					for i := range p.Steps {
						s := &p.Steps[i]
						if s.Status == "completed" && s.Action == action {
							// Check params match
							if paramKey != "" {
								if val, ok := s.Params[paramKey]; ok {
									// Simple equality check (convert to string for safety)
									if fmt.Sprintf("%v", val) == fmt.Sprintf("%v", paramValue) {
										return s
									}
								}
							} else {
								// No param check required
								return s
							}
						}
					}
					return nil
				},
			}

			// Execute
			err := wf.Run(wc, task.Plan.Intent.Prompt)
			close(proxyLogChan)
			<-proxyDone

			if err != nil {
				tm.OutputChan <- fmt.Sprintf("[%s] ❌ [Workflow] Execution failed: %v", task.ID, err)
				task.Status = TaskStatusError

				// Update plan status to stopped
				tm.mu.Lock()
				storedPlan, getErr := tm.planner.Store.GetPlan(task.ID)
				if getErr == nil {
					storedPlan.Status = "stopped"
					// Reset active steps to pending so they can be retried on resume
					for i := range storedPlan.Steps {
						if storedPlan.Steps[i].Status == "running" || storedPlan.Steps[i].Status == "waiting_input" {
							storedPlan.Steps[i].Status = "pending"
						}
					}
					_ = tm.planner.Store.SavePlan(storedPlan)
				}
				tm.mu.Unlock()
			} else {
				tm.OutputChan <- fmt.Sprintf("[%s] ✅ [Workflow] Execution completed successfully.", task.ID)

				// Update task status
				task.Status = TaskStatusCompleted

				// Finalize Plan JSON status
				tm.mu.Lock()
				storedPlan, err := tm.planner.Store.GetPlan(task.ID)
				if err == nil {
					storedPlan.Status = "completed"
					_ = tm.planner.Store.SavePlan(storedPlan)
				}
				tm.mu.Unlock()
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
			// Check if it was manually cancelled/completed
			if task.Status == TaskStatusCompleted || task.Status == TaskStatusCancelled {
				statusStr := "completed"
				if task.Status == TaskStatusCancelled {
					statusStr = "cancelled"
				}
				tm.OutputChan <- fmt.Sprintf("[%s] Task %s by user request.", task.ID, statusStr)

				tm.mu.Lock()
				if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
					p.Status = statusStr
					// Mark active/pending steps as cancelled/completed
					for i := range p.Steps {
						s := &p.Steps[i]
						switch s.Status {
						case "running", "waiting_input":
							s.Status = "cancelled"
							s.Result = "Cancelled by user"
						case "pending":
							s.Status = "skipped"
							s.Result = "Skipped due to cancellation"
						}
					}
					_ = tm.planner.Store.SavePlan(p)
				}
				tm.mu.Unlock()
				return
			}

			tm.OutputChan <- fmt.Sprintf("[%s] Task cancelled.", task.ID)
			task.Status = TaskStatusError

			tm.mu.Lock()
			if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
				p.Status = "stopped"
				// Reset active steps to pending
				for i := range p.Steps {
					if p.Steps[i].Status == "running" || p.Steps[i].Status == "waiting_input" {
						p.Steps[i].Status = "pending"
					}
				}
				_ = tm.planner.Store.SavePlan(p)
			}
			tm.mu.Unlock()
			return
		default:
			// Proceed
		}

		// 1. Identify Runnable Steps (Batch)
		var batchIndices []int
		var activeStep *model.Step

		// 0. Priority: Check for steps already waiting for input (e.g. failed steps or resumed state)
		for i := range task.Plan.Steps {
			if task.Plan.Steps[i].Status == "waiting_input" {
				activeStep = &task.Plan.Steps[i]
				break
			}
		}

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
		if len(batchIndices) == 0 && activeStep == nil {
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

				// Update task status
				task.Status = TaskStatusCompleted

				// Finalize Plan JSON status
				tm.mu.Lock()
				storedPlan, err := tm.planner.Store.GetPlan(task.ID)
				if err == nil {
					storedPlan.Status = "completed"
					_ = tm.planner.Store.SavePlan(storedPlan)
				}
				tm.mu.Unlock()

				return
			}

			// If not all done but no runnable steps, we are STUCK.
			tm.OutputChan <- fmt.Sprintf("[%s] Plan stuck: Unfinished steps but none runnable. Stopping.", task.ID)
			task.Status = TaskStatusError

			tm.mu.Lock()
			if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
				p.Status = "stopped"
				_ = tm.planner.Store.SavePlan(p)
			}
			tm.mu.Unlock()
			return
		}

		// 3. Process Batch
		// Check for interactive steps
		for _, idx := range batchIndices {
			step := &task.Plan.Steps[idx]
			isReview := step.Action == "content-review" || step.Action == "draft_scenes" || step.Action == "audit_request"
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

					// Update Status to Running & Persist
					tm.mu.Lock()
					if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
						// Find and update step in persistent copy
						for k := range p.Steps {
							if p.Steps[k].ID == step.ID {
								p.Steps[k].Status = "running"
								break
							}
						}
						_ = tm.planner.Store.SavePlan(p)
					}
					step.Status = "running" // Update local copy
					tm.mu.Unlock()

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
									if key == "CONSOLE_OUTPUT" {
										resultBuilder.WriteString(parts[1] + "\n")
									} else {
										resultBuilder.WriteString(fmt.Sprintf("%s: %s\n", key, parts[1]))
									}
								}
								// Do NOT log result lines to console/logBuffer.
								// They are internal protocol for result passing.
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
						// Inject context info for executors (like file reader)
						if step.Params == nil {
							step.Params = make(map[string]interface{})
						}
						step.Params["plan_id"] = task.ID

						// Parameter Variable Substitution
						// Resolve ${VAR} using results from previous steps
						// 1. Collect results map
						resultsMap := make(map[string]string)
						tm.mu.Lock()
						currentP, _ := tm.planner.Store.GetPlan(task.ID)
						tm.mu.Unlock()

						for _, prevStep := range currentP.Steps {
							if prevStep.ID < step.ID && prevStep.Status == "completed" {
								// Parse result string (Key: Value\nKey:Value)
								lines := strings.Split(prevStep.Result, "\n")
								for _, line := range lines {
									parts := strings.SplitN(line, ":", 2)
									if len(parts) == 2 {
										k := strings.TrimSpace(parts[0])
										v := strings.TrimSpace(parts[1])
										resultsMap[k] = v
									}
								}
							}
						}

						// Inject Context Variables
						resultsMap["PLAN_ID"] = task.ID

						// Replace in Params
						for k, v := range step.Params {
							if strVal, ok := v.(string); ok && strings.Contains(strVal, "${") {
								for rk, rv := range resultsMap {
									placeholder := "${" + rk + "}"
									if strings.Contains(strVal, placeholder) {
										strVal = strings.ReplaceAll(strVal, placeholder, rv)
									}
								}
								step.Params[k] = strVal
							}
						}
						// Retry / Healing Loop
						maxRetries := 0
						if cfgBytes, err := tm.planner.Store.LoadConfig(); err == nil {
							var cfg config.Config
							if yaml.Unmarshal(cfgBytes, &cfg) == nil && cfg.LLM.Retries > 0 {
								maxRetries = cfg.LLM.Retries
							}
						}

						for attempt := 0; attempt <= maxRetries; attempt++ {
							execErr = exec.Execute(task.Ctx, *step, outputBridge)

							if execErr == nil {
								break
							}

							// Self-Healing Logic for create_code
							if attempt < maxRetries && step.Action == "create_code" {
								logMu.Lock()
								logBuffer = append(logBuffer, fmt.Sprintf("⚠️ Step failed: %v. Attempting Self-Healing (%d/%d)...", execErr, attempt+1, maxRetries))
								logMu.Unlock()

								fixPrompt := fmt.Sprintf(`
The execution of 'create_code' failed.
Error: %v
Current Params: %v

Please FIX the parameters to satisfy the error requirements (e.g. provide missing 'files' map).
Return ONLY a valid JSON object representing the FIXED 'params' object.
Do NOT return YAML or Markdown blocks.
`, execErr, step.Params)

								fixedJSON, err := tm.planner.GetLLM().Generate(task.Ctx, fixPrompt, "You are a JSON repair agent. Output raw JSON only.")
								if err != nil {
									continue
								}

								// Clean JSON
								fixedJSON = strings.TrimSpace(fixedJSON)
								fixedJSON = strings.TrimPrefix(fixedJSON, "```json")
								fixedJSON = strings.TrimPrefix(fixedJSON, "```")
								fixedJSON = strings.TrimSuffix(fixedJSON, "```")

								var newParams map[string]interface{}
								if err := json.Unmarshal([]byte(fixedJSON), &newParams); err == nil {
									step.Params = newParams
									step.Params["plan_id"] = task.ID // Ensure ID persists
									logMu.Lock()
									logBuffer = append(logBuffer, "✅ Parameters self-healed. Retrying...")
									logMu.Unlock()
								}
							} else {
								break
							}
						}
					} else {
						execErr = tm.executeStep(task.Ctx, step, task.ID, outputBridge)
					}
					close(outputBridge)
					msgWG.Wait() // Wait for all logs to be processed

					if execErr != nil {
						logMu.Lock()
						logBuffer = append(logBuffer, fmt.Sprintf("[%s] Step %d Failed: %v", task.ID, step.ID, execErr))
						logMu.Unlock()
					}

					// Flush Logs Atomically
					logMu.Lock()
					for _, line := range logBuffer {
						tm.OutputChan <- line
					}
					logMu.Unlock()

					if execErr != nil {
						// FAILURE HANDLING: Set to Waiting Input
						step.Status = "waiting_input"
						step.Error = execErr.Error()
						step.Result = fmt.Sprintf("Error: %v", execErr)
						tm.OutputChan <- fmt.Sprintf("[%s] Step %d paused on error. Waiting for user input...", task.ID, step.ID)
					} else {
						step.Status = "completed"
						if res := resultBuilder.String(); res != "" {
							step.Result = res
						}
					}
				}(idx)
			}
			execWG.Wait()

			_ = tm.planner.Store.SavePlan(*task.Plan)

			// Check for auto-update triggers
			lastIdx := len(task.Plan.Steps) - 1
			finishedLast := false
			failedAny := false

			for _, idx := range batchIndices {
				if task.Plan.Steps[idx].Status == "waiting_input" {
					failedAny = true
				}
				if idx == lastIdx && task.Plan.Steps[idx].Status == "completed" {
					finishedLast = true
				}
			}

			if failedAny {
				// Loop again to handle waiting input
				continue
			}
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
		// Check for Auto-Approval for "audit_request"
		if activeStep.Action == "audit_request" || activeStep.Action == "audit-request" {
			// Extract parameters
			justification, _ := activeStep.Params["justification"].(string)
			stakeholders, _ := activeStep.Params["stakeholders"].([]interface{})

			// Justification Fallback
			if justification == "" {
				if r, ok := activeStep.Params["reason"].(string); ok {
					justification = r
				} else if viol, ok := activeStep.Params["violation"].(string); ok {
					justification = fmt.Sprintf("VIOLATION DETECTED: %s", viol)
				} else if intent, ok := activeStep.Params["intent"].(string); ok {
					justification = fmt.Sprintf("Review required for: %s", intent)
				} else {
					// Try Dependency Results
					for _, depID := range activeStep.DependsOn {
						for _, s := range task.Plan.Steps {
							if s.ID == depID && strings.Contains(s.Result, "[VIOLATION]") {
								justification = fmt.Sprintf("Audit Triggered by: %s", strings.TrimSpace(s.Result))
								break
							}
						}
						if justification != "" {
							break
						}
					}
					if justification == "" {
						justification = "Manual review required by compliance policy."
					}
				}
			}

			// Load Real Config for Groups (Unconditional)
			var cfg config.Config
			if cfgBytes, err := tm.planner.Store.LoadConfig(); err == nil {
				_ = yaml.Unmarshal(cfgBytes, &cfg)
			}

			// Stakeholders Fallback logic using Config
			var requiredGroups []string
			if len(stakeholders) > 0 {
				for _, s := range stakeholders {
					val := fmt.Sprintf("%v", s)
					// Resolve key against config map (e.g. "security" -> ["ciso", ...])
					if expanded, ok := cfg.ApprovalGroups[strings.ToLower(val)]; ok {
						requiredGroups = append(requiredGroups, expanded...)
					} else {
						requiredGroups = append(requiredGroups, val)
					}
				}
			} else {
				// Fallback Logic with Config Map
				lowerJust := strings.ToLower(justification)
				var groupKey string

				if strings.Contains(lowerJust, "security") || strings.Contains(lowerJust, "access") || strings.Contains(lowerJust, "residency") {
					groupKey = "security"
				} else if strings.Contains(lowerJust, "legal") {
					groupKey = "legal"
				} else {
					groupKey = "compliance" // Default assumption
				}

				// Look up in config, fallback to defaults if missing in config
				if groups, ok := cfg.ApprovalGroups[groupKey]; ok && len(groups) > 0 {
					requiredGroups = groups
				} else {
					// Hard defaults if config is empty for that key
					switch groupKey {
					case "security":
						requiredGroups = []string{"ciso", "security-admin"}
					case "legal":
						requiredGroups = []string{"legal-counsel"}
					default:
						requiredGroups = []string{"Compliance-Admin"}
					}
				}
			}

			// Validate: Update params so downstream logs see the resolved groups
			resolvedInterface := make([]interface{}, len(requiredGroups))
			for i, v := range requiredGroups {
				resolvedInterface[i] = v
			}
			activeStep.Params["stakeholders"] = resolvedInterface

			// Only verify auto-approval if running in CLI Auto-Pilot mode
			mode, _ := task.Ctx.Value("mode").(string)
			if mode == "cli-autopilot" {
				// Check User Permissions
				if user, ok := iam.GetUserFromContext(task.Ctx); ok {
					authorized := false
					for _, g := range user.Groups {
						for _, req := range requiredGroups {
							if strings.EqualFold(g, req) || g == "admin" || g == "group-admin" { // admin override
								authorized = true
								break
							}
						}
						if authorized {
							break
						}
					}

					if authorized {
						// PRINT AUDIT DETALS FOR VISIBILITY
						tm.OutputChan <- fmt.Sprintf("\n[%s] 🛡️ COMPLIANCE AUDIT REQUIRED", task.ID)
						tm.OutputChan <- fmt.Sprintf("Justification: %s", justification)
						approversJSON, _ := json.Marshal(requiredGroups)
						tm.OutputChan <- fmt.Sprintf("Approvers: %s", string(approversJSON))
						tm.OutputChan <- "Options: '/approve' | '/reject'"

						tm.OutputChan <- fmt.Sprintf("[%s] ⚡️ Auto-Approving Audit Step (User '%s' authorized for %v)", task.ID, user.Username, requiredGroups)

						// Mark Completed
						activeStep.Status = "completed"
						activeStep.Result = fmt.Sprintf("Auto-Approved by %s (Groups: %v)", user.Username, user.Groups)

						// Update params to reflect auto-resolution if needed
						// Persist
						tm.mu.Lock()
						if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
							// Update step in persistent plan
							for i := range p.Steps {
								if p.Steps[i].ID == activeStep.ID {
									p.Steps[i] = *activeStep
									break
								}
							}
							_ = tm.planner.Store.SavePlan(p)
						}
						tm.mu.Unlock()

						// Continue Loop (Skip Waiting Input)
						continue
					} else {
						tm.OutputChan <- fmt.Sprintf("[%s] 🔒 Auto-Approval Failed: User '%s' groups %v do not match required %v", task.ID, user.Username, user.Groups, requiredGroups)
					}
				}
			}
		}

		// Check for Auto-Accept for "ask_questions"
		if activeStep.Action == "ask_questions" || activeStep.Action == "ask-questions" {
			mode, _ := task.Ctx.Value("mode").(string)
			if mode == "cli-autopilot" {
				tm.OutputChan <- fmt.Sprintf("[%s] ⚡️ Auto-Accepting Questions with Defaults in Auto-Pilot Mode", task.ID)

				// Reconstruct defaults
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
				details.WriteString("Auto-Accepted Defaults:\n")
				for i, q := range questions {
					assumption := "Unknown"
					if i < len(assumptions) {
						assumption = fmt.Sprintf("%v", assumptions[i])
					}
					details.WriteString(fmt.Sprintf("%d. %v -> %s\n", i+1, q, assumption))
				}

				activeStep.Status = "completed"
				activeStep.Result = details.String()

				// Persist
				tm.mu.Lock()
				if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
					for i := range p.Steps {
						if p.Steps[i].ID == activeStep.ID {
							p.Steps[i] = *activeStep
							break
						}
					}
					_ = tm.planner.Store.SavePlan(p)
				}
				tm.mu.Unlock()
				continue
			}
		}

		// We must pause and ask for input
		task.Status = TaskStatusWaitingInput

		tm.mu.Lock()
		if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
			p.Status = "waiting_input"
			// Update active step status
			for i := range p.Steps {
				if p.Steps[i].ID == activeStep.ID {
					p.Steps[i].Status = "waiting_input"
					if activeStep.Result != "" {
						p.Steps[i].Result = activeStep.Result // Persist error message if any
					}
					break
				}
			}
			_ = tm.planner.Store.SavePlan(p)
			// Update local plan pointer
			task.Plan.Status = "waiting_input"
			activeStep.Status = "waiting_input"
		}
		tm.mu.Unlock()

		// Send prompt to OutputChan
		switch activeStep.Action {
		case "ask_questions", "ask-questions":
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

		case "content-review", "draft_scenes", "content_review", "draft-scenes":
			tm.OutputChan <- fmt.Sprintf("\n[%s] Review content (%s):", task.ID, activeStep.AgentID)
			tm.OutputChan <- formatStepParams(activeStep.Params)
			tm.OutputChan <- "Options: [Type feedback] | '/accept' | '/stop'"

		case "audit_request", "audit-request":
			justification, _ := activeStep.Params["justification"].(string)
			stakeholders, _ := activeStep.Params["stakeholders"].([]interface{})

			// 1. Justification Fallback
			if justification == "" {
				if r, ok := activeStep.Params["reason"].(string); ok {
					justification = r
				} else if viol, ok := activeStep.Params["violation"].(string); ok {
					justification = fmt.Sprintf("VIOLATION DETECTED: %s", viol)
				} else if intent, ok := activeStep.Params["intent"].(string); ok {
					justification = fmt.Sprintf("Review required for: %s", intent)
				} else {
					// Try Dependency Results
					for _, depID := range activeStep.DependsOn {
						for _, s := range task.Plan.Steps {
							if s.ID == depID && strings.Contains(s.Result, "[VIOLATION]") {
								justification = fmt.Sprintf("Audit Triggered by: %s", strings.TrimSpace(s.Result))
								break
							}
						}
						if justification != "" {
							break
						}
					}
					if justification == "" {
						justification = "Manual review required by compliance policy."
					}
				}
			}

			// 2. Stakeholders Fallback (Infer from Config/Context)
			if len(stakeholders) == 0 {
				// Simple heuristic mapping based on keywords in justification/violation to typical groups
				lowerJust := strings.ToLower(justification)
				if strings.Contains(lowerJust, "security") || strings.Contains(lowerJust, "access") || strings.Contains(lowerJust, "residency") {
					// Assume CISO/Security
					stakeholders = []interface{}{"ciso", "group-admin"}
				} else if strings.Contains(lowerJust, "legal") || strings.Contains(lowerJust, "contract") {
					stakeholders = []interface{}{"legal", "group-admin"}
				} else {
					stakeholders = []interface{}{"compliance", "group-admin"}
				}
			}

			tm.OutputChan <- fmt.Sprintf("\n[%s] 🛡️ COMPLIANCE AUDIT REQUIRED", task.ID)
			tm.OutputChan <- fmt.Sprintf("Justification: %s", justification)

			approversJSON, _ := json.Marshal(stakeholders)
			tm.OutputChan <- fmt.Sprintf("Approvers: %s", string(approversJSON))

			tm.OutputChan <- "Options: '/approve' | '/reject'"

		default:
			// Generic or Error Handling
			tm.OutputChan <- fmt.Sprintf("[%s] Step %d Paused/Failed: %s", task.ID, activeStep.ID, activeStep.Action)
			if activeStep.Result != "" {
				tm.OutputChan <- fmt.Sprintf("Message: %s", activeStep.Result)
			}
			tm.OutputChan <- "Options: [Type specific instruction] | '/retry' | '/stop'"
		}

		// WAIT FOR INPUT
		select {
		case <-task.Ctx.Done():
			return
		case answer := <-task.InputChan:
			// Process Answer
			task.Status = TaskStatusRunning

			tm.mu.Lock()
			if p, err := tm.planner.Store.GetPlan(task.ID); err == nil {
				p.Status = "running"
				_ = tm.planner.Store.SavePlan(p)
				task.Plan.Status = "running"
				tm.OutputChan <- fmt.Sprintf("[%s] Status updated to RUNNING (Input received)", task.ID)
			}
			tm.mu.Unlock()
			// 1. Identify which step to apply input to
			activeStepIdx := -1
			// Find index of activeStep in our local plan copy
			for i := range task.Plan.Steps {
				if &task.Plan.Steps[i] == activeStep {
					activeStepIdx = i
					break
				}
			}

			if activeStepIdx == -1 && len(batchIndices) > 0 {
				activeStepIdx = batchIndices[0]
			}

			if activeStepIdx == -1 {
				tm.OutputChan <- fmt.Sprintf("[%s] Error: No active step to apply input to. Resetting state...", task.ID)
				// If we are getting here repeatedly with "defaults", we are in an infinite loop.
				// Stop the task.
				task.Status = TaskStatusError
				return
			}

			// Logic duplication from original main.go
			// Apply to plan
			isAccept := answer == "/accept" || answer == "accept"

			if activeStep.Action == "ask_questions" && isAccept {
				// Reconstruct defaults from assumptions
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
					val := "Accepted Default"
					if i < len(assumptions) {
						val = fmt.Sprintf("%v", assumptions[i])
					}
					details.WriteString(fmt.Sprintf("%v: %v\n", q, val))
				}
				answer = details.String()
			}

			if isAccept {
				task.Plan.Steps[activeStepIdx].Status = "completed"
				task.Plan.Steps[activeStepIdx].Result = answer
				_ = tm.planner.Store.SavePlan(*task.Plan)

				if activeStepIdx == len(task.Plan.Steps)-1 {
					tm.OutputChan <- fmt.Sprintf("[%s] Determining next steps...", task.ID)
					// Use the actual answer (details) instead of a hardcoded string
					updatedPlan, err := tm.planner.UpdatePlan(task.Ctx, task.Plan, answer)
					if err == nil {
						task.Plan = updatedPlan
					}
				}
				continue
			}

			// Feedback / Rejection
			// If this was a review step, mark it as rejected so it's hidden from Kanban
			// and cleaner in history.
			if activeStep.Action == "content-review" || activeStep.Action == "draft_scenes" || strings.Contains(strings.ToLower(activeStep.Action), "review") {
				task.Plan.Steps[activeStepIdx].Status = "rejected"
				task.Plan.Steps[activeStepIdx].Result = fmt.Sprintf("Rejected by user: %s", answer)
				_ = tm.planner.Store.SavePlan(*task.Plan)
			}

			// Standard update

			// Detect if we are in a failed state and user wants to retry
			isFailedStep := activeStep.Status == "waiting_input" && activeStep.Error != ""
			if isFailedStep {
				lowerAnswer := strings.ToLower(answer)
				if strings.Contains(lowerAnswer, "retry") || strings.Contains(lowerAnswer, "fix") {
					task.Plan.Steps[activeStepIdx].Status = "pending"
					task.Plan.Steps[activeStepIdx].Error = ""
					// Append hint to params? For now just retry.
					tm.OutputChan <- fmt.Sprintf("[%s] Resetting step %d to PENDING via User Action.", task.ID, activeStep.ID)
					_ = tm.planner.Store.SavePlan(*task.Plan)

					// If "fix", we might want to try to use the input as params?
					// But relying on "UpdatePlan" for a single step retry is hard.
					// We will assume the user fixed the environment or config and wants a plain retry.
					continue
				}
			}

			tm.OutputChan <- fmt.Sprintf("[%s] [Planner] Processing feedback/input...", task.ID)
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
// executeStep handles the actual execution logic for a step
// executeStep handles the actual execution logic for a step
func (tm *TaskManager) executeStep(ctx context.Context, step *model.Step, planID string, outputChan chan<- string) error {
	if step.Params == nil {
		step.Params = make(map[string]interface{})
	}
	// Inject Plan ID for context-aware executors (e.g. MCP path resolution)
	step.Params["plan_id"] = planID

	action := step.Action

	// 1. Try Dispatcher directly
	if tm.dispatcher != nil {
		if exec, err := tm.dispatcher.GetExecutor(action); err == nil {
			return exec.Execute(ctx, *step, outputChan)
		}
	}

	// 2. Handle "tool_usage" wrapper pattern (used by mcp-agent)
	if action == "tool_usage" {
		if toolName, ok := step.Params["tool_name"].(string); ok {
			outputChan <- fmt.Sprintf("🔧 Unwrapping tool_usage: %s", toolName)
			// Try finding executor for the specific tool name
			if tm.dispatcher != nil {
				if exec, err := tm.dispatcher.GetExecutor(toolName); err == nil {
					// Create a proxy step with the specific action
					proxyStep := *step
					proxyStep.Action = toolName

					// Flatten "parameters" if present (common in tool_usage schema)
					if innerParams, ok := step.Params["parameters"].(map[string]interface{}); ok {
						for k, v := range innerParams {
							proxyStep.Params[k] = v
						}
					}
					// Also support "params" key just in case
					if innerParams, ok := step.Params["params"].(map[string]interface{}); ok {
						for k, v := range innerParams {
							proxyStep.Params[k] = v
						}
					}

					return exec.Execute(ctx, proxyStep, outputChan)
				}
			}
			return fmt.Errorf("no executor found for tool: %s", toolName)
		}
		return fmt.Errorf("tool_usage action requires 'tool_name' parameter")
	}

	// 3. Agent-specific Legacy Handling
	switch step.AgentID {
	case "scene-creator":
		return tm.executeSceneCreation(ctx, step)
	default:
		// Default: Check for known prefix
		if strings.HasPrefix(step.Action, "generate_") {
			tm.OutputChan <- fmt.Sprintf("[%s] executing generic generation action: %s", step.AgentID, step.Action)
			time.Sleep(1 * time.Second)
			return nil
		}
		// If explicit "tool_usage" failed above, or unknown action:
		return fmt.Errorf("unknown action '%s' for agent '%s' (no executor found)", step.Action, step.AgentID)
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
