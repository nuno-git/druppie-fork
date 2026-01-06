package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/config"
	"github.com/sjhoeksma/druppie/core/internal/converter"
	"github.com/sjhoeksma/druppie/core/internal/iam"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/planner"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/router"
	"github.com/sjhoeksma/druppie/core/internal/store"
	"github.com/spf13/cobra"
	"golang.org/x/term"
)

func getAuthContext(ctx context.Context, p iam.Provider, demo bool) context.Context {
	if demo {
		u := &iam.User{ID: "demo", Username: "demo", Groups: []string{"root", "admin"}}
		return iam.ContextWithUser(ctx, u)
	}

	if _, ok := p.(*iam.DemoProvider); ok {
		u := &iam.User{ID: "demo", Username: "demo", Groups: []string{"root", "admin"}}
		return iam.ContextWithUser(ctx, u)
	}

	token, err := iam.LoadClientToken()
	if err != nil || token == "" {
		return ctx
	}

	if lp, ok := p.(*iam.LocalProvider); ok {
		if u, ok := lp.GetUserByToken(token); ok {
			return iam.ContextWithUser(ctx, u)
		}
	}
	return ctx
}

var (
	Version = "-.-.-"
)

func main() {
	// 0. Version Check
	if len(os.Args) > 1 && (os.Args[1] == "version" || os.Args[1] == "--version") {
		fmt.Printf("Druppie version: %s\n", Version)
		os.Exit(0)
	}

	var rootCmd = &cobra.Command{
		Use:   "druppie",
		Short: "Druppie Helper CLI & API Server",
		Long: `Druppie manages the Registry, Planner, and Orchestration API. 
By default, it starts the API Server on port 8080. 
Use global flags like --plan-id to resume existing planning tasks or --llm-provider to switch backends.`,
	}

	// CLI Flags
	var llmProviderOverride string
	var buildProviderOverride string
	var debug bool
	var demo bool
	var planID string

	// Register commands
	rootCmd.AddCommand(newGenerateCmd())
	rootCmd.AddCommand(newCliCmd())

	// Helper to bootstrap dependencies
	// Helper to bootstrap dependencies
	// Returns ConfigManager to allow updates, and Builder Engine
	setup := func(_ *cobra.Command) (*config.Manager, *registry.Registry, *router.Router, *planner.Planner, *mcp.Manager, builder.BuildEngine, iam.Provider, error) {
		// If demo flag is set, force IAM provider to demo via env var (handled by config manager loadEnv)
		if demo {
			os.Setenv("IAM_PROVIDER", "demo")
		}

		// Ensure we are working from the project root (handles Chdir)
		if err := ensureProjectRoot(); err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("root detection error: %w", err)
		}

		rootDir, err := findProjectRoot()
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("registry path error: %w", err)
		}

		reg, err := registry.LoadRegistry(rootDir)
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("registry load error: %w", err)
		}
		stats := reg.Stats()
		fmt.Printf("Loading registry (%d Blocks, %d Skills, %d MCP, %d Agents, %d Compliance) from: %s\n",
			stats["building_blocks"], stats["skills"], stats["mcp_servers"], stats["agents"], stats["compliance_rules"], rootDir)

		// Initialize Store (Central .druppie dir for all persistence)
		storeDir := filepath.Join(rootDir, ".druppie")
		druppieStore, err := store.NewFileStore(storeDir)
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("store init error: %w", err)
		}

		// Load Configuration from Store
		cfgMgr, err := config.NewManager(druppieStore)
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("config load error: %w", err)
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
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("builder init error: %w", err)
		}

		// Initialize LLM with Config
		llmManager, err := llm.NewManager(context.Background(), cfg.LLM)
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("llm init error: %w", err)
		}

		// Initialize MCP Manager
		mcpManager := mcp.NewManager(context.Background(), druppieStore, reg)

		r := router.NewRouter(llmManager, druppieStore, reg, debug)
		p := planner.NewPlanner(llmManager, reg, druppieStore, mcpManager, debug)

		iamProv, err := iam.NewProvider(cfg.IAM, rootDir)
		if err != nil {
			return nil, nil, nil, nil, nil, nil, nil, fmt.Errorf("iam init error: %w", err)
		}

		return cfgMgr, reg, r, p, mcpManager, buildEngine, iamProv, nil
	}

	var serveCmd = &cobra.Command{
		Use:   "serve",
		Short: "Start the Druppie API Server",
		Run: func(cmd *cobra.Command, args []string) {
			cfgMgr, reg, routerService, plannerService, mcpManager, buildEngine, iamProvider, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup Error: %v\n", err)
				os.Exit(1)
			}
			tm := NewTaskManager(plannerService, mcpManager, buildEngine)
			cfg := cfgMgr.Get()

			// Start Cleanup Routine
			go func() {
				rootDir, _ := findProjectRoot()
				if rootDir != "" {
					storeDir := filepath.Join(rootDir, ".druppie")
					cleanupDays := cfg.Server.CleanupDays
					if cleanupDays <= 0 {
						cleanupDays = 7 // Default fallback if config missing
					}

					// Helper function
					doCleanup := func() {
						fmt.Printf("[Cleanup] Checking for plans older than %d days...\n", cleanupDays)
						plansDir := filepath.Join(storeDir, "plans")
						entries, err := os.ReadDir(plansDir)
						if err != nil {
							fmt.Printf("[Cleanup] Failed to read plans dir: %v\n", err)
							return
						}

						cutoff := time.Now().AddDate(0, 0, -cleanupDays)
						count := 0

						for _, entry := range entries {
							if entry.IsDir() {
								planPath := filepath.Join(plansDir, entry.Name(), "plan.json")
								info, err := os.Stat(planPath)
								if err == nil && info.ModTime().Before(cutoff) {
									id := entry.Name()
									// Use Store to delete (handles logs/files/plans)
									if err := plannerService.Store.DeletePlan(id); err == nil {
										count++
										fmt.Printf("[Cleanup] Deleted old plan: %s (Age: %s)\n", id, time.Since(info.ModTime()).Round(time.Hour))
									} else {
										fmt.Printf("[Cleanup] Failed to delete plan %s: %v\n", id, err)
									}
								}
							}
						}
						if count > 0 {
							fmt.Printf("[Cleanup] Completed. Removed %d old plans.\n", count)
						}
					}

					// Initial run
					doCleanup()

					// Periodic run (every 24h)
					ticker := time.NewTicker(24 * time.Hour)
					for range ticker.C {
						doCleanup()
					}
				}
			}()

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
						//fmt.Println(msg) // Output to console for visibility

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
							// Sanitize ID (remove trailing punctuation)
							planID = strings.TrimRight(planID, ".,;:!?\")")
						}

						// Save to store
						_ = plannerService.Store.AppendRawLog(planID, msg)

					case <-tm.TaskDoneChan:
						// Just consume
					}
				}
			}()

			r := chi.NewRouter()
			// Custom Error-Only Logger (Silences 200 OKs)
			r.Use(func(next http.Handler) http.Handler {
				return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					ww := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
					t1 := time.Now()
					defer func() {
						// Log only if status >= 400 and not 404 (suppress Not Found noise)
						if ww.Status() >= 400 && ww.Status() != 404 {
							fmt.Printf("[HTTP] %s %s -> %d (%dB) in %s\n",
								r.Method, r.URL.Path, ww.Status(), ww.BytesWritten(), time.Since(t1))
						}
					}()
					next.ServeHTTP(ww, r)
				})
			})
			r.Use(middleware.Recoverer)

			// UI Route
			r.Get("/admin", func(w http.ResponseWriter, r *http.Request) {
				root, _ := findProjectRoot()
				http.ServeFile(w, r, filepath.Join(root, "ui", "admin.html"))
			})

			r.Get("/code", func(w http.ResponseWriter, r *http.Request) {
				root, _ := findProjectRoot()
				http.ServeFile(w, r, filepath.Join(root, "ui", "code.html"))
			})

			// Public System Info
			r.Get("/info", func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				cfg := cfgMgr.Get()

				// Determine if auth is required
				// Logic: If IAM provider is NOT 'demo' (and maybe eventually 'none'), it is required.
				// However, config.IAM.Provider defaults to 'local'.
				authRequired := cfg.IAM.Provider != "demo"

				resp := map[string]interface{}{
					"auth_required": authRequired,
					"iam": map[string]string{
						"provider": cfg.IAM.Provider,
					},
				}
				json.NewEncoder(w).Encode(resp)
			})

			// Public Version Endpoint
			// Public Version Endpoint
			r.Get("/v1/version", func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")

				// Format version: v1.0.1-1-g123 -> 1.0.1
				v := strings.TrimPrefix(Version, "v")
				if idx := strings.Index(v, "-"); idx != -1 {
					v = v[:idx]
				}

				json.NewEncoder(w).Encode(map[string]string{
					"version": v,
				})
			})

			// API Routes
			r.Route("/v1", func(r chi.Router) {
				// Apply IAM Middleware to all v1 routes
				r.Use(iamProvider.Middleware())
				iamProvider.RegisterRoutes(r)

				r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
					w.Write([]byte("OK"))
				})

				// Registry Endpoints
				r.Get("/registry", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					user, _ := iam.GetUserFromContext(r.Context())
					var groups []string
					if user != nil {
						groups = user.Groups
					}
					blocks := reg.ListBuildingBlocks(groups)
					json.NewEncoder(w).Encode(blocks)
				})

				// Chat / Intent Endpoint
				r.Post("/chat/completions", func(w http.ResponseWriter, r *http.Request) {
					var req struct {
						Prompt string `json:"prompt"`
						PlanID string `json:"plan_id"` // Optional: Context for continuing chat
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid request body", http.StatusBadRequest)
						return
					}

					var currentPlan model.ExecutionPlan
					var planID string
					isNewPlan := true

					// Check if we are continuing an existing conversation
					if req.PlanID != "" {
						if p, err := plannerService.Store.GetPlan(req.PlanID); err == nil {
							currentPlan = p
							planID = p.ID
							isNewPlan = false
						}
					}

					if isNewPlan {
						// Create new plan skeleton
						planID = fmt.Sprintf("plan-%d", time.Now().Unix())
						currentPlan = model.ExecutionPlan{
							ID: planID,
							Intent: model.Intent{
								InitialPrompt: req.Prompt,
								Prompt:        req.Prompt,
							},
							Status: "completed",
							Steps:  []model.Step{},
						}
						// If user is authenticated, set creator ID
						user, _ := iam.GetUserFromContext(r.Context())
						if user != nil {
							currentPlan.CreatorID = user.Username
							// Optional: Add creator's groups by default?
							// currentPlan.AllowedGroups = user.Groups
							// Let's keep it clean for now, maybe just Creator access implicity logic elsewhere?
							// The user request was "allow a plan to be accessible by users that are within the group list"
							// So we need to populate this list.
						}
					} else {
						// Update status of existing plan to indicate activity
						currentPlan.Status = "running"
					}

					// Store User Input as a Step (for both New and Existing plans)
					newStepID := 1
					if len(currentPlan.Steps) > 0 {
						newStepID = currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
					}
					currentPlan.Steps = append(currentPlan.Steps, model.Step{
						ID:      newStepID,
						AgentID: "user",
						Action:  "user_query",
						Status:  "running",
						Result:  req.Prompt,
					})
					currentPlan.Status = "running"

					// Save plan state (create or update timestamp/status)
					if err := plannerService.Store.SavePlan(currentPlan); err != nil {
						http.Error(w, fmt.Sprintf("Failed to save plan: %v", err), http.StatusInternalServerError)
						return
					}

					// Return plan ID immediately to UI
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(map[string]interface{}{
						"intent": model.Intent{Action: "analyzing"},
						"plan":   currentPlan,
					})

					// Process asynchronously
					// Capture user from request context before async
					user, userOk := iam.GetUserFromContext(r.Context())

					// Process asynchronously
					go func() {
						// Create background context with user
						ctx := context.Background()
						if userOk {
							ctx = iam.ContextWithUser(ctx, user)
						}
						tm.OutputChan <- fmt.Sprintf("[%s] Analyzing request...", planID)

						effectivePrompt := req.Prompt
						if !isNewPlan {
							//tm.OutputChan <- fmt.Sprintf("[DEBUG] Loading plan %s. Steps found: %d", planID, len(currentPlan.Steps))
							// 1. Build Context
							history := ""
							// Exclude the last step (current request) which was already appended
							priorSteps := currentPlan.Steps[:len(currentPlan.Steps)-1]

							startIdx := 0
							if len(priorSteps) > 20 {
								startIdx = len(priorSteps) - 20
							}
							for _, s := range priorSteps[startIdx:] {
								switch s.Action {
								case "user_query":
									history += fmt.Sprintf("User: %s\n", s.Result)
								case "general_chat":
									history += fmt.Sprintf("AI: %s\n", s.Result)
								}
							}
							effectivePrompt = fmt.Sprintf("History:\n%s\nRequest: %s", history, req.Prompt)
							//tm.OutputChan <- fmt.Sprintf("[DEBUG] Constructed History: %s", history)
						}

						// 2. Analyze Intent
						intent, _, err := routerService.Analyze(ctx, planID, effectivePrompt)
						if err != nil {
							tm.OutputChan <- fmt.Sprintf("[%s] Router failed: %v", planID, err)
							// Update pending plan to failed
							currentPlan.Status = "stopped"
							_ = plannerService.Store.SavePlan(currentPlan)
							return
						}

						tm.OutputChan <- fmt.Sprintf("[%s] Intent: %s", planID, intent.Action)

						// Update currentPlan with the analyzed intent
						currentPlan.Intent.Action = intent.Action
						currentPlan.Intent.Category = intent.Category
						currentPlan.Intent.Language = intent.Language
						currentPlan.Intent.ContentType = intent.ContentType

						// Mark user_query as completed (since plan is now generated)
						// This ensures it is preserved by task_manager's cleanup logic,
						// fixing the issue where "pending" steps were being deleted.
						for i, s := range currentPlan.Steps {
							if s.Action == "user_query" && s.Status == "running" {
								currentPlan.Steps[i].Status = "completed"
								///currentPlan.Status = "running" //We are now running
								_ = plannerService.Store.SavePlan(currentPlan)
							}
						}

						// 3. Execution
						// Treat any action that IS NOT simple chat as a request for Planning/Execution.
						// This ensures query_registry, orchestrate_complex, etc., are handled by the Planner.
						if intent.Action != "general_chat" {
							// If we were chatting, we might want to start fresh or pivot.
							// For simplicity, we treat this as a "New Plan" triggering event.
							// Stop the active task to prevent it from marking the plan as "Completed"
							// while we are generating the new plan.
							tm.StopTask(planID)
							// Wait longer to ensure `runTaskLoop` has fully exited and flushed its "stopped" state to disk
							time.Sleep(500 * time.Millisecond)

							// Reload plan from store to ensure we have the very latest state (including any "stopped" status wrote by the dying task)
							// This prevents us from saving a stale version that might be overwritten or merging blindly.
							if freshPlan, err := plannerService.Store.GetPlan(planID); err == nil {
								// We must preserve the INTENT from our local `currentPlan` / `req` because
								// the fresh plan from disk might be stale regarding the *new* intent we just analyzed.
								// `currentPlan` has the `intent` from router. `freshPlan` has the old intent.
								// Only `Steps` and `Status` are relevant from disk.
								// Actually, `currentPlan` in this scope has the NEW intent from Router (Line 305).
								// We want to keep that. We only want to ensure `Steps` are up to date (e.g. if Step 1 completed).
								currentPlan.Steps = freshPlan.Steps
								// But we ignore freshPlan.Status because we are about to force it to Running.
							}

							// User wants "content of current chat retained".
							// So we pass the effectivePrompt (with history) to the Planner!
							intent.InitialPrompt = effectivePrompt
							intent.Prompt = effectivePrompt // Planner uses this

							// Indicate we are starting the work
							currentPlan.Status = "running"
							// Add a temporary step to show in Kanban even without UI hacks
							newStepID := 1
							if len(currentPlan.Steps) > 0 {
								newStepID = currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
							}
							genPlanStep := model.Step{
								ID:      newStepID,
								AgentID: "planner",
								Action:  "generate_plan",
								Status:  "running",
								Result:  "Designing execution plan...",
							}
							currentPlan.Steps = append(currentPlan.Steps, genPlanStep)
							_ = plannerService.Store.SavePlan(currentPlan)
							tm.OutputChan <- fmt.Sprintf("[%s] Generating Plan...", planID)

							fullPlan, err := plannerService.CreatePlan(ctx, intent, planID)
							if err != nil {
								tm.OutputChan <- fmt.Sprintf("[%s] Planner failed: %v", planID, err)
								currentPlan.Status = "stopped"
								// Mark generate_plan as failed
								currentPlan.Steps[len(currentPlan.Steps)-1].Status = "failed"
								currentPlan.Steps[len(currentPlan.Steps)-1].Result = fmt.Sprintf("Failed: %v", err)
								_ = plannerService.Store.SavePlan(currentPlan)
								return
							}

							// Mark generate_plan as completed
							currentPlan.Steps[len(currentPlan.Steps)-1].Status = "completed"
							currentPlan.Steps[len(currentPlan.Steps)-1].Result = "Plan generated."

							// MERGE new steps into current plan
							nextID := currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
							for i := range fullPlan.Steps {
								fullPlan.Steps[i].ID = nextID + i
								// Fix dependencies if they refer to local IDs (1, 2...)
								// This is tricky. Usually dependencies are relative to the new block.
								// We should shift them by (nextID - 1).
								var newDeps []int
								for _, dep := range fullPlan.Steps[i].DependsOn {
									newDeps = append(newDeps, dep+(nextID-1))
								}
								fullPlan.Steps[i].DependsOn = newDeps
							}
							currentPlan.Steps = append(currentPlan.Steps, fullPlan.Steps...)
							currentPlan.SelectedAgents = fullPlan.SelectedAgents
							currentPlan.Status = "running"

							tm.OutputChan <- fmt.Sprintf("[%s] Plan created. Starting task...", planID)

							// Log router step - MOVED TO ROUTER INTERNALLY
							// _ = plannerService.Store.LogInteraction(currentPlan.ID, "Router", req.Prompt, rawRouterResp)

							// Save updated plan
							_ = plannerService.Store.SavePlan(currentPlan)

							// START THE TASK
							tm.StartTask(ctx, currentPlan)
						} else {
							tm.OutputChan <- fmt.Sprintf("[%s] Request handled by Router (no plan needed).", planID)

							// Log to plan-specific log so UI sees it - MOVED TO ROUTER INTERNALLY
							// _ = plannerService.Store.LogInteraction(planID, "Router", effectivePrompt, rawRouterResp)

							// Determine result to show
							resultText := intent.Answer
							if resultText == "" {
								// Fallback to the summary/prompt if no direct answer
								resultText = intent.Prompt
							}

							// Output the response to the console
							tm.OutputChan <- fmt.Sprintf("[%s] Response: %s", planID, resultText)

							// Update plan status to completed and store the answer as a step
							currentPlan.Status = "completed"

							newID := 1
							if len(currentPlan.Steps) > 0 {
								newID = currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
							}

							currentPlan.Steps = append(currentPlan.Steps, model.Step{
								ID:      newID,
								AgentID: "router",
								Action:  "general_chat",
								Status:  "completed",
								Result:  resultText,
							})
							_ = plannerService.Store.SavePlan(currentPlan)
						}
					}()
				})

				// Configuration Endpoint
				r.Get("/config", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(cfgMgr.Get().Sanitize())
				})
				r.Put("/config", func(w http.ResponseWriter, r *http.Request) {
					// We need the raw config struct from the request
					// Note: validation should happen here
					var newCfg config.Config
					if err := json.NewDecoder(r.Body).Decode(&newCfg); err != nil {
						http.Error(w, "Invalid Config", http.StatusBadRequest)
						return
					}
					// Update via manager
					if err := cfgMgr.Update(newCfg); err != nil {
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

					id, err := buildEngine.TriggerBuild(r.Context(), req.RepoURL, req.CommitHash, "", nil)
					if err != nil {
						http.Error(w, fmt.Sprintf("Build failed: %v", err), http.StatusInternalServerError)
						return
					}
					json.NewEncoder(w).Encode(map[string]string{"build_id": id})
				})

				// MCP Endpoints
				r.Route("/mcp", func(r chi.Router) {
					manager := tm.MCPManager

					r.Get("/servers", func(w http.ResponseWriter, r *http.Request) {
						w.Header().Set("Content-Type", "application/json")
						json.NewEncoder(w).Encode(manager.GetServers())
					})

					r.Post("/servers", func(w http.ResponseWriter, r *http.Request) {
						var req struct {
							Name string `json:"name"`
							URL  string `json:"url"`
						}
						if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
							http.Error(w, "Invalid body", http.StatusBadRequest)
							return
						}

						// Basic validation
						if req.Name == "" || req.URL == "" {
							http.Error(w, "Name and URL required", http.StatusBadRequest)
							return
						}

						// Connect
						if err := manager.AddServer(r.Context(), req.Name, req.URL); err != nil {
							http.Error(w, fmt.Sprintf("Failed to add server: %v", err), http.StatusInternalServerError)
							return
						}
						w.WriteHeader(http.StatusCreated)
					})

					r.Get("/tools", func(w http.ResponseWriter, r *http.Request) {
						w.Header().Set("Content-Type", "application/json")
						json.NewEncoder(w).Encode(manager.ListAllTools())
					})
				})

				// Tasks/Approvals Endpoint
				r.Get("/tasks", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					user, hasUser := iam.GetUserFromContext(r.Context())

					plans, err := plannerService.Store.ListPlans()
					if err != nil {
						http.Error(w, "Failed to list plans", http.StatusInternalServerError)
						return
					}

					type Task struct {
						PlanID        string `json:"plan_id"`
						PlanName      string `json:"plan_name"`
						StepID        int    `json:"step_id"`
						Description   string `json:"description"`
						AssignedGroup string `json:"assigned_group"`
						AgentID       string `json:"agent_id"`
					}

					var tasks []Task

					for _, p := range plans {
						// Only consider plans that are running or waiting
						// Actually, we should check the Step status primarily.
						for _, s := range p.Steps {
							// Status "waiting_input" or "requires_approval" (future strict status)
							if s.Status == "waiting_input" || s.Status == "requires_approval" {
								// Check Assignment
								allowed := false
								if s.AssignedGroup == "" {
									// Public/Creator specific? Default to creator if exists
									if p.CreatorID == "" {
										allowed = true
									} else if hasUser && p.CreatorID == user.Username {
										allowed = true
									}
								} else if hasUser {
									for _, g := range user.Groups {
										if g == s.AssignedGroup || g == "root" || g == "admin" {
											allowed = true
											break
										}
									}
								}

								if allowed {
									tasks = append(tasks, Task{
										PlanID:        p.ID,
										PlanName:      p.Intent.Prompt,
										StepID:        s.ID,
										Description:   s.Result, // Often contains the question/prompt
										AssignedGroup: s.AssignedGroup,
										AgentID:       s.AgentID,
									})
								}
							}
						}
					}

					json.NewEncoder(w).Encode(tasks)
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

					// Filter plans by creator (if user is authenticated)
					if user, ok := iam.GetUserFromContext(r.Context()); ok {

						// If user is 'demo' user (ID 'demo-user'), show everything
						if user.ID == "demo-user" {
							// No filtering needed
						} else {
							// Check if user is admin (optional, for now strictly filtering per request)
							// Iterate and filter
							var filtered []model.ExecutionPlan
							for _, p := range plans {
								// Show plan if:
								// 1. It has no creator (legacy/demo/public)
								// 2. User is the creator
								// 3. User is in one of the allowed groups
								allowed := false
								if p.CreatorID == "" || p.CreatorID == user.Username {
									allowed = true
								} else {
									// Check groups
									for _, allowedGroup := range p.AllowedGroups {
										for _, userGroup := range user.Groups {
											if allowedGroup == userGroup {
												allowed = true
												break
											}
										}
										if allowed {
											break
										}
									}
								}

								if allowed {
									filtered = append(filtered, p)
								}
							}
							plans = filtered
						}
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
							// Commented out to prevent UI flickering "Stopped" during short transitions or if task is running in background but not in memory list yet?
							// Actually, if task is NOT in memory, it IS stopped effectively.
							// BUT during `CreatePlan`, we StopTask provided we manually set status="running".
							// So if we trust Disk, we should NOT override here.
							// if plans[i].Status == "running" || plans[i].Status == "waiting_input" {
							// 	plans[i].Status = "stopped"
							// }
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
						// No active task - check if plan says running but task is gone (Zombie State)
						if plan.Status == "running" || plan.Status == "waiting_input" {
							plan.Status = "stopped"
							// We DON'T auto-save to disk here to allow user to see it was once running
							// and explicitly resume or manage it.
							// _ = plannerService.Store.SavePlan(plan)
						}
					}
					tm.mu.Unlock()

					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(plan)
				})

				// --- File Management for UI ---
				r.Get("/plans/{id}/files", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}

					// Find plan dir: .druppie/plans/<id>/src (source code only)
					root, _ := findProjectRoot()
					planDir := filepath.Join(root, ".druppie", "plans", id, "src")

					var files []string
					// Walk relative
					err := filepath.Walk(planDir, func(path string, info os.FileInfo, err error) error {
						if err != nil {
							return err
						}
						if !info.IsDir() {
							rel, _ := filepath.Rel(planDir, path)
							// Filter out common junk
							if !strings.Contains(rel, ".git") && !strings.HasPrefix(rel, "node_modules") {
								files = append(files, rel)
							}
						}
						return nil
					})

					if err != nil {
						http.Error(w, "Error listing files", http.StatusInternalServerError)
						return
					}
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(files)
				})

				r.Get("/plans/{id}/files/content", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					pathParam := r.URL.Query().Get("path")
					if pathParam == "" {
						http.Error(w, "path required", http.StatusBadRequest)
						return
					}

					root, _ := findProjectRoot()
					planDir := filepath.Join(root, ".druppie", "plans", id, "src")
					absPath := filepath.Join(planDir, pathParam)

					// Security check
					cleanPlan := filepath.Clean(planDir)
					cleanTarget := filepath.Clean(absPath)
					if !strings.HasPrefix(cleanTarget, cleanPlan) {
						http.Error(w, "Forbidden path", http.StatusForbidden)
						return
					}

					http.ServeFile(w, r, absPath)
				})

				r.Put("/plans/{id}/files/content", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					pathParam := r.URL.Query().Get("path")
					if pathParam == "" {
						http.Error(w, "path required", http.StatusBadRequest)
						return
					}

					root, _ := findProjectRoot()
					planDir := filepath.Join(root, ".druppie", "plans", id, "src")
					absPath := filepath.Join(planDir, pathParam)

					// Security check
					cleanPlan := filepath.Clean(planDir)
					cleanTarget := filepath.Clean(absPath)
					if !strings.HasPrefix(cleanTarget, cleanPlan) {
						http.Error(w, "Forbidden path", http.StatusForbidden)
						return
					}

					content, err := io.ReadAll(r.Body)
					if err != nil {
						http.Error(w, "Failed read body", http.StatusBadRequest)
						return
					}

					if err := os.WriteFile(absPath, content, 0644); err != nil {
						http.Error(w, "Failed write file", http.StatusInternalServerError)
						return
					}
					w.Write([]byte("OK"))
				})

				// --- Plugin Promotion ---
				r.Post("/plans/{id}/builds/{buildID}/promote", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}
					buildID := chi.URLParam(r, "buildID")

					var req struct {
						Name        string `json:"name"`
						Description string `json:"description"`
					}
					if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
						http.Error(w, "Invalid body", http.StatusBadRequest)
						return
					}

					root, _ := findProjectRoot()
					conv := converter.NewPluginConverter(reg, root)

					if err := conv.ConvertBuildToBlock(id, buildID, req.Name, req.Description); err != nil {
						http.Error(w, fmt.Sprintf("Promotion failed: %v", err), http.StatusInternalServerError)
						return
					}

					w.Write([]byte("OK"))
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

				r.Post("/plans/{id}/stop", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}

					// Stop the task via TaskManager but mark as finished/completed per user request
					tm.FinishTask(id)

					// Force update plan status to cancelled.
					// Note: Finishtask runs async cancellation which also updates the plan.
					// But we update here specifically to handle cases where the task wasn't running in memory.
					plan, err := plannerService.Store.GetPlan(id)
					if err == nil {
						plan.Status = "cancelled"
						// Also mark pending steps as cancelled here to handle non-running tasks
						// or ensure consistency if TaskManager didn't catch it.
						for i := range plan.Steps {
							s := &plan.Steps[i]
							if s.Status == "pending" || s.Status == "running" || s.Status == "waiting_input" {
								s.Status = "cancelled"
								s.Result = "Cancelled by user"
							}
						}
						_ = plannerService.Store.SavePlan(plan)
					}

					w.WriteHeader(http.StatusOK)
				})

				// Group Management Endpoints for Plans
				r.Post("/plans/{id}/groups/{group}", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					group := chi.URLParam(r, "group")

					plan, err := plannerService.Store.GetPlan(id)
					if err != nil {
						http.Error(w, "Plan not found", http.StatusNotFound)
						return
					}

					// Check duplication
					exists := false
					for _, g := range plan.AllowedGroups {
						if g == group {
							exists = true
							break
						}
					}
					if !exists {
						plan.AllowedGroups = append(plan.AllowedGroups, group)
						if err := plannerService.Store.SavePlan(plan); err != nil {
							http.Error(w, "Failed to update plan", http.StatusInternalServerError)
							return
						}
					}
					w.WriteHeader(http.StatusOK)
				})

				r.Delete("/plans/{id}/groups/{group}", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					group := chi.URLParam(r, "group")

					plan, err := plannerService.Store.GetPlan(id)
					if err != nil {
						http.Error(w, "Plan not found", http.StatusNotFound)
						return
					}

					newGroups := []string{}
					for _, g := range plan.AllowedGroups {
						if g != group {
							newGroups = append(newGroups, g)
						}
					}
					plan.AllowedGroups = newGroups
					if err := plannerService.Store.SavePlan(plan); err != nil {
						http.Error(w, "Failed to update plan", http.StatusInternalServerError)
						return
					}
					w.WriteHeader(http.StatusOK)
				})

				r.Get("/plans/{id}/groups", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					plan, err := plannerService.Store.GetPlan(id)
					if err != nil {
						http.Error(w, "Plan not found", http.StatusNotFound)
						return
					}
					w.Header().Set("Content-Type", "application/json")
					json.NewEncoder(w).Encode(plan.AllowedGroups)
				})

				r.Post("/plans/{id}/files", func(w http.ResponseWriter, r *http.Request) {
					id := chi.URLParam(r, "id")
					if !strings.HasPrefix(id, "plan-") {
						id = "plan-" + id
					}

					// Update max upload size to 50MB
					r.Body = http.MaxBytesReader(w, r.Body, 50<<20)
					if err := r.ParseMultipartForm(50 << 20); err != nil {
						http.Error(w, "File too big", http.StatusBadRequest)
						return
					}

					file, header, err := r.FormFile("file")
					if err != nil {
						http.Error(w, "Invalid file", http.StatusBadRequest)
						return
					}
					defer file.Close()

					rootDir, _ := findProjectRoot()
					if rootDir == "" {
						http.Error(w, "Project root not found", http.StatusInternalServerError)
						return
					}

					targetDir := filepath.Join(rootDir, ".druppie", "plans", id, "files")
					if err := os.MkdirAll(targetDir, 0755); err != nil {
						http.Error(w, "Failed to create directory", http.StatusInternalServerError)
						return
					}

					filename := header.Filename
					dstPath := filepath.Join(targetDir, filename)
					dst, err := os.Create(dstPath)
					if err != nil {
						http.Error(w, "Failed to create file", http.StatusInternalServerError)
						return
					}
					defer dst.Close()

					if _, err := io.Copy(dst, file); err != nil {
						http.Error(w, "Failed to save file", http.StatusInternalServerError)
						return
					}

					// Update Plan in Store
					tm.mu.Lock()
					plan, err := plannerService.Store.GetPlan(id)
					if err == nil {
						exists := false
						for _, f := range plan.Files {
							if f == filename {
								exists = true
								break
							}
						}
						if !exists {
							plan.Files = append(plan.Files, filename)
							_ = plannerService.Store.SavePlan(plan)
						}
					}
					tm.mu.Unlock()

					_ = plannerService.Store.LogInteraction(id, "System", "File Upload", fmt.Sprintf("Uploaded file: %s", filename))

					w.WriteHeader(http.StatusOK)
					w.Write([]byte(fmt.Sprintf(`{"filename": "%s"}`, filename)))
				})
				// Agent Endpoint
				r.Get("/agents", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					user, _ := iamProvider.GetUser(r)
					var groups []string
					if user != nil {
						groups = user.Groups
					}
					agents := reg.ListAgents(groups)
					json.NewEncoder(w).Encode(agents)
				})

				// MCP Endpoint
				r.Get("/mcp", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					user, _ := iamProvider.GetUser(r)
					var groups []string
					if user != nil {
						groups = user.Groups
					}
					list := reg.ListMCPServers(groups)
					json.NewEncoder(w).Encode(list)
				})

				// Skill Endpoint
				r.Get("/skills", func(w http.ResponseWriter, r *http.Request) {
					w.Header().Set("Content-Type", "application/json")
					user, _ := iamProvider.GetUser(r)
					var groups []string
					if user != nil {
						groups = user.Groups
					}
					list := reg.ListSkills(groups)
					json.NewEncoder(w).Encode(list)
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
						// Task not active in memory. Try to resume from store if plan exists.
						plan, err := plannerService.Store.GetPlan(id)
						if err == nil {
							// Plan exists! Resume it.
							tm.OutputChan <- fmt.Sprintf("[%s] Resuming inactive plan from store on input received...", id)

							// Force status update to valid running state before starting
							plan.Status = "running"
							_ = plannerService.Store.SavePlan(plan)

							// Start the task
							task = tm.StartTask(context.Background(), plan)

							// Proceed to use 'task' for input
						} else {
							// Task not in memory AND Plan not found in store

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
					}

					// Send to task (Buffered channel allows immediate return)
					select {
					case task.InputChan <- req.Input:
						w.WriteHeader(http.StatusOK)
					default:
						http.Error(w, "Task input buffer full", http.StatusServiceUnavailable)
					}
				})
			})

			// Setup IAM Routes
			r.Group(func(r chi.Router) {
				iamProvider.RegisterRoutes(r.With(middleware.Logger))
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
			fmt.Printf("Providers: Git=[%s], IAM=[%s], LLM=[%s]\n",
				cfg.Git.Provider,
				cfg.IAM.Provider,
				cfg.LLM.DefaultProvider,
			)
			fmt.Printf("Starting server on port %s...\n", port)
			// Binds to 0.0.0.0 (all interfaces)
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
			_, reg, _, _, _, _, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			// Admin has all access
			adminGroups := []string{"root", "admin"}

			for _, bb := range reg.ListBuildingBlocks(adminGroups) {
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
			for _, agent := range reg.ListAgents(adminGroups) {
				fmt.Printf("- [Agent] %s: %s\n", agent.ID, agent.Name)
			}

			for id, rule := range reg.Compliance {
				fmt.Printf("- [Compliance] %s: %s\n", id, rule.Name)
			}
		},
	}

	// runInteractiveLoop Removed

	var loginCmd = &cobra.Command{
		Use:   "login",
		Short: "Login to local provider",
		Run: func(cmd *cobra.Command, args []string) {
			_, _, _, _, _, _, iamProv, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			localProv, ok := iamProv.(*iam.LocalProvider)
			if !ok {
				fmt.Println("Error: Login only supported for 'local' IAM provider.")
				os.Exit(1)
			}

			reader := bufio.NewReader(os.Stdin)
			fmt.Print("Username: ")
			user, _ := reader.ReadString('\n')
			user = strings.TrimSpace(user)

			fmt.Print("Password: ")
			bytePassword, err := term.ReadPassword(int(os.Stdin.Fd()))
			if err != nil {
				fmt.Println("\nError reading password")
				os.Exit(1)
			}
			pass := string(bytePassword)
			fmt.Println() // Print newline after password input

			token, u, err := localProv.Login(user, pass)
			if err != nil {
				fmt.Printf("Login failed: %v\n", err)
				os.Exit(1)
			}

			if err := iam.SaveClientToken(token); err != nil {
				fmt.Printf("Failed to save session: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("Logged in as %s (Groups: %v)\n", u.Username, u.Groups)
		},
	}

	var logoutCmd = &cobra.Command{
		Use:   "logout",
		Short: "Logout from local session",
		Run: func(cmd *cobra.Command, args []string) {
			// First clean up server side if possible
			// We need setup to get the provider
			// Ignoring errors here since logout should be best-effort on local cleanup
			_, _, _, _, _, _, iamProv, _ := setup(cmd)

			if localProv, ok := iamProv.(*iam.LocalProvider); ok {
				token, _ := iam.LoadClientToken()
				if token != "" {
					_ = localProv.ReloadSessions() // Sync first just in case
					_ = localProv.Logout(token)
				}
			}

			_ = iam.ClearClientToken()
			fmt.Println("Logged out.")
		},
	}

	// TaskManager instance
	var tm *TaskManager

	var chatCmd = &cobra.Command{
		Use:   "chat",
		Short: "Start interactive chat",
		Run: func(cmd *cobra.Command, args []string) {
			cfgMgr, _, router, planner, mcpManager, buildEngine, iamProv, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			cfg := cfgMgr.Get()
			ctx := getAuthContext(context.Background(), iamProv, demo)

			if user, _ := iam.GetUserFromContext(ctx); user == nil {
				fmt.Println("You need to login first.")
				loginCmd.Run(cmd, args)

				// Force reload of sessions for the current provider instance
				if lp, ok := iamProv.(*iam.LocalProvider); ok {
					_ = lp.ReloadSessions()
				}

				// Re-acquire context after login
				ctx = getAuthContext(context.Background(), iamProv, demo)
				if user, _ := iam.GetUserFromContext(ctx); user == nil {
					fmt.Println("Login failed or cancelled.")
					os.Exit(1)
				}
			}

			// Initialize TaskManager
			tm = NewTaskManager(planner, mcpManager, buildEngine)

			fmt.Println("--- Druppie Chat (Async) ---")
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
					tm.StartTask(ctx, plan)
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
						intent, rawRouterResp, err := router.Analyze(ctx, "", input)
						if err != nil {
							fmt.Printf("[Error] Router failed: %v\n> ", err)
							continue
						}

						if intent.Action == "create_project" {
							plan, err := planner.CreatePlan(ctx, intent, "")
							if err != nil {
								fmt.Printf("[Error] Planner failed: %v\n> ", err)
								continue
							}
							_ = planner.Store.LogInteraction(plan.ID, "Router", input, rawRouterResp)

							task := tm.StartTask(ctx, plan)
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

	var autoPilot bool
	var runCmd = &cobra.Command{
		Use:     "run [prompt]",
		Aliases: []string{"plan"},
		Short:   "Run a plan for a given prompt",
		Args:    cobra.MinimumNArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			_, _, router, planner, mcpMgr, buildEngine, iamProv, err := setup(cmd)
			if err != nil {
				fmt.Printf("Error: %v\n", err)
				os.Exit(1)
			}
			ctx := getAuthContext(context.Background(), iamProv, demo)
			if autoPilot {
				ctx = context.WithValue(ctx, "mode", "cli-autopilot")
			}

			if user, _ := iam.GetUserFromContext(ctx); user == nil {
				fmt.Println("You need to login first.")
				loginCmd.Run(cmd, args)

				// Force reload of sessions for the current provider instance
				if lp, ok := iamProv.(*iam.LocalProvider); ok {
					_ = lp.ReloadSessions()
				}

				ctx = getAuthContext(context.Background(), iamProv, demo)
				if user, _ := iam.GetUserFromContext(ctx); user == nil {
					fmt.Println("Login failed or cancelled.")
					os.Exit(1)
				}
			}

			prompt := strings.Join(args, " ")

			// Load or Create Plan
			var currentPlan model.ExecutionPlan
			effectivePrompt := prompt
			isNewPlan := true

			if planID != "" {
				if p, err := planner.Store.GetPlan(planID); err == nil {
					currentPlan = p
					isNewPlan = false
					fmt.Printf("[Chat] Resuming plan: %s\n", planID)
				}
			}

			if isNewPlan {
				if planID == "" {
					// Generate a new ID if not provided
					planID = fmt.Sprintf("plan-%d", time.Now().Unix())
				}
				currentPlan = model.ExecutionPlan{
					ID: planID,
					Intent: model.Intent{
						InitialPrompt: prompt,
						Prompt:        prompt,
					},
					Status: "pending",
					Steps:  []model.Step{},
				}
			} else {
				// 0. Store User Input
				newStepID := 1
				if len(currentPlan.Steps) > 0 {
					newStepID = currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
				}
				currentPlan.Steps = append(currentPlan.Steps, model.Step{
					ID: newStepID, AgentID: "user", Action: "user_query", Status: "running", Result: prompt,
				})
				currentPlan.Status = "running"
				_ = planner.Store.SavePlan(currentPlan)

				// 1. Build Context
				history := ""
				startIdx := 0
				if len(currentPlan.Steps) > 20 {
					startIdx = len(currentPlan.Steps) - 20
				}
				for _, s := range currentPlan.Steps[startIdx:] {
					switch s.Action {
					case "user_query":
						history += fmt.Sprintf("User: %s\n", s.Result)
					case "general_chat":
						history += fmt.Sprintf("AI: %s\n", s.Result)
					}
				}
				effectivePrompt = fmt.Sprintf("History:\n%s\nRequest: %s", history, prompt)
				//fmt.Printf("[DEBUG] Constructed History Steps: %d\n", len(currentPlan.Steps))
			}

			// Initialize TaskManager early to unify output
			tm := NewTaskManager(planner, mcpMgr, buildEngine)

			intent, rawRouterResp, err := router.Analyze(ctx, planID, effectivePrompt)
			if err != nil {
				fmt.Printf("Router failed: %v\n", err)
				os.Exit(1)
			}

			var responseOutput string

			if intent.Action == "create_project" || intent.Action == "orchestrate_complex" || intent.Action == "update_project" {
				// Update intent for planner
				intent.InitialPrompt = effectivePrompt
				intent.Prompt = effectivePrompt

				var err error
				currentPlan, err = planner.CreatePlan(ctx, intent, currentPlan.ID)
				if err != nil {
					fmt.Printf("[%s] Planner failed: %v\n", currentPlan.ID, err)
					os.Exit(1)
				}
				// Log router step to plan log
				_ = planner.Store.LogInteraction(currentPlan.ID, "Router", prompt, rawRouterResp)
				// Explicitly save the plan to disk so TaskManager can find it
				if err := planner.Store.SavePlan(currentPlan); err != nil {
					fmt.Printf("[%s] Failed to save plan: %v\n", currentPlan.ID, err)
					os.Exit(1)
				}
			} else {
				// General Chat or Query Registry - No Plan
				_ = planner.Store.LogInteraction(currentPlan.ID, "Router", effectivePrompt, rawRouterResp)

				answer := intent.Answer
				if answer == "" {
					answer = rawRouterResp
				}

				// Append AI Step
				newStepID := 1
				if len(currentPlan.Steps) > 0 {
					newStepID = currentPlan.Steps[len(currentPlan.Steps)-1].ID + 1
				}
				currentPlan.Steps = append(currentPlan.Steps, model.Step{
					ID: newStepID, AgentID: "router", Action: "general_chat", Status: "completed", Result: answer,
				})
				currentPlan.Status = "completed"
				_ = planner.Store.SavePlan(currentPlan)

				if intent.Answer != "" {
					responseOutput = fmt.Sprintf("[%s]\n ** AI Response:**\n%s", currentPlan.ID, intent.Answer)
				} else {
					responseOutput = fmt.Sprintf("[%s] Intent was '%s', which doesn't trigger a planner in this CLI.\n", currentPlan.ID, intent.Action)
				}
			}

			// Initialize TaskManager for execution
			task := tm.StartTask(ctx, currentPlan)
			fmt.Printf("[%s] Started Plan execution...\n", currentPlan.ID)

			// Inject the postponed AI response if exists
			if responseOutput != "" {
				tm.OutputChan <- responseOutput
			}

			// Initialize Logging to File
			logDir := filepath.Join(".druppie", "plans", currentPlan.ID, "logs")
			if err := os.MkdirAll(logDir, 0755); err == nil {
				logPath := filepath.Join(logDir, "execution.log")
				if f, err := os.OpenFile(logPath, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644); err == nil {
					defer f.Close()
					// Wrap output handling to write to file
					// We can't easily replace tm.OutputChan logic, but we can intercept the read loop below.

					// Execution Loop with File Logging
					done := false
					for !done {
						prefix := fmt.Sprintf("[%s]", currentPlan.ID)
						select {
						case log := <-tm.OutputChan:
							fmt.Println(log)
							if _, err := f.WriteString(log + "\n"); err != nil {
								fmt.Printf("Error writing to log: %v\n", err)
							}
						case <-time.After(500 * time.Millisecond):
							// Check status periodically
							// Note: Direct access is slightly racy but acceptable for this CLI tool
							switch task.Status {
							case TaskStatusWaitingInput:
								// Check if the output suggests an error requiring intervention
								// Since we can't easily see the last message here without state, we'll assume
								// if we are waiting for input, and it's an error-retry loop, auto-accept is dangerous.
								// However, for simplicity: If we hit this more than X times, or if the user wants to stop on error?
								// Let's change behavior: If it's a "Retry/Stop" prompt, we should probably STOP in auto-pilot to avoid loops.
								if autoPilot {
									prefix = fmt.Sprintf("[Auto-%s]", currentPlan.ID)
								}
								fmt.Printf("%s Input required. Checking for error state...\n", prefix)
								time.Sleep(1 * time.Second)

								// We default to /accept usually, BUT if the step failed and is asking for /retry, /accept might re-run it blindly?
								// Actually /accept usually means "use defaults" or "retry" depending on context.
								// Let's safety break: IF the plan status is technically "running" but we are paused.
								// Ideally we send "/stop" if we are in a loop.
								// For now, let's keep /accept but add a max-loop check or just exit if it fails repeatedly?
								// User Request: "fix auto_complete within plan mode that it exits on an error"
								// So if we see "Paused/Failed", we should stop.

								// We don't have easy access to the exact prompt text here (it was in OutputChan).
								// But we can check if task.Status is actually Error? No, it's WaitingInput.

								// Hack: We send /stop to be safe if we want it to exit on error.
								// But that stops valid questions too.
								// Better: rely on the user seeing the log.
								// BUT the user specifically asked to exit on error.
								// So let's send /stop which will likely abort the plan.
								// Wait, 'ask_questions' also triggers this. We want to /accept those.
								// We need to differentiate.
								// Since we can't contextually differentiate easily here without architectural change,
								// I will change it to /stop which is safer for "Auto-Pilot" than infinite loops,
								// OR we assume that if it's a "Failed" step, the output log showed it.

								// IMPROVED LOGIC: Exit monitor loop on approval/input request
								// This allows the user to use the UI or other means to approve without killing the plan.
								fmt.Printf("%s Plan is paused waiting for user input or approval.\n", prefix)
								done = true
							case TaskStatusCompleted:
								if autoPilot {
									prefix = fmt.Sprintf("[Auto-%s]", currentPlan.ID)
								}
								fmt.Printf("%s Plan execution completed successfully.\n", prefix)
								done = true
							case TaskStatusError:
								if autoPilot {
									prefix = fmt.Sprintf("[Auto-%s]", currentPlan.ID)
								}
								fmt.Printf("%s Plan execution failed.\n", prefix)
								done = true
							}
						}
					}
				} else {
					fmt.Printf("Failed to open execution log: %v\n", err)
				}
			} else {
				fmt.Printf("Failed to create log dir: %v\n", err)
			}

			// Fetch final state
			finalPlan, _ := planner.Store.GetPlan(currentPlan.ID)
			currentPlan = finalPlan
			// validJSON, _ := json.MarshalIndent(currentPlan, "", "  ")
			// fmt.Println(string(validJSON))
			fmt.Println("") // Add one more empty line on exit
		},
	}

	var resumeCmd = &cobra.Command{
		Use:   "resume [plan-id]",
		Short: "Resume a specific plan",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			_, _, _, planner, mcpMgr, buildEngine, iamProv, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup failed: %v\n", err)
				os.Exit(1)
			}

			ctx := getAuthContext(context.Background(), iamProv, demo)
			if user, _ := iam.GetUserFromContext(ctx); user == nil {
				fmt.Println("You need to login first.")
				loginCmd.Run(cmd, args)
				if lp, ok := iamProv.(*iam.LocalProvider); ok {
					_ = lp.ReloadSessions()
				}
				ctx = getAuthContext(context.Background(), iamProv, demo)
				if user, _ := iam.GetUserFromContext(ctx); user == nil {
					fmt.Println("Login failed or cancelled.")
					os.Exit(1)
				}
			}

			planID := args[0]
			if !strings.HasPrefix(planID, "plan-") {
				planID = "plan-" + planID
			}

			plan, err := planner.Store.GetPlan(planID)
			if err != nil {
				fmt.Printf("Plan %s not found\n", planID)
				os.Exit(1)
			}

			plan.Status = "running"
			_ = planner.Store.SavePlan(plan)

			tm := NewTaskManager(planner, mcpMgr, buildEngine)
			task := tm.StartTask(ctx, plan)
			fmt.Printf("Resuming plan %s...\n", plan.ID)

			done := false
			for !done {
				select {
				case log := <-tm.OutputChan:
					fmt.Println(log)
				case <-time.After(500 * time.Millisecond):
					if task.Status == TaskStatusCompleted || task.Status == TaskStatusError || task.Status == TaskStatusCancelled {
						fmt.Printf("Plan finished: %s\n", task.Status)
						done = true
					}
					if task.Status == TaskStatusWaitingInput {
						fmt.Println("Waiting for input... (Interaction in CLI resume not fully supported yet, use chat/UI)")
						// Simple sleep to avoid busy loop spam
						time.Sleep(2 * time.Second)
					}
				}
			}
		},
	}

	// MCP CLI Commands
	var mcpCmd = &cobra.Command{
		Use:   "mcp",
		Short: "Manage MCP Server integrations",
	}

	var mcpListCmd = &cobra.Command{
		Use:   "list",
		Short: "List configured MCP servers",
		Run: func(cmd *cobra.Command, args []string) {
			_, _, _, _, mcpMgr, _, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup failed: %v\n", err)
				os.Exit(1)
			}
			servers := mcpMgr.GetServers()
			if len(servers) == 0 {
				fmt.Println("No MCP servers configured.")
				return
			}
			fmt.Println("Configured MCP Servers:")
			for _, s := range servers {
				typeStr := ""
				if s.Type != "" {
					typeStr = fmt.Sprintf(" [%s]", s.Type)
				}
				fmt.Printf("- %s (%s)%s\n", s.Name, s.URL, typeStr)
			}
		},
	}

	var mcpAddCmd = &cobra.Command{
		Use:   "add [name] [url]",
		Short: "Add a new MCP server",
		Args:  cobra.ExactArgs(2),
		Run: func(cmd *cobra.Command, args []string) {
			_, _, _, _, mcpMgr, _, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup failed: %v\n", err)
				os.Exit(1)
			}
			name := args[0]
			url := args[1]
			ctx := context.Background()
			fmt.Printf("Connecting to %s (%s)...\n", name, url)
			if err := mcpMgr.AddServer(ctx, name, url); err != nil {
				fmt.Printf("Error adding server: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("Server '%s' added successfully.\n", name)
		},
	}

	var mcpDelCmd = &cobra.Command{
		Use:   "del [name]",
		Short: "Remove an MCP server",
		Args:  cobra.ExactArgs(1),
		Run: func(cmd *cobra.Command, args []string) {
			_, _, _, _, mcpMgr, _, _, err := setup(cmd)
			if err != nil {
				fmt.Printf("Startup failed: %v\n", err)
				os.Exit(1)
			}
			name := args[0]
			ctx := context.Background()
			if err := mcpMgr.RemoveServer(ctx, name); err != nil {
				fmt.Printf("Error removing server: %v\n", err)
				os.Exit(1)
			}
			fmt.Printf("Server '%s' removed.\n", name)
		},
	}

	mcpCmd.AddCommand(mcpListCmd)
	mcpCmd.AddCommand(mcpAddCmd)
	mcpCmd.AddCommand(mcpDelCmd)

	rootCmd.PersistentFlags().StringVar(&planID, "plan-id", "", "ID of an existing plan to resume or manage")
	rootCmd.PersistentFlags().StringVar(&llmProviderOverride, "llm-provider", "", "Override default LLM provider")
	rootCmd.PersistentFlags().StringVar(&buildProviderOverride, "build-provider", "", "Override default Build provider")
	rootCmd.PersistentFlags().BoolVar(&debug, "debug", true, "Enable debug mode (print raw LLM responses)")
	rootCmd.PersistentFlags().BoolVar(&demo, "demo", false, "Enable demo mode (full admin access, no login)")

	rootCmd.AddCommand(registryCmd)
	rootCmd.AddCommand(loginCmd)
	rootCmd.AddCommand(logoutCmd)
	rootCmd.AddCommand(chatCmd)
	runCmd.Flags().BoolVar(&autoPilot, "auto-pilot", false, "Enable auto-pilot (auto-approval) mode")
	rootCmd.AddCommand(runCmd)
	rootCmd.AddCommand(resumeCmd)
	rootCmd.AddCommand(mcpCmd)
	rootCmd.AddCommand(serveCmd)

	// Default to server mode
	rootCmd.Run = serveCmd.Run

	if err := rootCmd.Execute(); err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
}
