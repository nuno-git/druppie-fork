package executor

import (
	"context"
	"fmt"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// ComplianceExecutor handles compliance agent actions
type ComplianceExecutor struct{}

func (e *ComplianceExecutor) CanHandle(action string) bool {
	return action == "compliance_check" || action == "validate_policy"
}

func (e *ComplianceExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	switch step.Action {
	case "compliance_check":
		// Simple validation log
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

	case "validate_policy":
		// Log policy check
		policies, _ := step.Params["policy_frameworks"].([]interface{})
		outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=Validating against: %v", policies)
		return nil

	case "audit_request":
		// This should trigger an approval
		// We simulate this by returning an error that forces the TaskManager to pause?
		// No, better to just be honest.

		justification, _ := step.Params["justification"].(string)

		outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=[AUDIT] Approval Required for: %s", justification)

		// To force "Waiting Input" in TaskManager, we can return a specific error or
		// if the TaskManager supports "requires_approval" status naturally.
		// Looking at TaskManager (line 700+), it handles "ask_questions", "content-review" as specific cases.
		// "audit_request" is not there.

		// Ideally we should update TaskManager to handle "audit_request" as interactive.
		// But as an Executor, we can't easily change TaskManager logic.
		// However, we can return an error that says "Approval Required" which pauses the step!
		// The TaskManager pauses on error.

		return fmt.Errorf("Approval Required from Compliance Group. Please review plan and type '/approve' or '/reject'.")
	}

	return nil
}
