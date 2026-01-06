package mcp

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os/exec"
	"strings"
	"time"
)

// Transport defines the communication layer for MCP
type Transport interface {
	Connect(ctx context.Context) error
	Send(ctx context.Context, req JSONRPCMessage) (*JSONRPCMessage, error)
	Close() error
}

// HTTPTransport implements Transport via SSE and Post
type HTTPTransport struct {
	BaseURL      string
	Client       *http.Client
	PostEndpoint string
}

func NewHTTPTransport(baseURL string) *HTTPTransport {
	return &HTTPTransport{
		BaseURL: baseURL,
		Client: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

func (t *HTTPTransport) Connect(ctx context.Context) error {
	// SSE Handshake logic (moved from client.go)
	req, err := http.NewRequestWithContext(ctx, "GET", t.BaseURL+"/sse", nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "text/event-stream")

	resp, err := t.Client.Do(req)
	if err != nil {
		return err
	}
	// We don't read full stream here for MVP to avoid blocking,
	// just peep for endpoint.
	// (Real implementation needs continuous read)
	reader := bufio.NewReader(resp.Body)
	defer resp.Body.Close()

	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			return fmt.Errorf("failed to read SSE stream: %w", err)
		}

		if strings.HasPrefix(line, "event: endpoint") {
			dataLine, err := reader.ReadString('\n')
			if err != nil {
				return err
			}
			msg := strings.TrimPrefix(dataLine, "data: ")
			t.PostEndpoint = strings.TrimSpace(msg)
			break
		}
	}

	if t.PostEndpoint == "" {
		return fmt.Errorf("could not discover POST endpoint")
	}

	// Resolve Relative URL
	if !strings.HasPrefix(t.PostEndpoint, "http") {
		if strings.HasSuffix(t.BaseURL, "/") {
			t.PostEndpoint = t.BaseURL + t.PostEndpoint
		} else {
			t.PostEndpoint = t.BaseURL + "?endpoint=" + t.PostEndpoint
		}
	}
	return nil
}

func (t *HTTPTransport) Send(ctx context.Context, req JSONRPCMessage) (*JSONRPCMessage, error) {
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST", t.PostEndpoint, strings.NewReader(string(payload)))
	if err != nil {
		return nil, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	httpResp, err := t.Client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("http error: %s", httpResp.Status)
	}

	var jsonRpcResp JSONRPCMessage
	if err := json.NewDecoder(httpResp.Body).Decode(&jsonRpcResp); err != nil {
		return nil, err
	}
	return &jsonRpcResp, nil
}

func (t *HTTPTransport) Close() error {
	return nil
}

// StdioTransport implements Transport via local process
type StdioTransport struct {
	Command string
	Args    []string
	cmd     *exec.Cmd
	stdin   io.WriteCloser
	stdout  io.ReadCloser
	reader  *bufio.Reader
}

func NewStdioTransport(command string, args []string) *StdioTransport {
	return &StdioTransport{
		Command: command,
		Args:    args,
	}
}

func (t *StdioTransport) Connect(ctx context.Context) error {
	t.cmd = exec.CommandContext(ctx, t.Command, t.Args...)

	var err error
	t.stdin, err = t.cmd.StdinPipe()
	if err != nil {
		return err
	}
	t.stdout, err = t.cmd.StdoutPipe()
	if err != nil {
		return err
	}

	// Capture stderr to prefix logs
	// stderr, err := t.cmd.StderrPipe()
	// if err != nil {
	// 	return err
	// }
	// // Start a goroutine to log stderr with prefix
	// go func() {
	// 	scanner := bufio.NewScanner(stderr)
	// 	for scanner.Scan() {
	// 		fmt.Printf("[Transport] %s\n", scanner.Text())
	// 	}
	// }()

	if err := t.cmd.Start(); err != nil {
		return err
	}

	t.reader = bufio.NewReader(t.stdout)
	return nil
}

func (t *StdioTransport) Send(ctx context.Context, req JSONRPCMessage) (*JSONRPCMessage, error) {
	bytes, err := json.Marshal(req)
	if err != nil {
		return nil, err
	}

	// Write JSON-RPC message followed by newline
	if _, err := fmt.Fprintf(t.stdin, "%s\n", string(bytes)); err != nil {
		return nil, err
	}

	// Read loop to match ID
	// Note: This blocks until response matches or stream closes.
	// For robust usage, use a proper async reader loop.
	for {
		line, err := t.reader.ReadString('\n')
		if err != nil {
			return nil, err
		}

		// fmt.Printf("[StdioTransport] Received: %s", line)

		var msg JSONRPCMessage
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			// Check if it's logging or headers
			fmt.Printf("[Transport] Ignored non-json line: %s", line)
			continue // Skip logs or invalid lines
		}

		// Robust ID comparison (handle int vs float64 json unmarshal)
		matches := false
		if req.ID == msg.ID {
			matches = true
		} else {
			// Try comparing as strings to handle int vs float64 mismatch (common in JSON)
			reqIDStr := fmt.Sprintf("%v", req.ID)
			msgIDStr := fmt.Sprintf("%v", msg.ID)
			if reqIDStr == msgIDStr {
				matches = true
			}
		}

		if matches {
			return &msg, nil
		}
	}
}

func (t *StdioTransport) Close() error {
	if t.cmd != nil && t.cmd.Process != nil {
		return t.cmd.Process.Kill()
	}
	return nil
}
