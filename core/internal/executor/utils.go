package executor

import (
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/logging"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
)

// SanitizeAndFixMarkdown cleans up LLM output by:
// 1. Ensuring Mermaid diagrams are wrapped in backticks.
// 2. Fixing common Mermaid syntax errors caused by concatenation (e.g. "Note").
func SanitizeAndFixMarkdown(input string) string {
	result := input
	trimmed := strings.TrimSpace(result)

	// Case 1: Mermaid block without backticks (only if purely code)
	if strings.HasPrefix(trimmed, "mermaid") && !strings.HasPrefix(trimmed, "```") {
		result = "```" + trimmed + "\n```"
	}
	// Case 2: Graph/Flowchart directly without tag
	if strings.HasPrefix(trimmed, "graph ") || strings.HasPrefix(trimmed, "flowchart ") || strings.HasPrefix(trimmed, "sequenceDiagram") {
		result = "```mermaid\n" + trimmed + "\n```"
	}

	// Advanced Sanitization: Fix common Mermaid syntax errors (concatenated lines)
	fixer := func(input string) string {
		// Fix "wordNote" -> "word\nNote" (e.g. appNote -> app\nNote)
		reNote := regexp.MustCompile(`([a-zA-Z0-9_])(Note )`)
		input = reNote.ReplaceAllString(input, "$1\n$2")

		// Fix "wordclassDef" -> "word\nclassDef"
		reClassDef := regexp.MustCompile(`([a-zA-Z0-9_])(classDef )`)
		input = reClassDef.ReplaceAllString(input, "$1\n$2")

		// Fix "wordstyle" -> "word\nstyle"
		reStyle := regexp.MustCompile(`([a-zA-Z0-9_])(style )`)
		input = reStyle.ReplaceAllString(input, "$1\n$2")

		// Fix "wordsubgraph" -> "word\nsubgraph"
		reSubgraph := regexp.MustCompile(`([a-zA-Z0-9_])(subgraph )`)
		input = reSubgraph.ReplaceAllString(input, "$1\n$2")

		// Fix "wordend" at EOL or Newline
		reEnd := regexp.MustCompile(`([a-zA-Z0-9_])(end\s*$)`) // end at EOL
		input = reEnd.ReplaceAllString(input, "$1\n$2")
		reEnd2 := regexp.MustCompile(`([a-zA-Z0-9_])(end\s*\n)`) // end + newline
		input = reEnd2.ReplaceAllString(input, "$1\n$2")

		return input
	}

	// Apply fixer only to content inside mermaid blocks
	reMermaid := regexp.MustCompile("(?s)```mermaid(.*?)```")
	result = reMermaid.ReplaceAllStringFunc(result, func(match string) string {
		inner := match[10 : len(match)-3] // strip ```mermaid and ```
		fixedInner := fixer(inner)

		// Extra sanitization for Flowcharts/Graphs (which don't support 'Note right of')
		lowerInner := strings.ToLower(fixedInner)
		if strings.Contains(lowerInner, "flowchart") || strings.Contains(lowerInner, "graph ") {
			// Comment out "Note right/left/over of ..." lines as they break flowcharts
			reInvalidNote := regexp.MustCompile(`(?i)(?m)^\s*Note (right|left|over) of .*$`)
			fixedInner = reInvalidNote.ReplaceAllString(fixedInner, "%% $0")
		}

		return "```mermaid" + fixedInner + "```"
	})

	return result
}

// GetActionPrompt retrieves a specific prompt for an action from the Agent's definition.
// If not found in the 'prompts' map of the agent, it returns the provided defaultPrompt.
func GetActionPrompt(reg registry.RegistryInterface, agentID string, action string, defaultPrompt string) string {
	if reg == nil || agentID == "" {
		return defaultPrompt
	}

	// Retrieve Agent
	agent, err := reg.GetAgent(agentID)
	if err != nil {
		return defaultPrompt
	}

	// Normalize action to snake_case for lookup
	normalizedAction := strings.ReplaceAll(action, "-", "_")

	// Check Prompts map
	if agent.Prompts != nil {
		// Try exact match
		if p, ok := agent.Prompts[action]; ok && p != "" {
			return p
		}
		// Try normalized match
		if p, ok := agent.Prompts[normalizedAction]; ok && p != "" {
			return p
		}
	}

	return defaultPrompt
}

// AppendLog appends a raw line to the plan's execution.log
func AppendLog(planID, message string) error {
	return logging.AppendRawLog(planID, message)
}

// SaveAsset helper to store files (images, audio, video) in the plan's files directory
func SaveAsset(planID, filename, data string) error {
	basePath := fmt.Sprintf(".druppie/plans/%s/files", planID)
	if err := os.MkdirAll(basePath, 0755); err != nil {
		return err
	}
	fullPath := filepath.Join(basePath, filename)

	var content []byte
	var err error

	if strings.HasPrefix(data, "base64,") {
		parts := strings.Split(data, ",")
		if len(parts) > 1 {
			data = parts[len(parts)-1]
		}
		content, err = base64.StdEncoding.DecodeString(data)
	} else if strings.HasPrefix(data, "http") {
		resp, hErr := http.Get(data)
		if hErr != nil {
			return hErr
		}
		defer resp.Body.Close()
		content, err = io.ReadAll(resp.Body)
	} else {
		// Try base64 anyway, but fallback to raw bytes for mocks/placeholders
		content, err = base64.StdEncoding.DecodeString(data)
		if err != nil {
			content = []byte(data)
			err = nil
		}
	}

	if err != nil {
		return err
	}

	return os.WriteFile(fullPath, content, 0644)
}

// GetSkillInstructions retrieves the system prompt for a skill based on the action name.
// It tries snake_case normalization first, then falls back to the original action name.
func GetSkillInstructions(reg registry.RegistryInterface, action string) string {
	if reg == nil || action == "" {
		return ""
	}

	// Normalize to snake_case as primary lookup key
	normalizedAction := strings.ReplaceAll(action, "-", "_")

	// Try primary lookup
	skill, err := reg.GetSkill(normalizedAction)
	if err == nil && skill.SystemPrompt != "" {
		return skill.SystemPrompt
	} else if normalizedAction != action {
		// Fallback: Try original action if different (though snake_case is preferred)
		if skill, err := reg.GetSkill(action); err == nil && skill.SystemPrompt != "" {
			return skill.SystemPrompt
		}
	}
	return ""
}

// GetCompositeSkillInstructions retrieves skill instructions for BOTH the current action
// AND any skills explicitly assigned to the agent (e.g., "mermaid").
// GetCompositeSkillInstructions retrieves skill instructions for BOTH the current action
// AND any skills explicitly assigned to the agent (e.g., "mermaid").
func GetCompositeSkillInstructions(reg registry.RegistryInterface, agentID string, action string) string {
	return GetCompositeSkillInstructionsWithFilter(reg, agentID, action, nil)
}

// GetCompositeSkillInstructionsWithFilter retrieves skill instructions with an option to exclude specific skills.
func GetCompositeSkillInstructionsWithFilter(reg registry.RegistryInterface, agentID string, action string, excludedSkills []string) string {
	if reg == nil {
		return ""
	}

	// Create exclusion map for O(1) lookup
	excluded := make(map[string]bool)
	for _, s := range excludedSkills {
		excluded[strings.ToLower(s)] = true
	}

	var sb strings.Builder
	seenSkills := make(map[string]bool)

	// 1. Get Action-based Skill
	// Only if action itself is not excluded
	if !excluded[strings.ToLower(action)] {
		actionSkillPrompt := GetSkillInstructions(reg, action)
		if actionSkillPrompt != "" {
			sb.WriteString(fmt.Sprintf("\n\n### SKILL INSTRUCTIONS (%s)\n%s", action, actionSkillPrompt))

			// Mark action as seen (try to guess the ID or just assume we don't want to dupe the *prompt*)
			// Since we don't have the ID from GetSkillInstructions easily without refetching,
			// we rely on the fact that if it's in the agent's list, we might duplicate it.
			// Optimization: Check if action normalization matches a skill ID.
			normalizedAction := strings.ReplaceAll(action, "-", "_")
			seenSkills[normalizedAction] = true
			seenSkills[action] = true
		}
	}

	// 2. Get Agent-assigned Skills
	if agentID != "" {
		if agent, err := reg.GetAgent(agentID); err == nil {
			for _, skillName := range agent.Skills {
				if excluded[strings.ToLower(skillName)] {
					continue
				}

				// Avoid duplicates if the action was already the skill
				// (Assuming simple string matching is enough, or normalize if needed)
				normalizedSkill := strings.ReplaceAll(skillName, "-", "_")

				if seenSkills[normalizedSkill] || seenSkills[skillName] {
					continue
				}

				// Look up the skill object to check its type
				var skillObj model.Skill
				var err error

				// Try normalized then original
				skillObj, err = reg.GetSkill(normalizedSkill)
				if err != nil {
					skillObj, err = reg.GetSkill(skillName)
				}

				if err == nil {
					// STRICT CHECK: Only include if Type is explicitly "skill"
					// (As requested: "select them on the type: skill")
					if skillObj.Type == "skill" && skillObj.SystemPrompt != "" {
						sb.WriteString(fmt.Sprintf("\n\n### SKILL INSTRUCTIONS (%s)\n%s", skillName, skillObj.SystemPrompt))
						seenSkills[normalizedSkill] = true
						seenSkills[skillName] = true
					}
				}
			}
		}
	}

	return sb.String()
}
