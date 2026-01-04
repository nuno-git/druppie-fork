package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"strings"

	"github.com/spf13/cobra"
)

func newGenerateCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "generate",
		Short: "Generate search index from documentation",
		Run: func(cmd *cobra.Command, args []string) {
			if err := generateSearchIndex(); err != nil {
				fmt.Printf("Error generating index: %v\n", err)
				os.Exit(1)
			}
		},
	}
}

// IndexItem struct matching the JS output
type IndexItem struct {
	Title    string `json:"title"`
	Category string `json:"category"`
	Path     string `json:"path"`
	Content  string `json:"content"`
}

func generateSearchIndex() error {
	fmt.Println("Building search index...")

	if err := ensureProjectRoot(); err != nil {
		fmt.Printf("Warning: %v. Using current directory.\n", err)
	}

	cwd, _ := os.Getwd()
	fmt.Println("Working directory:", cwd)

	// 1. Read doc_registry.js
	registryPath := "doc_registry.js"
	content, err := os.ReadFile(registryPath)
	if err != nil {
		// Fallback: try to find it in default locations if we are running from binary in weird location
		// But Dockerfile ensures we are in /app and doc_registry.js is in /app
		return fmt.Errorf("failed to read doc_registry.js: %w", err)
	}

	// 2. Parse Registry using Regex
	// Format: { name: "Overview", path: "blocks/overview.md" },
	// We also need to capture Categories?
	// Format: "blocks": [ ... ]

	index := []IndexItem{}

	// Regex to match category blocks: "key": [ ... ]
	// Match quoted or unquoted keys
	catRegex := regexp.MustCompile(`"?(\w+)"?:\s*\[([\s\S]*?)\]`)
	matches := catRegex.FindAllStringSubmatch(string(content), -1)

	for _, match := range matches {
		category := match[1]
		blockContent := match[2]

		// Skip "scripts" or "tools" if desired? JS script included them. We include them.

		// Regex to match items: { name: "...", path: "..." }
		itemRegex := regexp.MustCompile(`\{\s*name:\s*"(.*?)",\s*path:\s*"(.*?)"\s*\}`)
		items := itemRegex.FindAllStringSubmatch(blockContent, -1)

		for _, item := range items {
			title := item[1]
			relPath := item[2]

			// Read file content
			fileContent, err := os.ReadFile(relPath)
			if err != nil {
				// Fail silently like the JS script (it just continues if not found)
				continue
			}

			text := string(fileContent)

			// 3. Clean content
			// Strip Frontmatter
			if strings.HasSuffix(relPath, ".md") {
				// Remove --- ... --- at start
				reFront := regexp.MustCompile(`(?s)^---\n.*?\n---\n`)
				text = reFront.ReplaceAllString(text, "")
			}

			// Remove Markdown syntax
			// Simple stripping of #, *, backticks
			reMd := regexp.MustCompile(`[#*\x60]`) // \x60 is backtick
			text = reMd.ReplaceAllString(text, "")

			// Links [text](url) -> text
			reLink := regexp.MustCompile(`\[(.*?)\]\(.*?\)`)
			text = reLink.ReplaceAllString(text, "$1")

			// Collapse whitespace
			reSpace := regexp.MustCompile(`\s+`)
			text = reSpace.ReplaceAllString(text, " ")
			text = strings.TrimSpace(text)

			// Truncate to 5000 chars
			if len(text) > 5000 {
				text = text[:5000]
			}

			index = append(index, IndexItem{
				Title:    title,
				Category: category,
				Path:     relPath,
				Content:  text,
			})
		}
	}

	// 4. Write output
	outPath := "search_index.json"
	bytes, _ := json.MarshalIndent(index, "", "  ")
	if err := os.WriteFile(outPath, bytes, 0644); err != nil {
		return fmt.Errorf("failed to write index: %w", err)
	}

	fmt.Printf("✅ Search index generated at %s containing %d items.\n", outPath, len(index))
	return nil
}
