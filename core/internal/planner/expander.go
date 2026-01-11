package planner

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// expandLoop generates N steps based on a template and an iterator source found in previous steps.
// It searches backwards for the 'iterator_source' param.
func (p *Planner) expandLoop(triggerStep model.Step, history []model.Step, currentSteps []model.Step) ([]model.Step, error) {
	// 1. Extract Params from Trigger Step
	// Expected:
	//   iterator_key: "av_script" (Where to look for the array)
	//   target_agent: "audio_creator"
	//   target_action: "text_to_speech"
	//   param_mapping: {"audio_text": "audio_text", "scene_id": "scene_id"} logic: target_param -> source_item_key

	iteratorKey, _ := triggerStep.Params["iterator_key"].(string)
	if iteratorKey == "" {
		iteratorKey = "av_script" // Default
	}

	targetAgent, _ := triggerStep.Params["target_agent"].(string)
	targetAction, _ := triggerStep.Params["target_action"].(string)

	// Normalize to snake_case
	targetAgent = strings.ReplaceAll(strings.ToLower(targetAgent), "-", "_")
	targetAction = strings.ReplaceAll(strings.ToLower(targetAction), "-", "_")

	if targetAgent == "" || targetAction == "" {
		return nil, fmt.Errorf("expand_loop requires target_agent and target_action")
	}

	// 2. Find the Iterator Array
	var iteratorArray []interface{}

	// A. Check Trigger Step params first (Highest Priority)
	if val, ok := triggerStep.Params[iteratorKey]; ok {
		if list, isList := val.([]interface{}); isList {
			iteratorArray = list
		} else {
			// CAST FAILURE DEBUG
			if p.Debug {
				fmt.Printf("[Expander] Found key '%s' in TriggerStep but cast failed. Type: %T\n", iteratorKey, val)
			}
		}
	}

	// B. If not found, search History (Backwards)
	if iteratorArray == nil {
		for i := len(history) - 1; i >= 0; i-- {
			step := history[i]
			// Check generic params
			if val, ok := step.Params[iteratorKey]; ok {
				if list, isList := val.([]interface{}); isList {
					iteratorArray = list
					break
				} else if strVal, isStr := val.(string); isStr {
					// Try parsing string as JSON array
					var parsedList []interface{}
					if err := json.Unmarshal([]byte(strVal), &parsedList); err == nil {
						iteratorArray = parsedList
						break
					} else {
						if p.Debug {
							fmt.Printf("[Expander] Found string key '%s' in History Step %d but parse failed: %v\n", iteratorKey, step.ID, err)
						}
					}
				} else {
					if p.Debug {
						fmt.Printf("[Expander] Found key '%s' in History Step %d but cast failed. Type: %T\n", iteratorKey, step.ID, val)
					}
				}
			}
			// Check generic params inside "result" map wrapper
			if result, ok := step.Params["result"].(map[string]interface{}); ok {
				if val, ok := result[iteratorKey]; ok {
					if list, isList := val.([]interface{}); isList {
						iteratorArray = list
						break
					} else if strVal, isStr := val.(string); isStr {
						// Support stringified JSON inside result map
						var parsedList []interface{}
						if err := json.Unmarshal([]byte(strVal), &parsedList); err == nil {
							iteratorArray = parsedList
							break
						}
					}
				}
			}
		}
	}

	// C. Check Result String (Slow path, but necessary fallback)
	if iteratorArray == nil {
		for i := len(history) - 1; i >= 0; i-- {
			step := history[i]
			// Only try if Result contains the key and looks like JSON
			if strings.Contains(step.Result, iteratorKey) && (strings.HasPrefix(strings.TrimSpace(step.Result), "{") || strings.HasPrefix(strings.TrimSpace(step.Result), "[")) {
				var tempMap map[string]interface{}
				// Try unmarshal
				if err := json.Unmarshal([]byte(step.Result), &tempMap); err == nil {
					if val, ok := tempMap[iteratorKey]; ok {
						if list, isList := val.([]interface{}); isList {
							iteratorArray = list
							break
						}
					}
				}
			}
		}
	}

	if iteratorArray == nil {
		return nil, fmt.Errorf("iterator array '%s' not found in history or trigger params", iteratorKey)
	}

	// 3. Generate New Steps
	var newSteps []model.Step
	startID := triggerStep.ID + 1
	if len(currentSteps) > 0 {
		startID = currentSteps[len(currentSteps)-1].ID + 1
	}

	for i, item := range iteratorArray {
		itemMap, ok := item.(map[string]interface{})
		if !ok {
			continue // Skip invalid items
		}

		newStep := model.Step{
			ID:      startID + i,
			AgentID: targetAgent,
			Action:  targetAction,
			Status:  "pending",
			Params:  make(map[string]interface{}),
		}

		// Apply Mapping
		// We copy everything from the itemMap to params for simplicity, OR use mapping if strict
		// Strategy: Copy ALL fields from the scene object into the new step params
		for k, v := range itemMap {
			newStep.Params[k] = v
		}

		// Add context
		newStep.Params["scene_index"] = i
		// Ensure scene_id exists
		if _, ok := newStep.Params["scene_id"]; !ok {
			newStep.Params["scene_id"] = i + 1
		}

		// Specific handling for Video Generation dependencies
		// If we are generating video, we might need audio/image files from PREVIOUS expansion results.
		if strings.Contains(targetAction, "video") {
			sid := newStep.Params["scene_id"]

			// 1. Try to find actual Audio File from history
			audioFile := fmt.Sprintf("audio_scene_%v.mp3", sid) // Default if nothing found
			for _, h := range history {
				// Match audio creator and same scene_id
				if h.Status == "completed" && (h.AgentID == "audio_creator" || h.Action == "text_to_speech") {
					if fmt.Sprintf("%v", h.Params["scene_id"]) == fmt.Sprintf("%v", sid) {
						// Extract from result string (e.g. "AUDIO_FILE: audio_scene_1.wav")
						if strings.Contains(h.Result, "AUDIO_FILE:") {
							lines := strings.Split(h.Result, "\n")
							for _, line := range lines {
								if strings.HasPrefix(line, "AUDIO_FILE:") {
									audioFile = strings.TrimSpace(strings.TrimPrefix(line, "AUDIO_FILE:"))
									break
								}
							}
						} else if val, ok := h.Params["audio_file"].(string); ok {
							audioFile = val
						}
						break
					}
				}
			}
			newStep.Params["audio_file"] = audioFile

			// 2. Try to find actual Image File from history
			imageFile := fmt.Sprintf("image_scene_%v.png", sid) // Default
			for _, h := range history {
				if h.Status == "completed" && (h.AgentID == "image_creator" || h.Action == "image_generation") {
					if fmt.Sprintf("%v", h.Params["scene_id"]) == fmt.Sprintf("%v", sid) {
						if strings.Contains(h.Result, "IMAGE_FILE:") {
							lines := strings.Split(h.Result, "\n")
							for _, line := range lines {
								if strings.HasPrefix(line, "IMAGE_FILE:") {
									imageFile = strings.TrimSpace(strings.TrimPrefix(line, "IMAGE_FILE:"))
									break
								}
							}
						} else if val, ok := h.Params["image_file"].(string); ok {
							imageFile = val
						}
						break
					}
				}
			}
			newStep.Params["image_file"] = imageFile
		}

		newSteps = append(newSteps, newStep)
	}

	return newSteps, nil
}
