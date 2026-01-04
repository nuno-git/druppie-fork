package converter

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"gopkg.in/yaml.v3"
)

// PluginConverter handles conversion of builds to building blocks
type PluginConverter struct {
	Registry *registry.Registry
	RootDir  string
}

func NewPluginConverter(reg *registry.Registry, rootDir string) *PluginConverter {
	return &PluginConverter{
		Registry: reg,
		RootDir:  rootDir,
	}
}

// ConvertBuildToBlock promotes a build to a reusable plugin
func (c *PluginConverter) ConvertBuildToBlock(planID, buildID, name, description string) error {
	// 1. Locate Artifacts
	// .druppie/plans/<planID>/builds/<buildID>
	buildDir := filepath.Join(c.RootDir, ".druppie", "plans", planID, "builds", buildID)
	if _, err := os.Stat(buildDir); os.IsNotExist(err) {
		return fmt.Errorf("build artifacts not found at %s", buildDir)
	}

	// 2. Create Plugin Directory
	// blocks/plugins/<name-sanitized>
	pluginID := fmt.Sprintf("plugin-%s", buildID)
	if name != "" {
		// sanitization logic should be better but strictly:
		pluginID = name // Assume caller sanitized or use UUID
	}

	pluginDir := filepath.Join(c.RootDir, "blocks", "plugins", pluginID)
	if err := os.MkdirAll(pluginDir, 0755); err != nil {
		return fmt.Errorf("failed to create plugin dir: %w", err)
	}

	// 3. Copy Artifacts
	// For now, let's just copy everything? Or select files?
	// Simple recursive copy
	err := copyDir(buildDir, pluginDir)
	if err != nil {
		return fmt.Errorf("failed to copy artifacts: %w", err)
	}

	// 4. Generate block.yaml
	block := model.BuildingBlock{
		ID:          pluginID,
		Name:        name,
		Type:        "plugin",
		Description: description,
		AuthGroups:  []string{}, // Public by default?
	}

	yamlData, err := yaml.Marshal(block)
	if err != nil {
		return fmt.Errorf("failed to marshal block yaml: %w", err)
	}

	if err := os.WriteFile(filepath.Join(pluginDir, "block.yaml"), yamlData, 0644); err != nil {
		return fmt.Errorf("failed to write block.yaml: %w", err)
	}

	// 5. Register in Memory
	c.Registry.RegisterBuildingBlock(block)

	return nil
}

func copyDir(src, dst string) error {
	return filepath.Walk(src, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		relPath, err := filepath.Rel(src, path)
		if err != nil {
			return err
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
