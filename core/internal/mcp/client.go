package mcp

import (
	"context"
	"encoding/json"
	"fmt"
)

// Client handles connection to an MCP server via Transport
type Client struct {
	Transport Transport
}

func NewClient(t Transport) *Client {
	return &Client{
		Transport: t,
	}
}

// Connect delegates to Transport
func (c *Client) Connect(ctx context.Context) error {
	return c.Transport.Connect(ctx)
}

// ListTools queries the MCP server for available tools
func (c *Client) ListTools(ctx context.Context) ([]Tool, error) {
	// Construct JSON-RPC request
	body := JSONRPCMessage{
		JSONRPC: "2.0",
		Method:  "tools/list",
		ID:      1,
	}

	resp, err := c.Transport.Send(ctx, body)
	if err != nil {
		return nil, err
	}

	if resp.Error != nil {
		return nil, fmt.Errorf("rpc error: %s", resp.Error.Message)
	}

	var result ListToolsResult
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return nil, err
	}

	return result.Tools, nil
}

// CallTool executes a tool
func (c *Client) CallTool(ctx context.Context, name string, args map[string]interface{}) (*CallToolResult, error) {
	reqData := CallToolRequest{
		Name:      name,
		Arguments: args,
	}
	reqBytes, _ := json.Marshal(reqData)

	body := JSONRPCMessage{
		JSONRPC: "2.0",
		Method:  "tools/call",
		Params:  reqBytes,
		ID:      2,
	}

	resp, err := c.Transport.Send(ctx, body)
	if err != nil {
		return nil, err
	}

	if resp.Error != nil {
		return nil, fmt.Errorf("rpc error: %s", resp.Error.Message)
	}

	var result CallToolResult
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		return nil, err
	}

	return &result, nil
}
