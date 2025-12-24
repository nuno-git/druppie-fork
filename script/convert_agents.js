const fs = require('fs');
const path = require('path');

const agentsDir = path.join(__dirname, '../agents');
const files = fs.readdirSync(agentsDir).filter(f => f.endsWith('.yaml'));

console.log(`Found ${files.length} yaml files to convert.`);

files.forEach(file => {
    const yamlPath = path.join(agentsDir, file);
    const content = fs.readFileSync(yamlPath, 'utf8');

    // Extract metadata
    const idMatch = content.match(/^id:\s*(.*)$/m);
    const nameMatch = content.match(/^name:\s*(?:"([^"]*)"|([^"\n]*))$/m);
    const descMatch = content.match(/^description:\s*(?:"([^"]*)"|([^"\n]*))$/m);
    const versionMatch = content.match(/^version:\s*(.*)$/m);
    const modelMatch = content.match(/^model:\s*(?:"([^"]*)"|([^"\n]*))$/m);

    // Arrays need special handling or we just copy the lines
    const skillsLine = content.match(/^skills:\s*\[.*\]/m);
    const toolsLine = content.match(/^tools:\s*\[.*\]/m);

    // Extract instructions
    // Assumes instructions: | followed by indented block at the end of file
    const instructionsMatch = content.match(/instructions:\s*[|>]?\n([\s\S]*)/);

    let body = "";
    if (instructionsMatch) {
        const rawBody = instructionsMatch[1];
        const lines = rawBody.split('\n');

        // Determine indentation from the first non-empty line
        let indent = '';
        const firstLine = lines.find(l => l.trim().length > 0);
        if (firstLine) {
            const match = firstLine.match(/^(\s+)/);
            if (match) indent = match[1];
        }

        if (indent) {
            body = lines.map(line => {
                if (line.startsWith(indent)) return line.substring(indent.length);
                if (line.trim().length === 0) return '';
                return line; // Should not happen if well formed
            }).join('\n');
        } else {
            body = rawBody;
        }
    }

    let mdContent = "---\n";
    if (idMatch) mdContent += `id: ${idMatch[1].trim()}\n`;

    if (nameMatch) {
        const val = nameMatch[1] || nameMatch[2];
        mdContent += `name: "${val.trim()}"\n`;
    }

    if (descMatch) {
        const val = descMatch[1] || descMatch[2];
        mdContent += `description: "${val.trim()}"\n`;
    }

    mdContent += `type: agent\n`; // Force type agent

    if (versionMatch) mdContent += `version: ${versionMatch[1].trim()}\n`;

    if (modelMatch) {
        const val = modelMatch[1] || modelMatch[2];
        mdContent += `model: "${val.trim()}"\n`;
    }

    if (skillsLine) mdContent += `${skillsLine[0]}\n`;
    if (toolsLine) mdContent += `${toolsLine[0]}\n`;

    mdContent += "---\n\n";
    mdContent += body.trim() + "\n"; // Trim leading/trailing newlines of body

    const mdPath = yamlPath.replace('.yaml', '.md');
    fs.writeFileSync(mdPath, mdContent);
    fs.unlinkSync(yamlPath);
    console.log(`Converted ${file} -> ${path.basename(mdPath)}`);
});
