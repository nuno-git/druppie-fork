package workflows

// List of all Native Workflows to be registered
var availableWorkflows = []Workflow{
	&VideoCreationWorkflow{},
	// [AUTO-REGISTER] Add new workflows here
}

// RegisterAll loads all defined workflows into the manager
func RegisterAll(m *Manager) {
	for _, w := range availableWorkflows {
		m.Register(w)
	}
}
