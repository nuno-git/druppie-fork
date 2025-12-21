const fs = require('fs');
const path = require('path');

// 1. Read Registry
// We treat doc_registry.js as a module by modifying the variable declaration
const registryPath = path.join(__dirname, 'doc_registry.js');
const registryContent = fs.readFileSync(registryPath, 'utf8');

// Replace 'const DOC_REGISTRY =' with 'module.exports =' so we can require it
const jsContent = registryContent.replace('const DOC_REGISTRY =', 'module.exports =');
const tempRegistryPath = path.join(__dirname, 'temp_registry.js');
fs.writeFileSync(tempRegistryPath, jsContent);

let registry;
try {
    registry = require(tempRegistryPath);
} catch (error) {
    console.error("Failed to parse doc_registry.js file:", error);
    process.exit(1);
} finally {
    if (fs.existsSync(tempRegistryPath)) {
        fs.unlinkSync(tempRegistryPath);
    }
}

// 2. Build Index
const index = [];

console.log("Building search index...");

for (const [category, items] of Object.entries(registry)) {
    for (const item of items) {
        try {
            const filePath = path.join(__dirname, item.path);
            // Verify extension is .md or similar text file
            if (fs.existsSync(filePath) && (filePath.endsWith('.md') || filePath.endsWith('.txt') || filePath.endsWith('.sh'))) {
                const content = fs.readFileSync(filePath, 'utf8');
                // Simple cleanup: remove markdown syntax for better searching
                const plainText = content
                    .replace(/[#*`]/g, '')         // Remove #, *, `
                    .replace(/\[(.*?)\]\(.*?\)/g, '$1') // Extract link text
                    .replace(/\s+/g, ' ')          // Collapse whitespace
                    .trim();

                index.push({
                    title: item.name,
                    category: category,
                    path: item.path,
                    // Store simplified content for partial matching, limit size
                    content: plainText.substring(0, 5000)
                });
            } else if (!fs.existsSync(filePath)) {
                // console.warn(`Warning: File referenced in registry not found: ${item.path}`);
            }
        } catch (e) {
            console.error(`Error processing ${item.path}`, e);
        }
    }
}

// 3. Write Database
const outputPath = path.join(__dirname, 'search_index.json');
fs.writeFileSync(outputPath, JSON.stringify(index, null, 2));
console.log(`✅ Search index generated at ${outputPath} containing ${index.length} items.`);
