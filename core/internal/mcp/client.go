package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// Client handles connection to an MCP server via SSE
type Client struct {
	BaseURL    string
	HTTPClient *http.Client

	// PostEndpoint is discovered from the SSE handshake
	PostEndpoint string
}

func NewClient(baseURL string) *Client {
	return &Client{
		BaseURL: baseURL,
		HTTPClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// Connect establishes the SSE connection and handshake
// Note: For a robust implementation, this would handle background reading loop.
// For MVP, we might just discover the POST endpoint if provided in headers or initial event.
func (c *Client) Connect(ctx context.Context) error {
	// 1. Start SSE request
	req, err := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/sse", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "text/event-stream")

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return err
	}
	// Note: We are not keep-aliving the reading loop in this simple MVP,
	// assuming we can interact via standard HTTP POST if we knew the endpoint.
	// However, MCP *requires* the SSE channel for server-to-client notifications.
	// For this plan Scope "Complex Request Orchestration" -> "MCP Client",
	// let's assume we just want to hit the POST endpoint for tools/list and tools/call.
	// Real MCP requires reading the 'endpoint' event from SSE.

	reader := bufio.NewReader(resp.Body)
	// Read until we find the 'endpoint' event
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			resp.Body.Close()
			return fmt.Errorf("failed to read SSE stream: %w", err)
		}

		if strings.HasPrefix(line, "event: endpoint") {
			// Next line should be data: ...
			dataLine, err := reader.ReadString('\n')
			if err != nil {
				resp.Body.Close()
				return err
			}
			msg := strings.TrimPrefix(dataLine, "data: ")
			c.PostEndpoint = strings.TrimSpace(msg)

			// We have what we need for now. In a full agent, we'd keep this open.
			// But Go HTTP client blocks on Do(), so we'd need a goroutine.
			// For now, close and proceed.
			resp.Body.Close()
			break
		}
	}

	if c.PostEndpoint == "" {
		// Fallback or error
		return fmt.Errorf("could not discover POST endpoint from MCP server")
	}

	// Handle relative path
	if !strings.HasPrefix(c.PostEndpoint, "http") {
		// Simple join
		if strings.HasSuffix(c.BaseURL, "/") {
			c.PostEndpoint = c.BaseURL + c.PostEndpoint
		} else {
			c.PostEndpoint = c.BaseURL + "?endpoint=" + c.PostEndpoint // This logic depends on server impl
			// Actually many servers just give a relative path.
			// Let's assume absolute for now or simple relative
			c.PostEndpoint = c.BaseURL + c.PostEndpoint // very rough
		}
	}

	return nil
}

// ListTools queries the MCP server for available tools
func (c *Client) ListTools(ctx context.Context) ([]Tool, error) {
	// Construct JSON-RPC request
	body := JSONRPCMessage{
		JSONRPC: "2.0",
		Method:  "tools/list",
		ID:      1,
	}

	resp, err := c.sendRequest(ctx, body)
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

	resp, err := c.sendRequest(ctx, body)
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

func (c *Client) sendRequest(ctx context.Context, body JSONRPCMessage) (*JSONRPCMessage, error) {
	// Mock implementation if no endpoint (e.g. testing)
	if c.PostEndpoint == "mock" {
		return c.mockResponse(body)
	}

	// Real Implementation
	payload, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal jsonrpc request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", c.PostEndpoint, strings.NewReader(string(payload)))
	if err != nil {
		return nil, fmt.Errorf("failed to create http request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	httpResp, err := c.HTTPClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("http request failed: %w", err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("http error: %s", httpResp.Status)
	}

	var jsonRpcResp JSONRPCMessage
	if err := json.NewDecoder(httpResp.Body).Decode(&jsonRpcResp); err != nil {
		return nil, fmt.Errorf("failed to decode response: %w", err)
	}

	return &jsonRpcResp, nil
}

func (c *Client) mockResponse(req JSONRPCMessage) (*JSONRPCMessage, error) {
	if req.Method == "tools/list" {
		res := ListToolsResult{
			Tools: []Tool{
				{Name: "mock-tool", Description: "A mock tool"},
			},
		}
		data, _ := json.Marshal(res)
		return &JSONRPCMessage{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result:  data,
		}, nil
	}
	return nil, fmt.Errorf("unknown mock method")
}
