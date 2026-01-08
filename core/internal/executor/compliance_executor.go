package executor

import (
	"context"
	"fmt"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
)

// ComplianceExecutor handles compliance agent actions
type ComplianceExecutor struct {
	LLM llm.Provider
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

			prompt := fmt.Sprintf(`You are a Compliance Officer. Analyze the following deployment configuration for compliance violations:

Region: %s
Access Level: %s
Additional Context: %v

Check for:
- Data residency requirements (EU data must stay in EU, healthcare data restrictions)
- Public access to sensitive data
- Regulatory compliance (GDPR, HIPAA, etc.)

Output format:
If violations found: "[VIOLATION] <description>"
If compliant: "Compliance Check Passed."`, region, access, step.Params)

			result, usage, err := e.LLM.Generate(ctx, "Compliance Check", prompt)
			if err != nil {
				outputChan <- fmt.Sprintf("LLM compliance check failed: %v. Using rule-based fallback.", err)
				return e.executeRuleBasedCheck(step, outputChan)
			}

			outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", strings.TrimSpace(result))

			// Report usage
			if usage.TotalTokens > 0 {
				outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens)
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
