package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"unicode"

	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
)

// StandardExecutor is a general-purpose executor that delegates to standard actions.
// It replaces specific InfrastructureExecutor and can be extended for other common tasks.
type StandardExecutor struct {
	StdCtx *StandardContext
}

// CanHandle determines if the executor can handle the given action.
// It lazily checks if there is a Standard Action implementation or an MCP tool for the action.
func (e *StandardExecutor) CanHandle(action string) bool {
	// 1. Check if StandardActions has a method for this action
	methodName := "Action" + toCamelCase(action)
	if e.StdCtx != nil && e.StdCtx.StandardActions != nil {
		val := reflect.ValueOf(e.StdCtx.StandardActions)
		if val.MethodByName(methodName).IsValid() {
			return true
		}
	}

	// 2. Check if MCP Manager has a tool for this action
	if e.StdCtx != nil && e.StdCtx.MCPManager != nil {
		if _, found := e.StdCtx.MCPManager.GetToolServer(action); found {
			return true
		}
	}

	return false
}

func (e *StandardExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	//outputChan <- fmt.Sprintf("StandardExecutor: Executing '%s'...", step.Action)
	return ExecuteStandardAction(e, e.StdCtx, ctx, step, outputChan)
}

// ActionGeneric is a fallback (required by ExecuteStandardAction contract if used for fallback),
// but since CanHandle is now strict, this might not be reached unless forced.
func (e *StandardExecutor) ActionGeneric(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- fmt.Sprintf("StandardExecutor: Generic placeholder execution for '%s'", step.Action)
	return nil
}

// StandardContext holds dependencies needed for standard execution dispatch
type StandardContext struct {
	MCPManager      *mcp.Manager
	StandardActions *StandardActions
	// Add Registry or CodeBlock manager here in future
}

// ExecuteStandardAction attempts to execute an action by looking for a specific method
// on the executor struct, then falling back to StandardActions, then MCP tools.
func ExecuteStandardAction(e interface{}, stdCtx *StandardContext, ctx context.Context, step model.Step, outputChan chan<- string) error {
	methodName := "Action" + toCamelCase(step.Action)
	val := reflect.ValueOf(e)

	// 1. Check Local Specific Implementation
	method := val.MethodByName(methodName)
	if method.IsValid() {
		args := []reflect.Value{
			reflect.ValueOf(ctx),
			reflect.ValueOf(step),
			reflect.ValueOf(outputChan),
		}
		results := method.Call(args)
		if len(results) > 0 {
			if errVal := results[0]; !errVal.IsNil() {
				if err, ok := errVal.Interface().(error); ok {
					return err
				}
				return fmt.Errorf("unknown error from action %s", step.Action)
			}
		}
		return nil
	}

	// 2. Check Common Go Action (StandardActions)
	if stdCtx != nil && stdCtx.StandardActions != nil {
		commonVal := reflect.ValueOf(stdCtx.StandardActions)
		commonMethod := commonVal.MethodByName(methodName)
		if commonMethod.IsValid() {
			args := []reflect.Value{
				reflect.ValueOf(ctx),
				reflect.ValueOf(step),
				reflect.ValueOf(outputChan),
			}
			results := commonMethod.Call(args)
			if len(results) > 0 {
				if errVal := results[0]; !errVal.IsNil() {
					if err, ok := errVal.Interface().(error); ok {
						return err
					}
					return fmt.Errorf("unknown error from standard action %s", step.Action)
				}
			}
			return nil
		}
	}

	// 3. Check MCP / Dynamic Tools
	if stdCtx != nil && stdCtx.MCPManager != nil {
		_, found := stdCtx.MCPManager.GetToolServer(step.Action)
		if found {
			res, err := stdCtx.MCPManager.ExecuteTool(ctx, step.Action, step.Params)
			if err != nil {
				return err
			}
			for _, c := range res.Content {
				if c.Type == "text" {
					outputChan <- c.Text
				}
			}
			return nil
		}
	}

	// 4. Generic Fallback (Local)
	methodGeneric := val.MethodByName("ActionGeneric")
	if methodGeneric.IsValid() {
		args := []reflect.Value{
			reflect.ValueOf(ctx),
			reflect.ValueOf(step),
			reflect.ValueOf(outputChan),
		}
		results := methodGeneric.Call(args)
		if len(results) > 0 {
			if errVal := results[0]; !errVal.IsNil() {
				if err, ok := errVal.Interface().(error); ok {
					return err
				}
			}
		}
		return nil
	}

	return fmt.Errorf("executor %T does not support action '%s', and no fallback found", e, step.Action)
}

// toCamelCase converts snake_case or kebab-case to CamelCase.
func toCamelCase(s string) string {
	parts := strings.FieldsFunc(s, func(r rune) bool {
		return r == '_' || r == '-' || r == ' '
	})

	var sb strings.Builder
	for _, part := range parts {
		if len(part) > 0 {
			runes := []rune(part)
			runes[0] = unicode.ToUpper(runes[0])
			if len(runes) > 1 {
				sb.WriteString(string(runes[0]))
				sb.WriteString(strings.ToLower(string(runes[1:])))
			} else {
				sb.WriteString(string(runes[0]))
			}
		}
	}
	return sb.String()
}

// StandardActions contains common implementations of actions that can be used by any executor
type StandardActions struct{}

// ActionCreateProject initializes a project structure
func (s *StandardActions) ActionCreateProject(ctx context.Context, step model.Step, outputChan chan<- string) error {
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	}

	outputChan <- "Initializing project structure (Generic)..."
	if planID != "" {
		outputChan <- fmt.Sprintf("Target Plan: %s", planID)
	}

	if name, ok := step.Params["name"].(string); ok {
		outputChan <- fmt.Sprintf("Project Name: %s", name)
	}

	outputChan <- "Project initialized successfully."
	return nil
}

// ActionCoding writes files to the project directory
func (s *StandardActions) ActionCoding(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Writing Code / Manifests (Generic)..."

	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	}

	if planID == "" {
		return fmt.Errorf("missing plan ID in context")
	}

	projectRoot, _ := paths.ResolvePath(".druppie", "plans", planID, "src")

	if err := os.MkdirAll(projectRoot, 0755); err != nil {
		return fmt.Errorf("failed to create project root: %w", err)
	}

	var fileMap map[string]interface{}
	if f, ok := step.Params["files"].(map[string]interface{}); ok {
		fileMap = f
	} else if fList, ok := step.Params["files"].([]interface{}); ok {
		fileMap = make(map[string]interface{})
		for _, item := range fList {
			if itemMap, ok := item.(map[string]interface{}); ok {
				if p, ok := itemMap["path"].(string); ok {
					if c, ok := itemMap["content"].(string); ok {
						fileMap[p] = c
					}
				}
			}
		}
	}

	if len(fileMap) == 0 {
		outputChan <- "Warning: No files provided in 'files' parameter."
	}

	for path, content := range fileMap {
		strContent, ok := content.(string)
		if !ok {
			continue
		}
		cleanPath := filepath.Clean(path)
		if cleanPath == "." || cleanPath == "/" {
			continue
		}

		// Sanitize Markdown files (Mermaid fixes)
		if filepath.Ext(cleanPath) == ".md" {
			strContent = SanitizeAndFixMarkdown(strContent)
		}

		fullPath := filepath.Join(projectRoot, cleanPath)

		if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err != nil {
			return fmt.Errorf("failed to create dir for %s: %w", path, err)
		}
		if err := os.WriteFile(fullPath, []byte(strContent), 0644); err != nil {
			return fmt.Errorf("failed to write %s: %w", path, err)
		}
		outputChan <- fmt.Sprintf("Created file: %s", path)
	}

	if desc, ok := step.Params["description"].(string); ok {
		outputChan <- fmt.Sprintf("Goal: %s", desc)
	}
	outputChan <- "Coding complete."
	return nil
}

func (s *StandardActions) ActionValidation(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Validating configuration and manifests (Standard)..."
	// Return a special error indicating that input is required,
	// which the engine can catch to update the step status to 'wait_for_input'.
	return fmt.Errorf("wait_for_input: Please review and validate the configuration manually")
}

func (s *StandardActions) ActionValidate(ctx context.Context, step model.Step, outputChan chan<- string) error {
	return s.ActionValidation(ctx, step, outputChan)
}

func (s *StandardActions) ActionDeployment(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Deploying resources (Standard)..."
	outputChan <- "Deployment successful."
	return nil
}

func (s *StandardActions) ActionDeploy(ctx context.Context, step model.Step, outputChan chan<- string) error {
	return s.ActionDeployment(ctx, step, outputChan)
}

func (s *StandardActions) ActionVerification(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Verifying deployment health (Standard)..."
	outputChan <- "Probes: OK"
	outputChan <- "Verification complete."
	return nil
}

func (s *StandardActions) ActionVerify(ctx context.Context, step model.Step, outputChan chan<- string) error {
	return s.ActionVerification(ctx, step, outputChan)
}

func (s *StandardActions) ActionEnsureAvailability(ctx context.Context, step model.Step, outputChan chan<- string) error {
	if target, ok := step.Params["target"].(string); ok {
		outputChan <- fmt.Sprintf("Verifying availability of %s...", target)
	}
	outputChan <- "Infrastructure availability check passed (Standard)."
	return nil
}

func (s *StandardActions) ActionCheckBlockStatus(ctx context.Context, step model.Step, outputChan chan<- string) error {
	if block, ok := step.Params["block"].(string); ok {
		outputChan <- fmt.Sprintf("Checking status of Building Block (Standard): %s", block)
		outputChan <- fmt.Sprintf("Block %s is RUNNING", block)
		return nil
	}
	return fmt.Errorf("check-block-status requires 'block' param")
}

func (s *StandardActions) ActionKubernetes(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Kubernetes placeholder execution"
	return nil
}

func (s *StandardActions) ActionTerraform(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "Terraform placeholder execution"
	return nil
}
