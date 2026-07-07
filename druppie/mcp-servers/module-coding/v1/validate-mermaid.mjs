#!/usr/bin/env node
/**
 * Native Mermaid syntax validator — no browser needed.
 *
 * Replaces mmdc (which requires Chromium) with mermaid.parse()
 * for structural syntax validation inside Docker containers.
 *
 * Usage: node validate-mermaid.mjs < input.mmd
 * Exit: 0 on valid, 1 on syntax error (writes errors to stderr)
 */

import mermaid from "/usr/local/lib/node_modules/@mermaid-js/mermaid-cli/node_modules/mermaid/dist/mermaid.core.mjs";

const chunks = [];
for await (const chunk of process.stdin) {
    chunks.push(chunk);
}
const input = Buffer.concat(chunks).toString("utf-8").trim();

if (!input) {
    process.stderr.write("Empty mermaid input\n");
    process.exit(1);
}

try {
    await mermaid.parse(input, { suppressErrors: false });
    process.exit(0);
} catch (error) {
    const msg = error?.message || String(error);
    if (msg.includes("DOMPurify")) {
        // DOMPurify.init errors are a headless-Node.js quirk, not syntax errors.
        // The parse succeeded; exit cleanly so the LLM can proceed.
        process.exit(0);
    }
    process.stderr.write(`Mermaid parse error: ${msg}\n`);
    process.exit(1);
}
