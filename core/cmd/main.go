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
	setup := func(cmd *cobra.Command) (*config.Manager, *registry.Registry, *router.Router, *planner.Planner, builder.BuildEngine, error) {
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
			cfg := cfgMgr.Get()

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

					// 1. Analyze Intent
					intent, rawRouterResp, err := routerService.Analyze(r.Context(), req.Prompt)
					if err != nil {
						http.Error(w, fmt.Sprintf("Router failed: %v", err), http.StatusInternalServerError)
						return
					}

					// 2. Planning (if needed)
					var plan *model.ExecutionPlan
					if intent.Action == "create_project" {
						p, err := plannerService.CreatePlan(r.Context(), intent)
						if err != nil {
							http.Error(w, fmt.Sprintf("Planner failed: %v", err), http.StatusInternalServerError)
							return
						}
						plan = &p
						// Log router step to plan log
						_ = plannerService.Store.LogInteraction(plan.ID, "Router", req.Prompt, rawRouterResp)
					} else {
						// Log to generic interaction log
						_ = plannerService.Store.LogInteraction("", "Router", req.Prompt, rawRouterResp)
					}

					// 3. Response
					resp := map[string]interface{}{
						"intent": intent,
						"plan":   plan,
					}
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(resp)
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

				// MCP Endpoint
				r.Get("/mcps", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					mcpServers := reg.ListMCPServers()
					json.NewEncoder(w).Encode(mcpServers)
				})

				// Configuration Endpoint
				r.Get("/config", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(cfgMgr.Get().Sanitize())
				})

				r.Put("/config", func(w http.ResponseWriter, r *http.Request) {
					currentConfig := cfgMgr.Get()
					if err := json.NewDecoder(r.Body).Decode(&currentConfig); err != nil {
						http.Error(w, "Invalid config", http.StatusBadRequest)
						return
					}
					if err := cfgMgr.Update(currentConfig); err != nil {
						http.Error(w, fmt.Sprintf("Failed to update config: %v", err), http.StatusInternalServerError)
						return
					}
					w.WriteHeader(http.StatusOK)
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
			})

			// Serve static files from current directory
			workDir, _ := os.Getwd()
			fmt.Printf("Serving static files from: %s\n", workDir)
			fs := http.FileServer(http.Dir(workDir))
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
					if task.Status == TaskStatusWaitingInput {
						fmt.Println("[Auto-Pilot] Input required. Auto-accepting defaults...")
						// Simulate user verify/accept delay
						time.Sleep(1 * time.Second)
						task.InputChan <- "/accept"
					} else if task.Status == TaskStatusCompleted {
						fmt.Println("[Auto-Pilot] Plan execution completed successfully.")
						done = true
					} else if task.Status == TaskStatusError {
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
