#!/usr/bin/env node
const readline = require('readline');

const rl = readline.createInterface({
  input: process.stdin,
  output: process.stdout,
  terminal: false
});

rl.on('line', (line) => {
  if (!line.trim()) return;
  try {
    const request = JSON.parse(line);
    let response;

    if (request.method === 'initialize') {
      response = {
        jsonrpc: '2.0',
        id: request.id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'calc-mcp', version: '1.0.0' }
        }
      };
    } else if (request.method === 'tools/list') {
      response = {
        jsonrpc: '2.0',
        id: request.id,
        result: {
          tools: [{
            name: "add",
            description: "Adds two numbers (a, b) and returns the sum",
            inputSchema: {
              type: "object",
              properties: {
                a: { type: "number", description: "The first number" },
                b: { type: "number", description: "The second number" }
              },
              required: ["a", "b"]
            }
          }]
        }
      };
    } else if (request.method === 'tools/call') {
      const toolName = request.params.name;
      const args = request.params.arguments || {};

      if (toolName === 'add') {
        const sum = Number(args.a) + Number(args.b);
        response = {
          jsonrpc: '2.0',
          id: request.id,
          result: { content: [{ type: "text", text: String(sum) }] }
        };
      } else {
        response = { jsonrpc: '2.0', id: request.id, error: { code: -32601, message: "Tool not found" } };
      }
    }

    if (response) console.log(JSON.stringify(response));
  } catch (e) {
    console.log(JSON.stringify({ jsonrpc: '2.0', id: null, error: { code: -32700, message: "Parse error" } }));
  }
});