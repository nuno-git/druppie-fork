package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/config"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/planner"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/router"
	"github.com/sjhoeksma/druppie/core/internal/store"
	"github.com/spf13/cobra"
)

func main() {
	var rootCmd = &cobra.Command{
		Use:   "druppie-core",
		Short: "Druppie Core Helper CLI & API Server",
		Long: `Druppie Core manages the Registry, Planner, and Orchestration API. 
By default, it starts the API Server on port 8080. 
Use global flags like --plan-id to resume existing planning tasks or --llm-provider to switch backends.`,
	}

	// CLI Flags
	var llmProviderOverride string
	var buildProviderOverride string
	var debug bool
	var planID string

	// Helper to find project root
	findProjectRoot := func() (string, error) {
		cwd, err := os.Getwd()
		if err != nil {
			return "", err
		}

		// Traverse up until we find .druppie or blocks
		for {
			if _, err := os.Stat(filepath.Join(cwd, ".druppie")); err == nil {
				return cwd, nil
			}
			if _, err := os.Stat(filepath.Join(cwd, "blocks")); err == nil {
				return cwd, nil
			}

			parent := filepath.Dir(cwd)
			if parent == cwd {
				// Reached root without finding
				return "", fmt.Errorf("project root not found (missing .druppie or blocks)")
			}
			cwd = parent
		}
	}

	// Helper to bootstrap dependencies
	// Returns ConfigManager to allow updates, and Builder Engine
	setup := func(_ *cobra.Command) (*config.Manager, *registry.Registry, *router.Router, *planner.Planner, builder.BuildEngine, error) {
		// Check if we are in 'core' and need to move up to project root
		cwd, _ := os.Getwd()
		if filepath.Base(cwd) == "core" {
			_ = os.Chdir("..")
		}

		rootDir, err := findProjectRoot()

		fmt.Printf("Loading registry from: %s\n", rootDir)
		reg, err := registry.LoadRegistry(rootDir)
		if err != nil {
			return nil, nil, nil, nil, nil, fmt.Errorf("registry load error: %w", err)
		}

		// Initialize Store (Central .druppie dir for all persistence)
		storeDir := filepath.Join(rootDir, ".druppie")
		druppieStore, err := store.NewFileStore(storeDir)
		if err != nil {
			return nil, nil, nil, nil, nil, fmt.Errorf("store init error: %w", err)
		}

		// Load Configuration from Store
		cfgMgr, err := config.NewManager(druppieStore)
		if err != nil {
			return nil, nil, nil, nil, nil, fmt.Errorf("config load error: %w", err)
		}
		cfg := cfgMgr.Get()

		// Apply Overrides
		if llmProviderOverride != "" {
			fmt.Printf("Overriding LLM Provider to: %s\n", llmProviderOverride)
			cfg.LLM.DefaultProvider = llmProviderOverride
		}
		if buildProviderOverride != "" {
			fmt.Printf("Overriding Build Provider to: %s\n", buildProviderOverride)
			cfg.Build.DefaultProvider = buildProviderOverride
		}

		// Initialize Build Engine
		buildEngine, err := builder.NewEngine(cfg.Build)
		if err != nil {
			return nil, nil, nil, nil, nil, fmt.Errorf("builder init error: %w", err)
		}

		// Initialize LLM with Config
		llmManager, err := llm.NewManager(context.Background(), cfg.LLM)
		if err != nil {
			return nil, nil, nil, nil, nil, fmt.Errorf("llm init error: %w", err)
		}

		r := router.NewRouter(llmManager, druppieStore, debug)
		p := planner.NewPlanner(llmManager, reg, druppieStore, debug)

		return cfgMgr, reg, r, p, buildEngine, nil
	}

	var serveCmd = &cobra.Command{
		Use:   "serve",
		Short: "Start the Druppie Core API Server",
		Run: func(cmd *cobra.Command, args []string) {
			cfgMgr, reg, routerService, plannerService, buildEngine, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup Error: %v\n", err)
				os.Exit(1)
			}
			tm := NewTaskManager(plannerService)
			cfg := cfgMgr.Get()

			// Start log drainer to:
			// 1. Unblock the buffered channel
			// 2. Print to server console (stdout)
			// 3. Persist to store logs for UI
			go func() {
				// Simple regex to extract Plan ID: [plan-12345]
				// Note: using regexp.MustCompile outside loop would be better but this is fine
				for {
					select {
					case msg := <-tm.OutputChan:
						fmt.Println(msg) // Print to console

						// Extract Plan ID roughly
						var planID string
						// Find "plan-"
						if idx := strings.Index(msg, "plan-"); idx != -1 {
							// Check previous char is [ or space? Not strictly necessary if ID is unique enough
							// Let's take next 15-20 chars until ] or space
							rest := msg[idx:]
							endIdx := strings.IndexAny(rest, "] ")
							if endIdx != -1 {
								planID = rest[:endIdx]
							} else {
								planID = rest
							}
						}

						// Save to store
						_ = plannerService.Store.AppendRawLog(planID, msg)

					case <-tm.TaskDoneChan:
						// Just consume
					}
				}
			}()

			r := chi.NewRouter()
			r.Use(middleware.Logger)
			r.Use(middleware.Recoverer)

			// API Routes
			r.Route("/v1", func(r chi.Router) {
				r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
					w.Write([]byte("OK"))
				})

				// Registry Endpoints
				r.Get("/registry", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					blocks := reg.ListBuildingBlocks()
					json.NewEncoder(w).Encode(blocks)
				})

				// Chat / Intent Endpoint
				r.Post("/chat/completions", func(w http.ResponseWriter, r *http.Request) {
					var req struct {
						Prompt string `json:"prompt"`
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid request body", http.StatusBadRequest)
						return
					}

					// Create plan skeleton IMMEDIATELY for UI visibility
					planID := fmt.Sprintf("plan-%d", time.Now().Unix())
					pendingPlan := model.ExecutionPlan{
						ID: planID,
						Intent: model.Intent{
							InitialPrompt: req.Prompt,
							Prompt:        req.Prompt,
						},
						Status: "pending",
						Steps:  []model.Step{},
					}

					// Save pending plan to store
					if err := plannerService.Store.SavePlan(pendingPlan); err != nil {
						http.Error(w, fmt.Sprintf("Failed to create plan: %v", err), http.StatusInternalServerError)
						return
					}

					// Return plan ID immediately to UI
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(map[string]interface{}{
						"intent": model.Intent{Action: "analyzing"},
						"plan":   pendingPlan,
					})

					// Process asynchronously
					// Process asynchronously
					go func() {
						tm.OutputChan <- fmt.Sprintf("[%s] Analyzing request...", planID)

						// 1. Analyze Intent
						intent, rawRouterResp, err := routerService.Analyze(context.Background(), req.Prompt)
						if err != nil {
							tm.OutputChan <- fmt.Sprintf("[%s] Router failed: %v", planID, err)
							// Update pending plan to failed
							pendingPlan.Status = "stopped"
							_ = plannerService.Store.SavePlan(pendingPlan)
							return
						}

						tm.OutputChan <- fmt.Sprintf("[%s] Intent: %s", planID, intent.Action)

						// 2. Planning (if needed)
						if intent.Action == "create_project" {
							fullPlan, err := plannerService.CreatePlan(context.Background(), intent)
							if err != nil {
								tm.OutputChan <- fmt.Sprintf("[%s] Planner failed: %v", planID, err)
								// Update pending plan to failed
								pendingPlan.Status = "stopped"
								_ = plannerService.Store.SavePlan(pendingPlan)
								return
							}

							// IMPORTANT: Use the pending plan ID, don't create a new one
							fullPlan.ID = planID
							fullPlan.Status = "running"

							tm.OutputChan <- fmt.Sprintf("[%s] Plan created. Starting task...", planID)

							// Log router step
							_ = plannerService.Store.LogInteraction(fullPlan.ID, "Router", req.Prompt, rawRouterResp)

							// Save updated plan (replaces pending plan)
							_ = plannerService.Store.SavePlan(fullPlan)

							// START THE TASK
							tm.StartTask(context.Background(), fullPlan)
						} else {
							tm.OutputChan <- fmt.Sprintf("[%s] Request handled by Router (no plan needed).", planID)

							// Log to generic interaction log
							_ = plannerService.Store.LogInteraction("", "Router", req.Prompt, rawRouterResp)

							// Update plan status to completed (non-project intent)
							pendingPlan.Status = "completed"
							_ = plannerService.Store.SavePlan(pendingPlan)
						}
					}()
				})

				// Agent Endpoint
				r.Get("/agents", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					agents := reg.ListAgents()
					json.NewEncoder(w).Encode(agents)
				})

				// Skill Endpoint
				r.Get("/skills", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					skills := reg.ListSkills()
					json.NewEncoder(w).Encode(skills)
				})

				// Configuration Endpoint
				r.Get("/config", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(cfgMgr.Get().Sanitize())
				})

				// Build Trigger Endpoint
				r.Post("/build", func(w http.ResponseWriter, r *http.Request) {
					var req struct {
						RepoURL    string `json:"repo_url"`
						CommitHash string `json:"commit_hash"`
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid request body", http.StatusBadRequest)
						return
					}

					id, err := buildEngine.TriggerBuild(r.Context(), req.RepoURL, req.CommitHash)
					if err != nil {
						http.Error(w, fmt.Sprintf("Build failed: %v", err), http.StatusInternalServerError)
						return
					}
					json.NewEncoder(w).Encode(map[string]string{"build_id": id})
				})

				// HITL Endpoint (Stub)
				r.Get("/approvals", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode([]string{})
				})

				// --- Task & Plan Monitoring ---
				r.Post("/interaction", func(w http.ResponseWriter, r *http.Request) {
					var req struct {
						PlanID  string `json:"plan_id"`
						AgentID string `json:"agent_id"`
						Action  string `json:"action"`
						Result  string `json:"result"`
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid request", http.StatusBadRequest)
						return
					}
					_ = plannerService.Store.LogInteraction(req.PlanID, req.AgentID, req.Action, req.Result)
					w.WriteHeader(http.StatusOK)
				})

				r.Get("/plans", func(w http.ResponseWriter, r *http.Request) {
					plans, err := plannerService.Store.ListPlans()
					if err != nil {
						http.Error(w, "Failed to list plans", http.StatusInternalServerError)
						return
					}

					// Update plan statuses based on actual task states
					tm.mu.Lock()
					for i := range plans {
						if task, ok := tm.tasks[plans[i].ID]; ok {
							switch task.Status {
							case TaskStatusRunning:
								plans[i].Status = "running"
							case TaskStatusWaitingInput:
								plans[i].Status = "waiting_input"
							case TaskStatusCompleted:
								plans[i].Status = "completed"
							case TaskStatusError:
								plans[i].Status = "stopped"
							}
						} else {
							// No active task - mark as stopped if it claims to be running
							if plans[i].Status == "running" || plans[i].Status == "waiting_input" {
								plans[i].Status = "stopped"
							}
						}
					}
					tm.mu.Unlock()

					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(plans)
				})

				r.Get("/plans/{id}", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					plan, err := plannerService.Store.GetPlan(id)
					if err != nil {
						http.Error(w, "Plan not found", http.StatusNotFound)
						return
					}

					// Update plan status based on actual task state
					tm.mu.Lock()
					if task, ok := tm.tasks[id]; ok {
						switch task.Status {
						case TaskStatusRunning:
							plan.Status = "running"
						case TaskStatusWaitingInput:
							plan.Status = "waiting_input"
						case TaskStatusCompleted:
							plan.Status = "completed"
						case TaskStatusError:
							plan.Status = "stopped"
						}
					} else {
						// No active task - check if plan says running but task is gone
						if plan.Status == "running" || plan.Status == "waiting_input" {
							plan.Status = "stopped"
						}
					}
					tm.mu.Unlock()

					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(plan)
				})

				r.Delete("/plans/{id}", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}

					// Stop the task if running
					tm.mu.Lock()
					if task, ok := tm.tasks[id]; ok {
						task.Cancel()
						delete(tm.tasks, id)
					}
					tm.mu.Unlock()

					// Wait for task to cleanup and logs to drain preventing race condition where log file is recreated
					time.Sleep(500 * time.Millisecond)

					// Delete plan file
					if err := plannerService.Store.DeletePlan(id); err != nil {
						http.Error(w, "Failed to delete plan", http.StatusInternalServerError)
						return
					}

					w.WriteHeader(http.StatusOK)
				})

				r.Post("/plans/{id}/resume", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}

					plan, err := plannerService.Store.GetPlan(id)
					if err != nil {
						http.Error(w, "Plan not found", http.StatusNotFound)
						return
					}

					// Update status to running and restart task
					plan.Status = "running"
					if err := plannerService.Store.SavePlan(plan); err != nil {
						http.Error(w, "Failed to update plan", http.StatusInternalServerError)
						return
					}

					// Restart the task
					tm.StartTask(context.Background(), plan)

					w.WriteHeader(http.StatusOK)
				})

				r.Get("/logs/{id}", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					logs, err := plannerService.Store.GetLogs(id)
					if err != nil {
						http.Error(w, "Logs not found", http.StatusNotFound)
						return
					}
					w.Header().Set("Content-Type", "text/plain")
					w.Write([]byte(logs))
				})

				// Alias for UI which requests /v1/tasks/{id}/output
				r.Get("/tasks/{id}/output", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					logs, err := plannerService.Store.GetLogs(id)
					if err != nil {
						// Return empty log instead of 404 to avoid console errors if just started
						w.Header().Set("Content-Type", "text/plain")
						w.Write([]byte(""))
						return
					}
					w.Header().Set("Content-Type", "text/plain")
					w.Write([]byte(logs))
				})

				r.Post("/tasks/{id}/message", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					var req struct {
						Input string `json:"input"`
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid request", http.StatusBadRequest)
						return
					}

					// Find the task
					// Note: TaskManager stores tasks by plan ID
					// We need to find the plan ID that matches. Actually TaskManager.tasks uses plan.ID.
					// Let's assume the ID passed is the plan ID.
					tm.mu.Lock()
					task, ok := tm.tasks[id]
					tm.mu.Unlock()

					if !ok {
						// Task not started yet - handle stop command directly
						if req.Input == "/stop" {
							plan, err := plannerService.Store.GetPlan(id)
							if err == nil {
								plan.Status = "stopped"
								_ = plannerService.Store.SavePlan(plan)
								w.WriteHeader(http.StatusOK)
								return
							}
						}
						http.Error(w, "Task not found", http.StatusNotFound)
						return
					}

					// Send to task
					select {
					case task.InputChan <- req.Input:
						w.WriteHeader(http.StatusOK)
					case <-time.After(2 * time.Second):
						http.Error(w, "Task is not waiting for input", http.StatusConflict)
					}
				})
			})

			// Serve static files (expecting 'ui' folder to be present in root)
			workDir, _ := os.Getwd()
			var staticRoot string

			// Check if ./ui exists (Docker / Production)
			if _, err := os.Stat(filepath.Join(workDir, "ui")); err == nil {
				staticRoot = workDir
			} else if _, err := os.Stat(filepath.Join(filepath.Dir(workDir), "ui")); err == nil {
				// Check if ../ui exists (Local Development from core/)
				// In this case, we serve the PARENT directory so that /ui/... URLs work correctly
				staticRoot = filepath.Dir(workDir)
			} else {
				fmt.Println("[Warning] Could not find 'ui' directory in ./ui or ../ui. Serving current directory.")
				staticRoot = workDir
			}

			fmt.Printf("Serving static files from root: %s\n", staticRoot)
			fs := http.FileServer(http.Dir(staticRoot))
			r.Handle("/*", fs)

			port := cfg.Server.Port
			if port == "" {
				port = "8080"
			}
			fmt.Printf("Starting server on port %s...\n", port)
			if err := http.ListenAndServe(":"+port, r); err != nil {
				fmt.Printf("Server failed: %v\n", err)
				os.Exit(1)
			}
		},
	}

	var registryCmd = &cobra.Command{
		Use:   "registry",
		Short: "Dump the loaded registry",
		Run: func(cmd *cobra.Command, args []string) {
			_, reg, _, _, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			stats := reg.Stats()
			fmt.Printf("Loaded: %d Building Blocks, %d Skills, %d MCP Servers, %d Agents\n",
				stats["building_blocks"], stats["skills"], stats["mcp_servers"], stats["agents"])

			for _, bb := range reg.ListBuildingBlocks() {
				fmt.Printf("- [Block] %s: %s\n", bb.ID, bb.Name)
			}

			// We access maps directly here for simplicity, or we could add ListSkills/ListMCPServers methods.
			// Since we are in a read-only CLI command initialized sequentially, direct access is okay,
			// but proper practice would be to use helper methods.
			// Let's rely on the fact that we can interact with the struct fields.

			for id, skill := range reg.Skills {
				fmt.Printf("- [Skill] %s: %s\n", id, skill.Name)
			}

			for id, mcp := range reg.MCPServers {
				fmt.Printf("- [MCP] %s: %s\n", id, mcp.Name)
			}

			// ListAgents was added in Phase 2
			for _, agent := range reg.ListAgents() {
				fmt.Printf("- [Agent] %s: %s\n", agent.ID, agent.Name)
			}
		},
	}

	// runInteractiveLoop Removed

	// TaskManager instance
	var tm *TaskManager

	var chatCmd = &cobra.Command{
		Use:   "chat",
		Short: "Start interactive chat",
		Run: func(cmd *cobra.Command, args []string) {
			cfgMgr, _, router, planner, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			cfg := cfgMgr.Get()

			// Initialize TaskManager
			tm = NewTaskManager(planner)

			fmt.Println("--- Druppie Core Chat (Async) ---")
			fmt.Printf("LLM Provider: %s\n", cfg.LLM.DefaultProvider)
			fmt.Println("Commands: /exit, /list, /stop <id>, /switch <id>")

			// Resume plan if ID provided
			if planID != "" {
				fullID := planID
				if !strings.HasPrefix(fullID, "plan-") {
					fullID = "plan-" + fullID
				}
				router.PlanID = fullID
				fmt.Printf("[Chat] Resuming plan: %s\n", fullID)
				plan, err := planner.Store.GetPlan(fullID)
				if err != nil {
					fmt.Printf("[Error] Failed to load plan: %v\n", err)
				} else {
					tm.StartTask(context.Background(), plan)
				}
			}

			// Main Loop
			scanner := bufio.NewScanner(os.Stdin)
			fmt.Print("> ")

			// Input channel to decouple blocking read
			inputChan := make(chan string)
			go func() {
				for scanner.Scan() {
					inputChan <- scanner.Text()
				}
				close(inputChan)
			}()

			var activeTaskID string = ""

			for {
				select {
				case input, ok := <-inputChan:
					if !ok {
						return
					}

					// Handle Global Commands
					if input == "/exit" {
						return
					}
					if input == "/list" {
						tasks := tm.ListTasks()
						fmt.Println("Active Tasks:")
						for _, t := range tasks {
							fmt.Println(" - " + t)
						}
						fmt.Print("> ")
						continue
					}
					if strings.HasPrefix(input, "/stop ") {
						id := strings.TrimSpace(strings.TrimPrefix(input, "/stop "))
						tm.StopTask(id)
						fmt.Print("> ")
						continue
					}
					if strings.HasPrefix(input, "/switch ") {
						id := strings.TrimSpace(strings.TrimPrefix(input, "/switch "))
						activeTaskID = id
						fmt.Printf("Switched active task context to %s\n> ", id)
						continue
					}

					// Route Input
					// If activeTaskID is set and that task is waiting, send it there
					// Else if no active task, try to find one waiting

					targetTask := tm.GetSingleActiveTask()
					if activeTaskID != "" {
						if t, ok := tm.tasks[activeTaskID]; ok {
							targetTask = t
						}
					}

					if targetTask != nil && targetTask.Status == TaskStatusWaitingInput {
						// Send to Task
						targetTask.InputChan <- input
						// Reset prompt
						continue
					}

					// If not handled by task, treat as new Router Request
					if !strings.HasPrefix(input, "/") {
						fmt.Println("[Router - Analyzing]")
						intent, rawRouterResp, err := router.Analyze(context.Background(), input)
						if err != nil {
							fmt.Printf("[Error] Router failed: %v\n> ", err)
							continue
						}

						if intent.Action == "create_project" {
							plan, err := planner.CreatePlan(context.Background(), intent)
							if err != nil {
								fmt.Printf("[Error] Planner failed: %v\n> ", err)
								continue
							}
							_ = planner.Store.LogInteraction(plan.ID, "Router", input, rawRouterResp)

							task := tm.StartTask(context.Background(), plan)
							activeTaskID = task.ID
							fmt.Printf("[Planner] Started Plan %s\n", plan.ID)
						} else {
							fmt.Printf("[Router - %s] %s\n> ", intent.Action, intent.InitialPrompt)
						}
					} else {
						fmt.Println("Unknown command.")
						fmt.Print("> ")
					}

				case log := <-tm.OutputChan:
					// Clear current line if possible or just print
					// Simple print for now
					fmt.Printf("\r%s\n> ", log)

				case id := <-tm.TaskDoneChan:
					fmt.Printf("\r[Task Manager] Task %s Finished.\n> ", id)
				}
			}
		},
	}

	var planCmd = &cobra.Command{
		Use:   "plan [prompt]",
		Short: "Generate a plan for a given prompt",
		Args:  cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			_, _, router, planner, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}

			prompt := strings.Join(args, " ")
			intent, rawRouterResp, err := router.Analyze(context.Background(), prompt)
			if err != nil {
				fmt.Printf("Router failed: %v\n", err)
				os.Exit(1)
			}

			if intent.Action != "create_project" {
				_ = planner.Store.LogInteraction("", "Router", prompt, rawRouterResp)
				fmt.Printf("Intent was '%s', which doesn't trigger a planner in this CLI.\n", intent.Action)
				return
			}

			plan, err := planner.CreatePlan(context.Background(), intent)
			if err != nil {
				fmt.Printf("Planner failed: %v\n", err)
				os.Exit(1)
			}
			// Log router step to plan log
			_ = planner.Store.LogInteraction(plan.ID, "Router", prompt, rawRouterResp)

			// Initialize TaskManager for execution
			tm := NewTaskManager(planner)
			task := tm.StartTask(context.Background(), plan)
			fmt.Printf("[Planner] Started Plan %s execution...\n", plan.ID)

			// Execution Loop
			done := false
			for !done {
				select {
				case log := <-tm.OutputChan:
					fmt.Println(log)
				case <-time.After(500 * time.Millisecond):
					// Check status periodically
					// Note: Direct access is slightly racy but acceptable for this CLI tool
					switch task.Status {
					case TaskStatusWaitingInput:
						fmt.Println("[Auto-Pilot] Input required. Auto-accepting defaults...")
						// Simulate user verify/accept delay
						time.Sleep(1 * time.Second)
						task.InputChan <- "/accept"
					case TaskStatusCompleted:
						fmt.Println("[Auto-Pilot] Plan execution completed successfully.")
						done = true
					case TaskStatusError:
						fmt.Println("[Auto-Pilot] Plan execution failed.")
						done = true
					}
				}
			}

			// Fetch final state
			finalPlan, _ := planner.Store.GetPlan(plan.ID)
			plan = finalPlan

			// validJSON, _ := json.MarshalIndent(plan, "", "  ")
			// fmt.Println(string(validJSON))
		},
	}

	rootCmd.PersistentFlags().StringVar(&planID, "plan-id", "", "ID of an existing plan to resume or manage")
	rootCmd.PersistentFlags().StringVar(&llmProviderOverride, "llm-provider", "", "Override default LLM provider")
	rootCmd.PersistentFlags().StringVar(&buildProviderOverride, "build-provider", "", "Override default Build provider")
	rootCmd.PersistentFlags().BoolVar(&debug, "debug", true, "Enable debug mode (print raw LLM responses)")

	rootCmd.AddCommand(registryCmd)
	rootCmd.AddCommand(chatCmd)
	rootCmd.AddCommand(planCmd)
	rootCmd.AddCommand(serveCmd)

	// Default to server mode
	rootCmd.Run = serveCmd.Run

	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
