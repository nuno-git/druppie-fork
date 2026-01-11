package executor

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
	"gopkg.in/yaml.v3"
)

// PluginExecutor handles plugin testing and promotion
type PluginExecutor struct {
	MCPManager *mcp.Manager
}

func (e *PluginExecutor) CanHandle(action string) bool {
	return action == "test_plugin" || action == "promote_plugin" || action == "execute_plugin"
}

func (e *PluginExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	}

	if planID == "" {
		return fmt.Errorf("missing plan ID in context")
	}

	switch step.Action {
	case "test_plugin":
		return e.testPlugin(ctx, step, planID, outputChan)
	case "promote_plugin":
		return e.promotePlugin(ctx, step, planID, outputChan)
	case "execute_plugin":
		return e.executePlugin(ctx, step, planID, outputChan)
	default:
		return fmt.Errorf("unsupported action: %s", step.Action)
	}
}

func (e *PluginExecutor) executePlugin(ctx context.Context, step model.Step, planID string, outputChan chan<- string) error {
	inputFileRaw, _ := step.Params["input_file"].(string)
	pluginPathRaw, _ := step.Params["plugin_path"].(string)
	pluginNameRaw, _ := step.Params["plugin_name"].(string)

	// Smart Redirect: If plugin_name matches a running MCP Server, use MCP execution
	if pluginNameRaw != "" && e.MCPManager != nil {
		// Check if server exists (using internal map check via GetServers or similar?
		// Manager doesn't expose CheckServer directly, but GetToolServer is for tools.
		// However, we can blindly try to resolve if we have a function_name)

		toolName, _ := step.Params["function_name"].(string)

		// Extract args from various aliases
		var args map[string]interface{}
		if a, ok := step.Params["args"].(map[string]interface{}); ok {
			args = a
		} else if a, ok := step.Params["input"].(map[string]interface{}); ok {
			args = a
		} else if a, ok := step.Params["arguments"].(map[string]interface{}); ok {
			args = a
		} else if a, ok := step.Params["tool_input"].(map[string]interface{}); ok {
			args = a
		}

		if toolName != "" {
			// This looks like an MCP call disguised as execute_plugin
			outputChan <- fmt.Sprintf("[plugin-executor] Redirecting '%s' to MCP Executor...", pluginNameRaw)

			// Try execute
			res, err := e.MCPManager.ExecuteTool(ctx, toolName, args)
			if err != nil {
				return fmt.Errorf("redirected MCP execution failed: %w", err)
			}
			for _, c := range res.Content {
				if c.Type == "text" {
					outputChan <- c.Text
				}
			}
			return nil
		}
	}

	outputChan <- fmt.Sprintf("[plugin-executor] Analyzing execution request: plugin=%s input=%s", pluginPathRaw, inputFileRaw)

	// Resolve src dir
	srcDir, err := paths.ResolvePath(".druppie", "plans", planID, "src")
	if err != nil {
		return fmt.Errorf("failed to resolve src dir: %w", err)
	}

	// Resolve input file path
	// Handle variable substitution if present
	inputFileRaw = strings.ReplaceAll(inputFileRaw, "${PLAN_ID}", planID)

	var inputPath string
	if filepath.IsAbs(inputFileRaw) {
		inputPath = inputFileRaw
	} else if strings.HasPrefix(inputFileRaw, ".druppie") {
		// Relative from project root
		root, _ := paths.FindProjectRoot()
		inputPath = filepath.Join(root, inputFileRaw)
	} else {
		// Relative from src
		inputPath = filepath.Join(srcDir, inputFileRaw)
	}

	// Resolve plugin entry point
	// Often comes as "${PLAN_ID}/src/index.js" or similar
	pluginPathClean := strings.ReplaceAll(pluginPathRaw, "${PLAN_ID}", planID)
	// If it contains /src/, simplify to filename if we are running from srcDir
	if strings.Contains(pluginPathClean, "/src/") {
		parts := strings.Split(pluginPathClean, "/src/")
		if len(parts) > 1 {
			pluginPathClean = parts[1] // just the filename e.g. "index.js"
		}
	}
	entryPoint := filepath.Join(srcDir, pluginPathClean)

	outputChan <- fmt.Sprintf("[plugin-executor] Executing %s < %s", entryPoint, inputPath)

	// Check files
	if _, err := os.Stat(entryPoint); os.IsNotExist(err) {
		return fmt.Errorf("plugin entry point not found: %s", entryPoint)
	}
	if _, err := os.Stat(inputPath); os.IsNotExist(err) {
		return fmt.Errorf("input file not found: %s", inputPath)
	}

	cmd := exec.CommandContext(ctx, "node", entryPoint)
	cmd.Dir = srcDir

	inFile, err := os.Open(inputPath)
	if err != nil {
		return fmt.Errorf("failed to open input file: %w", err)
	}
	defer inFile.Close()
	cmd.Stdin = inFile

	// Capture output
	// Since json-rpc output might optionally be used later, we log it
	out, err := cmd.CombinedOutput()
	outputChan <- string(out)

	if err != nil {
		return fmt.Errorf("plugin execution returned error: %w", err)
	}

	outputChan <- "[plugin-executor] ✅ Execution successful"
	return nil
}

func (e *PluginExecutor) testPlugin(ctx context.Context, step model.Step, planID string, outputChan chan<- string) error {
	buildID, ok := step.Params["build_id"].(string)
	if !ok || buildID == "" {
		return fmt.Errorf("missing required parameter 'build_id'")
	}

	// Locate build directory
	buildDir, _ := paths.ResolvePath(".druppie", "plans", planID, "builds", buildID)
	if _, err := os.Stat(buildDir); os.IsNotExist(err) {
		return fmt.Errorf("build directory not found: %s", buildDir)
	}

	outputChan <- fmt.Sprintf("[plugin-converter] Testing plugin from build: %s", buildID)

	// Check if package.json exists (Node.js plugin)
	pkgPath := filepath.Join(buildDir, "package.json")
	if _, err := os.Stat(pkgPath); os.IsNotExist(err) {
		return fmt.Errorf("package.json not found in build - plugins must be Node.js based")
	}

	// Validate plugin structure
	requiredFiles := []string{"package.json"}
	for _, file := range requiredFiles {
		path := filepath.Join(buildDir, file)
		if _, err := os.Stat(path); os.IsNotExist(err) {
			return fmt.Errorf("required file missing: %s", file)
		}
	}

	outputChan <- "[plugin-converter] ✅ Plugin structure validated"

	// Parse package.json to find entry point
	pkgData, err := os.ReadFile(pkgPath)
	if err != nil {
		return fmt.Errorf("failed to read package.json: %w", err)
	}

	var pkg struct {
		Bin map[string]string `json:"bin"`
	}
	if err := json.Unmarshal(pkgData, &pkg); err != nil {
		return fmt.Errorf("failed to parse package.json: %w", err)
	}

	if len(pkg.Bin) == 0 {
		return fmt.Errorf("package.json must have a 'bin' entry for MCP server")
	}

	// Get the first bin entry
	var entryPoint string
	for _, v := range pkg.Bin {
		entryPoint = v
		break
	}

	entryPointPath := filepath.Join(buildDir, entryPoint)
	if _, err := os.Stat(entryPointPath); os.IsNotExist(err) {
		return fmt.Errorf("entry point not found: %s", entryPoint)
	}

	outputChan <- fmt.Sprintf("[plugin-converter] Entry point: %s", entryPoint)

	// Install dependencies if node_modules doesn't exist
	nodeModulesPath := filepath.Join(buildDir, "node_modules")
	if _, err := os.Stat(nodeModulesPath); os.IsNotExist(err) {
		outputChan <- "[plugin-converter] Installing dependencies..."
		installCmd := exec.CommandContext(ctx, "npm", "install", "--production")
		installCmd.Dir = buildDir
		if output, err := installCmd.CombinedOutput(); err != nil {
			return fmt.Errorf("npm install failed: %w\nOutput: %s", err, string(output))
		}
		outputChan <- "[plugin-converter] ✅ Dependencies installed"
	}

	// Get test cases
	testCases, _ := step.Params["test_cases"].([]interface{})
	if len(testCases) == 0 {
		outputChan <- "[plugin-converter] ⚠️  No test cases provided - skipping functional tests"
		return nil
	}

	outputChan <- fmt.Sprintf("[plugin-converter] Running %d test case(s)...", len(testCases))

	// Start MCP server
	serverCmd := exec.CommandContext(ctx, "node", entryPointPath)
	serverCmd.Dir = buildDir

	stdin, err := serverCmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdin pipe: %w", err)
	}

	stdout, err := serverCmd.StdoutPipe()
	if err != nil {
		return fmt.Errorf("failed to create stdout pipe: %w", err)
	}

	stderr, err := serverCmd.StderrPipe()
	if err != nil {
		return fmt.Errorf("failed to create stderr pipe: %w", err)
	}

	if err := serverCmd.Start(); err != nil {
		return fmt.Errorf("failed to start MCP server: %w", err)
	}

	defer func() {
		stdin.Close()
		serverCmd.Process.Kill()
		serverCmd.Wait()
	}()

	// Monitor stderr for errors
	go func() {
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			line := scanner.Text()
			if line != "" {
				outputChan <- fmt.Sprintf("[plugin-server] %s", line)
			}
		}
	}()

	outputChan <- "[plugin-converter] ✅ MCP server started"

	// Initialize MCP connection
	initRequest := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      1,
		"method":  "initialize",
		"params": map[string]interface{}{
			"protocolVersion": "2024-11-05",
			"capabilities":    map[string]interface{}{},
			"clientInfo": map[string]interface{}{
				"name":    "druppie-test",
				"version": "1.0.0",
			},
		},
	}

	if err := json.NewEncoder(stdin).Encode(initRequest); err != nil {
		return fmt.Errorf("failed to send initialize request: %w", err)
	}

	// Read initialize response
	decoder := json.NewDecoder(stdout)
	var initResponse map[string]interface{}
	if err := decoder.Decode(&initResponse); err != nil {
		return fmt.Errorf("failed to read initialize response: %w", err)
	}

	outputChan <- "[plugin-converter] ✅ MCP connection initialized"

	// Send initialized notification
	initializedNotif := map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  "notifications/initialized",
	}
	if err := json.NewEncoder(stdin).Encode(initializedNotif); err != nil {
		return fmt.Errorf("failed to send initialized notification: %w", err)
	}

	// Execute test cases
	passedTests := 0
	failedTests := 0

	for i, tc := range testCases {
		testCase, ok := tc.(map[string]interface{})
		if !ok {
			outputChan <- fmt.Sprintf("[test-%d] ❌ Invalid test case format", i+1)
			failedTests++
			continue
		}

		toolName, _ := testCase["tool"].(string)
		input, _ := testCase["input"].(map[string]interface{})
		expected, _ := testCase["expected"]

		if toolName == "" {
			outputChan <- fmt.Sprintf("[test-%d] ❌ Missing 'tool' in test case", i+1)
			failedTests++
			continue
		}

		outputChan <- fmt.Sprintf("[test-%d] Testing tool: %s", i+1, toolName)
		inputJSON, _ := json.Marshal(input)
		outputChan <- fmt.Sprintf("[test-%d] Input: %s", i+1, string(inputJSON))

		// Call tool
		callRequest := map[string]interface{}{
			"jsonrpc": "2.0",
			"id":      i + 2,
			"method":  "tools/call",
			"params": map[string]interface{}{
				"name":      toolName,
				"arguments": input,
			},
		}

		if err := json.NewEncoder(stdin).Encode(callRequest); err != nil {
			outputChan <- fmt.Sprintf("[test-%d] ❌ Failed to send request: %v", i+1, err)
			failedTests++
			continue
		}

		// Read response
		var response map[string]interface{}
		if err := decoder.Decode(&response); err != nil {
			outputChan <- fmt.Sprintf("[test-%d] ❌ Failed to read response: %v", i+1, err)
			failedTests++
			continue
		}

		// Check for errors
		if errObj, ok := response["error"]; ok {
			outputChan <- fmt.Sprintf("[test-%d] ❌ Tool returned error: %v", i+1, errObj)
			failedTests++
			continue
		}

		// Validate response
		result, ok := response["result"]
		if !ok {
			outputChan <- fmt.Sprintf("[test-%d] ❌ No result in response", i+1)
			failedTests++
			continue
		}

		// If expected is provided, validate it
		if expected != nil {
			resultJSON, _ := json.Marshal(result)
			expectedJSON, _ := json.Marshal(expected)

			if string(resultJSON) == string(expectedJSON) {
				outputChan <- fmt.Sprintf("[test-%d] ✅ PASS", i+1)
				passedTests++
			} else {
				outputChan <- fmt.Sprintf("[test-%d] ❌ FAIL - Expected: %s, Got: %s", i+1, string(expectedJSON), string(resultJSON))
				failedTests++
			}
		} else {
			// No expected value, just check that we got a result
			outputChan <- fmt.Sprintf("[test-%d] ✅ PASS (result received)", i+1)
			passedTests++
		}
	}

	outputChan <- fmt.Sprintf("[plugin-converter] Test Results: %d passed, %d failed", passedTests, failedTests)

	if failedTests > 0 {
		return fmt.Errorf("plugin tests failed: %d/%d tests failed", failedTests, len(testCases))
	}

	outputChan <- "[plugin-converter] ✅ All tests passed!"

	return nil
}

func (e *PluginExecutor) promotePlugin(ctx context.Context, step model.Step, planID string, outputChan chan<- string) error {
	buildID, ok := step.Params["build_id"].(string)
	if !ok || buildID == "" {
		return fmt.Errorf("missing required parameter 'build_id'")
	}

	pluginName, ok := step.Params["plugin_name"].(string)
	if !ok || pluginName == "" {
		return fmt.Errorf("missing required parameter 'plugin_name'")
	}

	description, _ := step.Params["description"].(string)
	if description == "" {
		description = fmt.Sprintf("Plugin converted from build %s", buildID)
	}

	// Sanitize plugin name
	pluginName = strings.ToLower(pluginName)
	pluginName = strings.ReplaceAll(pluginName, " ", "-")
	pluginName = strings.ReplaceAll(pluginName, "_", "-")

	outputChan <- fmt.Sprintf("[plugin-converter] Promoting plugin: %s", pluginName)

	// 1. Locate build directory
	buildDir, _ := paths.ResolvePath(".druppie", "plans", planID, "builds", buildID)
	if _, err := os.Stat(buildDir); os.IsNotExist(err) {
		return fmt.Errorf("build directory not found: %s", buildDir)
	}

	// 2. Create plugin directory in .druppie/plugins
	pluginDir, _ := paths.ResolvePath(".druppie", "plugins", pluginName)
	if err := os.MkdirAll(pluginDir, 0755); err != nil {
		return fmt.Errorf("failed to create plugin directory: %w", err)
	}

	outputChan <- fmt.Sprintf("[plugin-converter] Created plugin directory: %s", pluginDir)

	// 3. Copy build artifacts to plugin directory
	if err := copyDir(buildDir, pluginDir); err != nil {
		return fmt.Errorf("failed to copy plugin files: %w", err)
	}

	outputChan <- "[plugin-converter] Copied plugin files"

	// 4. Handle MCP server definition
	authGroups, _ := step.Params["auth_groups"].([]interface{})
	authGroupsStr := []string{}
	for _, g := range authGroups {
		if gs, ok := g.(string); ok {
			authGroupsStr = append(authGroupsStr, gs)
		}
	}

	// Check if mcp.md exists in the build directory
	buildMcpPath := filepath.Join(buildDir, "mcp.md")
	var mcpContent string

	if _, err := os.Stat(buildMcpPath); err == nil {
		// Use existing mcp.md from build
		outputChan <- "[plugin-converter] Found mcp.md in build, using it"
		mcpBytes, err := os.ReadFile(buildMcpPath)
		if err != nil {
			return fmt.Errorf("failed to read mcp.md from build: %w", err)
		}
		mcpContent = string(mcpBytes)

		// Update the path in args to point to the promoted location
		mcpContent = strings.ReplaceAll(mcpContent, "/builds/", "/plugins/")
		mcpContent = strings.ReplaceAll(mcpContent, fmt.Sprintf("/plans/%s/", planID), "/plugins/")
	} else {
		// Generate default MCP definition
		outputChan <- "[plugin-converter] No mcp.md found, generating default"
		mcpContent = createMCPDefinition(pluginName, description, authGroupsStr)
	}

	// Write MCP definition to plugin directory for runtime loading
	mcpPluginPath := filepath.Join(pluginDir, "mcp.md")
	if err := os.WriteFile(mcpPluginPath, []byte(mcpContent), 0644); err != nil {
		return fmt.Errorf("failed to create MCP definition in plugin dir: %w", err)
	}
	outputChan <- "[plugin-converter] Copied MCP definition to plugin directory"

	// 5. Create block.yaml for registry
	block := model.BuildingBlock{
		ID:          pluginName,
		Name:        pluginName,
		Type:        "tool",
		Description: description,
		AuthGroups:  authGroupsStr,
	}

	yamlData, err := yaml.Marshal(block)
	if err != nil {
		return fmt.Errorf("failed to marshal block.yaml: %w", err)
	}

	blockPath := filepath.Join(pluginDir, "block.yaml")
	if err := os.WriteFile(blockPath, yamlData, 0644); err != nil {
		return fmt.Errorf("failed to write block.yaml: %w", err)
	}

	// 6. Register MCP server dynamically if Manager is available
	if e.MCPManager != nil {
		outputChan <- "[plugin-converter] Registering MCP server dynamically..."

		// Parse frontmatter
		parts := strings.Split(mcpContent, "---")
		if len(parts) >= 3 {
			var config struct {
				ID      string            `yaml:"id"`
				Name    string            `yaml:"name"`
				Command string            `yaml:"command"`
				Args    []string          `yaml:"args"`
				Env     map[string]string `yaml:"env"`
			}

			if err := yaml.Unmarshal([]byte(parts[1]), &config); err != nil {
				outputChan <- fmt.Sprintf("[plugin-converter] ⚠️ Failed to parse MCP frontmatter for registration: %v", err)
			} else {
				// Create ServerConfig
				serverCfg := mcp.ServerConfig{
					Name:     config.Name,
					Command:  config.Command,
					Args:     config.Args,
					Type:     "dynamic", // Managed dynamically now
					Category: "plugin",
				}

				// Register with Manager
				if err := e.MCPManager.AddServerConfig(ctx, serverCfg); err != nil {
					outputChan <- fmt.Sprintf("[plugin-converter] ⚠️ Failed to register MCP server: %v", err)
				} else {
					outputChan <- fmt.Sprintf("[plugin-converter] ✅ MCP Server '%s' registered and active", config.Name)
				}
			}
		} else {
			outputChan <- "[plugin-converter] ⚠️ Could not parse MCP definition (missing frontmatter)"
		}
	}

	outputChan <- "[plugin-converter] ✅ Plugin promoted successfully!"
	outputChan <- fmt.Sprintf("[plugin-converter] Plugin available as MCP server: %s", pluginName)

	return nil
}

func createMCPDefinition(name, description string, authGroups []string) string {
	authGroupsYAML := ""
	if len(authGroups) > 0 {
		authGroupsYAML = "\nauth_groups:\n"
		for _, g := range authGroups {
			authGroupsYAML += fmt.Sprintf("  - %s\n", g)
		}
	}

	return fmt.Sprintf(`---
id: %s
name: %s
command: node
args:
  - "./.druppie/plugins/%s/index.js"
transport: stdio%s
---
# %s

%s

This plugin was promoted from a plan build and is now available system-wide.

## Usage

The plugin exposes MCP tools that can be used by any agent in Druppie.
Refer to the plugin's README.md for specific tool documentation.
`, name, name, name, authGroupsYAML, name, description)
}

func copyDir(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		// Skip certain directories
		relPath, err := filepath.Rel(src, path)
		if err != nil {
			return err
		}

		// Skip logs, builds, node_modules, etc.
		if strings.Contains(relPath, "node_modules") ||
			strings.Contains(relPath, ".druppie") ||
			strings.Contains(relPath, "logs") {
			if info.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}

		dstPath := filepath.Join(dst, relPath)

		if info.IsDir() {
			return os.MkdirAll(dstPath, info.Mode())
		}

		// Copy file
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(dstPath, data, info.Mode())
	})
}
