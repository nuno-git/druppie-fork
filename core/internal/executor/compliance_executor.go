package executor

import (
	"context"
	"fmt"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
)

// ComplianceExecutor handles compliance agent actions
type ComplianceExecutor struct {
	LLM      llm.Provider
	Registry *registry.Registry
}

func (e *ComplianceExecutor) CanHandle(action string) bool {
	return action == "compliance_check" || action == "validate_policy"
}

func (e *ComplianceExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	switch step.Action {
	case "compliance_check":
		// Use LLM for intelligent compliance checking
		if e.LLM != nil {
			region, _ := step.Params["region"].(string)
			if region == "" {
				region, _ = step.Params["deployment_region"].(string)
			}
			access, _ := step.Params["access_level"].(string)

			language, _ := step.Params["language"].(string)
			if language == "" {
				language = "English" // Default
			}

			// Construct System Prompt (Hierarchical)
			basePrompt := fmt.Sprintf(`You are a Compliance Officer. Your goal is to analyze deployment configurations for violations of:
- Data residency (EU data stay in EU)
- Public access to sensitive data (PII)
- Regulatory frameworks (GDPR, HIPAA, NIS2)

instructions:
1. Provide the output in %s.
2. If violations found: Start with "[VIOLATION]" followed by the description in %s.
3. If compliant: Output "Compliance Check Passed." in %s.

Output format example:
"[VIOLATION] <Localized Description>"`, language, language, language)

			// 2. Lookup Agent Instructions (Override Base)
			defaultPrompt := basePrompt
			if e.Registry != nil && step.AgentID != "" {
				if agent, err := e.Registry.GetAgent(step.AgentID); err == nil && agent.Instructions != "" {
					defaultPrompt = fmt.Sprintf("IMPORTANT: You MUST write in %s language.\n%s", language, agent.Instructions)
				}
			}
			systemPrompt := GetActionPrompt(e.Registry, step.AgentID, step.Action, defaultPrompt)

			// 3. Lookup Skill Instructions (Append)
			// 3. Lookup Skill Instructions (Action + Agent Skills)
			skillInstructions := GetCompositeSkillInstructions(e.Registry, step.AgentID, step.Action)

			if skillInstructions != "" {
				systemPrompt += skillInstructions
			}

			// Construct User Prompt (Specific Task Data)
			userPrompt := fmt.Sprintf(`Analyze this configuration:
Region: %s
Access Level: %s
Additional Context: %v`, region, access, step.Params)

			result, usage, err := e.LLM.Generate(ctx, userPrompt, systemPrompt)
			if err != nil {
				outputChan <- fmt.Sprintf("LLM compliance check failed: %v. Using rule-based fallback.", err)
				return e.executeRuleBasedCheck(step, outputChan)
			}

			outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", strings.TrimSpace(result))

			// Report usage
			if usage.TotalTokens > 0 || usage.EstimatedCost > 0 {
				outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
			}

			return nil
		}

		return e.executeRuleBasedCheck(step, outputChan)

	case "validate_policy":
		policies, _ := step.Params["policy_frameworks"].([]interface{})
		outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=Validating against: %v", policies)
		return nil

	case "audit_request":
		justification, _ := step.Params["justification"].(string)
		if justification == "" {
			justification, _ = step.Params["reason"].(string)
		}
		outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=[AUDIT] Approval Required for: %s", justification)
		return fmt.Errorf("Approval Required from Compliance Group. Please review plan and type '/approve' or '/reject'.")
	}

	return nil
}

func (e *ComplianceExecutor) executeRuleBasedCheck(step model.Step, outputChan chan<- string) error {
	region, _ := step.Params["region"].(string)
	if region == "" {
		region, _ = step.Params["deployment_region"].(string)
	}
	access, _ := step.Params["access_level"].(string)

	if region == "us-east-1" && strings.ToLower(access) == "public" {
		outputChan <- "RESULT_CONSOLE_OUTPUT=[VIOLATION] Data Residency: US Region with Public Access detected."
	} else {
		outputChan <- "RESULT_CONSOLE_OUTPUT=Compliance Check Passed."
	}
	return nil
}
